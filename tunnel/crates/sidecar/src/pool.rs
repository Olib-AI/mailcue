//! Per-tunnel connection pool.
//!
//! Each pool slot owns one `Channel<TcpStream>` that has already
//! completed Noise IK handshake + `Hello`/`HelloAck`. Slots are leased to
//! callers; on drop the conn returns to the idle queue. A background
//! keepalive loop pings each idle conn and prunes dead ones.
//!
//! Health model: a tunnel becomes *unhealthy* after
//! `unhealthy_after_consecutive_failures` consecutive failed
//! Ping/Relay operations on its conns. The next successful op marks it
//! healthy again.

use std::collections::{HashMap, VecDeque};
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, anyhow};
use parking_lot::Mutex;
use tokio::net::TcpStream;
use tokio::sync::Notify;
use tokio::time::timeout;
use tracing::{debug, info, warn};

use mailcue_relay_proto::{Channel, Frame, HandshakeRole, PROTO_VERSION, perform_handshake};

use crate::config::{REASSEMBLY_HEADROOM_BYTES, SidecarConfig};
use crate::tunnels::Tunnel;

/// Wrapper around a `Channel<TcpStream>` plus pool bookkeeping.
pub struct Conn {
    /// The underlying authenticated, post-handshake channel.
    pub channel: Channel<TcpStream>,
    /// Tunnel id this conn was opened for (used by metrics / logs).
    pub tunnel_id: String,
    /// Last successful interaction (creation, Pong, Relay completion).
    pub last_used: Instant,
}

/// Live pool stats for one tunnel.
#[derive(Debug)]
struct TunnelStats {
    consecutive_failures: u32,
    healthy: bool,
    inflight: u64,
    requests_ok: u64,
    requests_err: u64,
    last_success: Option<u64>,
}

impl Default for TunnelStats {
    fn default() -> Self {
        // New tunnels are optimistically healthy: the selector will route
        // a probe relay through them, and they only flip to unhealthy
        // after `unhealthy_after_consecutive_failures` consecutive
        // failures. This avoids a chicken-and-egg deadlock where the
        // pool never opens a conn because no relay is sent because
        // nothing is healthy.
        Self {
            consecutive_failures: 0,
            healthy: true,
            inflight: 0,
            requests_ok: 0,
            requests_err: 0,
            last_success: None,
        }
    }
}

#[derive(Default)]
struct TunnelSlot {
    idle: VecDeque<Conn>,
    stats: TunnelStats,
}

/// Shared connection pool, keyed by tunnel id.
#[derive(Clone)]
pub struct Pool {
    inner: Arc<Mutex<HashMap<String, TunnelSlot>>>,
    cfg: Arc<SidecarConfig>,
    client_static_priv: Arc<[u8; 32]>,
    bytes_total: Arc<HashMap<String, AtomicU64>>,
    notify: Arc<Notify>,
}

impl Pool {
    /// Build a new pool.
    #[must_use]
    pub fn new(cfg: Arc<SidecarConfig>, client_static_priv: [u8; 32]) -> Self {
        Self {
            inner: Arc::new(Mutex::new(HashMap::new())),
            cfg,
            client_static_priv: Arc::new(client_static_priv),
            bytes_total: Arc::new(HashMap::new()),
            notify: Arc::new(Notify::new()),
        }
    }

    /// Drain all conns for tunnels not in `keep_ids`.
    pub fn retain(&self, keep_ids: &std::collections::BTreeSet<String>) {
        let mut g = self.inner.lock();
        let removed: Vec<String> = g
            .keys()
            .filter(|k| !keep_ids.contains(*k))
            .cloned()
            .collect();
        for k in &removed {
            g.remove(k);
            info!(tunnel = %k, "draining removed tunnel");
        }
    }

    /// Snapshot health for the selector.
    #[must_use]
    pub fn healthy_ids(&self) -> std::collections::BTreeSet<String> {
        let g = self.inner.lock();
        g.iter()
            .filter_map(|(k, v)| {
                if v.stats.healthy {
                    Some(k.clone())
                } else {
                    None
                }
            })
            .collect()
    }

    /// Snapshot of every known tunnel (registered with `ensure`) regardless of health.
    #[must_use]
    #[allow(dead_code)] // surfaced for tooling / diagnostics; not used on the hot path.
    pub fn all_ids(&self) -> Vec<String> {
        self.inner.lock().keys().cloned().collect()
    }

    /// Snapshot tunnel-level stats for the metrics endpoint.
    #[must_use]
    pub fn stats_snapshot(&self) -> Vec<TunnelStatsSnapshot> {
        let g = self.inner.lock();
        g.iter()
            .map(|(k, v)| TunnelStatsSnapshot {
                id: k.clone(),
                healthy: v.stats.healthy,
                idle: u64::try_from(v.idle.len()).unwrap_or(u64::MAX),
                inflight: v.stats.inflight,
                requests_ok: v.stats.requests_ok,
                requests_err: v.stats.requests_err,
                last_success: v.stats.last_success,
            })
            .collect()
    }

    /// Register a tunnel id so health metrics include it even before the
    /// first successful conn.
    pub fn ensure(&self, tunnel_id: &str) {
        let mut g = self.inner.lock();
        g.entry(tunnel_id.to_string()).or_default();
    }

    /// Attempt to acquire (or create) a leased connection for `tunnel`.
    ///
    /// On `Ok`, the caller is responsible for calling `release` (success)
    /// or `discard` (failure) when they are done.
    pub async fn lease(&self, tunnel: &Tunnel) -> Result<Conn> {
        // Try idle pool first.
        loop {
            let popped = {
                let mut g = self.inner.lock();
                let slot = g.entry(tunnel.id.clone()).or_default();
                slot.idle.pop_front()
            };
            if let Some(c) = popped {
                let idle_for = c.last_used.elapsed();
                if idle_for > Duration::from_secs(self.cfg.pool_idle_timeout_secs) {
                    debug!(
                        tunnel = %tunnel.id,
                        idle_secs = idle_for.as_secs(),
                        "evicting expired idle conn",
                    );
                    drop(c);
                    continue;
                }
                self.mark_inflight(&tunnel.id, true);
                return Ok(c);
            }
            break;
        }

        // No idle — open a fresh one.
        let conn = self.open(tunnel).await?;
        self.mark_inflight(&tunnel.id, true);
        Ok(conn)
    }

    /// Release a successful conn back to the idle pool, capped by
    /// `pool_idle_per_tunnel`.
    pub fn release(&self, mut conn: Conn) {
        conn.last_used = Instant::now();
        let tunnel_id = conn.tunnel_id.clone();

        let mut g = self.inner.lock();
        let slot = g.entry(tunnel_id.clone()).or_default();
        slot.stats.healthy = true;
        slot.stats.consecutive_failures = 0;
        slot.stats.requests_ok = slot.stats.requests_ok.saturating_add(1);
        slot.stats.last_success = Some(unix_now());
        if slot.stats.inflight > 0 {
            slot.stats.inflight -= 1;
        }

        if slot.idle.len() < self.cfg.pool_idle_per_tunnel {
            slot.idle.push_back(conn);
        } else {
            drop(conn);
        }
        drop(g);
        self.notify.notify_waiters();
    }

    /// Drop a failed conn and bump failure counters.
    pub fn discard(&self, conn: Conn, reason: &str) {
        let tunnel_id = conn.tunnel_id.clone();
        drop(conn);

        let mut g = self.inner.lock();
        let slot = g.entry(tunnel_id.clone()).or_default();
        slot.stats.consecutive_failures = slot.stats.consecutive_failures.saturating_add(1);
        slot.stats.requests_err = slot.stats.requests_err.saturating_add(1);
        if slot.stats.inflight > 0 {
            slot.stats.inflight -= 1;
        }
        if slot.stats.consecutive_failures >= self.cfg.unhealthy_after_consecutive_failures {
            if slot.stats.healthy {
                warn!(tunnel = %tunnel_id, %reason, "tunnel marked unhealthy");
            }
            slot.stats.healthy = false;
        }
    }

    fn mark_inflight(&self, tunnel_id: &str, inc: bool) {
        let mut g = self.inner.lock();
        let slot = g.entry(tunnel_id.to_string()).or_default();
        if inc {
            slot.stats.inflight = slot.stats.inflight.saturating_add(1);
        } else if slot.stats.inflight > 0 {
            slot.stats.inflight -= 1;
        }
    }

    /// Bytes-relayed accumulator for metrics.
    #[must_use]
    pub fn bytes_total(&self, tunnel_id: &str) -> u64 {
        self.bytes_total
            .get(tunnel_id)
            .map_or(0, |a| a.load(Ordering::Relaxed))
    }

    /// Open a new conn: TCP connect, Noise IK handshake, Hello/HelloAck.
    async fn open(&self, tunnel: &Tunnel) -> Result<Conn> {
        let endpoint = tunnel.endpoint();
        let connect_to = Duration::from_secs(self.cfg.connect_timeout_secs);

        let mut tcp = match timeout(connect_to, TcpStream::connect(&endpoint)).await {
            Ok(Ok(s)) => s,
            Ok(Err(e)) => {
                self.note_open_failure(&tunnel.id, &format!("connect: {e}"));
                return Err(anyhow!("connect {endpoint}: {e}"));
            }
            Err(_) => {
                self.note_open_failure(&tunnel.id, "connect timeout");
                return Err(anyhow!("connect timeout {endpoint}"));
            }
        };
        let _ = tcp.set_nodelay(true);

        let role = HandshakeRole::Initiator {
            remote_static: tunnel.edge_pubkey,
        };
        let (transport, _peer_static) = match timeout(
            connect_to,
            perform_handshake(&mut tcp, &self.client_static_priv, role),
        )
        .await
        {
            Ok(Ok(p)) => p,
            Ok(Err(e)) => {
                self.note_open_failure(&tunnel.id, &format!("handshake: {e}"));
                return Err(anyhow!("handshake {endpoint}: {e}"));
            }
            Err(_) => {
                self.note_open_failure(&tunnel.id, "handshake timeout");
                return Err(anyhow!("handshake timeout {endpoint}"));
            }
        };

        let mut channel = Channel::new(tcp, transport, REASSEMBLY_HEADROOM_BYTES);

        let req_to = Duration::from_secs(self.cfg.request_timeout_secs);

        if let Err(e) = timeout(
            req_to,
            channel.send_frame(&Frame::Hello {
                proto_version: PROTO_VERSION,
                client_id: self.cfg.client_id.clone(),
                sidecar_version: env!("CARGO_PKG_VERSION").to_string(),
            }),
        )
        .await
        .map_err(|_| anyhow!("Hello write timeout"))
        .and_then(|r| r.context("send Hello"))
        {
            self.note_open_failure(&tunnel.id, &format!("send Hello: {e}"));
            return Err(e);
        }

        let ack = timeout(req_to, channel.recv_frame())
            .await
            .map_err(|_| anyhow!("HelloAck read timeout"))?
            .context("recv HelloAck")?;
        match ack {
            Frame::HelloAck { proto_version, .. } if proto_version == PROTO_VERSION => {}
            Frame::HelloAck { proto_version, .. } => {
                self.note_open_failure(
                    &tunnel.id,
                    &format!("HelloAck proto_version mismatch: {proto_version}"),
                );
                return Err(anyhow!("HelloAck proto_version mismatch"));
            }
            Frame::Error { code, message, .. } => {
                self.note_open_failure(&tunnel.id, &format!("edge error: {code:?}: {message}"));
                return Err(anyhow!("edge error after Hello: {code:?}: {message}"));
            }
            other => {
                self.note_open_failure(&tunnel.id, &format!("expected HelloAck, got {other:?}"));
                return Err(anyhow!("expected HelloAck"));
            }
        }

        // Successful open counts as a health success.
        {
            let mut g = self.inner.lock();
            let slot = g.entry(tunnel.id.clone()).or_default();
            slot.stats.healthy = true;
            slot.stats.consecutive_failures = 0;
            slot.stats.last_success = Some(unix_now());
        }

        Ok(Conn {
            channel,
            tunnel_id: tunnel.id.clone(),
            last_used: Instant::now(),
        })
    }

    fn note_open_failure(&self, tunnel_id: &str, reason: &str) {
        let mut g = self.inner.lock();
        let slot = g.entry(tunnel_id.to_string()).or_default();
        slot.stats.consecutive_failures = slot.stats.consecutive_failures.saturating_add(1);
        slot.stats.requests_err = slot.stats.requests_err.saturating_add(1);
        if slot.stats.consecutive_failures >= self.cfg.unhealthy_after_consecutive_failures {
            if slot.stats.healthy {
                warn!(tunnel = %tunnel_id, %reason, "tunnel marked unhealthy");
            }
            slot.stats.healthy = false;
        }
        debug!(tunnel = %tunnel_id, %reason, "tunnel open failure");
    }

    /// Run keepalive pings on idle conns, forever. Spawn this once.
    pub async fn keepalive_loop(self) {
        let interval = Duration::from_secs(self.cfg.keepalive_interval_secs);
        loop {
            tokio::time::sleep(interval).await;

            // Collect tunnel ids holding idle conns under a short lock.
            let tunnel_ids: Vec<String> = {
                let g = self.inner.lock();
                g.iter()
                    .filter(|(_, slot)| !slot.idle.is_empty())
                    .map(|(k, _)| k.clone())
                    .collect()
            };

            for tid in tunnel_ids {
                // Pop one idle conn at a time and ping it; release if ok.
                let conn_opt = {
                    let mut g = self.inner.lock();
                    g.entry(tid.clone()).or_default().idle.pop_front()
                };
                if let Some(mut conn) = conn_opt {
                    match ping(&mut conn, &self.cfg).await {
                        Ok(()) => {
                            self.release(conn);
                        }
                        Err(e) => {
                            self.discard(conn, &format!("keepalive ping: {e}"));
                        }
                    }
                }
            }
        }
    }
}

/// Snapshot for the metrics endpoint.
#[derive(Debug, Clone)]
pub struct TunnelStatsSnapshot {
    /// Tunnel id.
    pub id: String,
    /// Healthy bit.
    pub healthy: bool,
    /// Idle conns currently in pool.
    pub idle: u64,
    /// In-flight relays.
    pub inflight: u64,
    /// Cumulative successful relays.
    pub requests_ok: u64,
    /// Cumulative failed relays.
    pub requests_err: u64,
    /// Last success unix-seconds.
    pub last_success: Option<u64>,
}

async fn ping(conn: &mut Conn, cfg: &SidecarConfig) -> Result<()> {
    let nonce: u64 = rand::random();
    let req_to = Duration::from_secs(cfg.request_timeout_secs);
    timeout(
        req_to,
        conn.channel.send_frame(&Frame::Ping {
            ts_unix: unix_now(),
            nonce,
        }),
    )
    .await
    .map_err(|_| anyhow!("ping write timeout"))?
    .context("send Ping")?;

    let reply = timeout(req_to, conn.channel.recv_frame())
        .await
        .map_err(|_| anyhow!("pong read timeout"))?
        .context("recv Pong")?;
    match reply {
        Frame::Pong {
            nonce: echoed_nonce,
            ..
        } if echoed_nonce == nonce => {
            conn.last_used = Instant::now();
            Ok(())
        }
        Frame::Pong { .. } => Err(anyhow!("pong nonce mismatch")),
        Frame::Error { code, message, .. } => {
            Err(anyhow!("edge error during ping: {code:?}: {message}"))
        }
        _ => Err(anyhow!("expected Pong, got something else")),
    }
}

fn unix_now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}
