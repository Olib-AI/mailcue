//! Minimal HTTP listener for `/healthz`, `/readyz`, `/metrics`.
//!
//! We use `hyper` directly (no `axum`) to keep the dependency footprint
//! tight — Prometheus text format is trivial to render by hand.

use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};

use anyhow::Result;
use http_body_util::Full;
use hyper::body::{Bytes, Incoming};
use hyper::server::conn::http1;
use hyper::service::service_fn;
use hyper::{Request, Response, StatusCode};
use hyper_util::rt::TokioIo;
use tokio::net::TcpListener;
use tracing::{debug, info, warn};

use crate::pool::Pool;
use crate::relay::SmtpReply;

/// Shared metrics state.
pub struct Metrics {
    pub(crate) ready: AtomicBool,
    pub(crate) smtp_2xx: AtomicU64,
    pub(crate) smtp_4xx: AtomicU64,
    pub(crate) smtp_5xx: AtomicU64,
    pool: Pool,
}

impl Metrics {
    /// Build a new metrics holder bound to a shared pool reference.
    #[must_use]
    pub fn new(pool: Pool) -> Self {
        Self {
            ready: AtomicBool::new(false),
            smtp_2xx: AtomicU64::new(0),
            smtp_4xx: AtomicU64::new(0),
            smtp_5xx: AtomicU64::new(0),
            pool,
        }
    }

    /// Mark the sidecar ready (SMTP listener bound, config loaded).
    pub fn set_ready(&self, ready: bool) {
        self.ready.store(ready, Ordering::SeqCst);
    }

    /// Record one SMTP submission outcome by reply class.
    pub fn smtp_record(&self, reply: &SmtpReply) {
        match reply.code / 100 {
            2 => self.smtp_2xx.fetch_add(1, Ordering::Relaxed),
            4 => self.smtp_4xx.fetch_add(1, Ordering::Relaxed),
            5 => self.smtp_5xx.fetch_add(1, Ordering::Relaxed),
            _ => 0,
        };
    }
}

/// Run the metrics HTTP listener forever (until cancel fires).
pub async fn run(
    listener: TcpListener,
    metrics: Arc<Metrics>,
    mut cancel: tokio::sync::watch::Receiver<bool>,
) {
    info!(listen = ?listener.local_addr().ok(), "sidecar metrics listener up");
    loop {
        tokio::select! {
            biased;
            res = cancel.changed() => {
                if res.is_err() || *cancel.borrow() {
                    break;
                }
            }
            accept_res = listener.accept() => {
                let (stream, _peer) = match accept_res {
                    Ok(p) => p,
                    Err(e) => {
                        warn!(error = %e, "metrics accept failed");
                        continue;
                    }
                };
                let metrics = Arc::clone(&metrics);
                tokio::spawn(async move {
                    let io = TokioIo::new(stream);
                    let svc = service_fn(move |req| {
                        let metrics = Arc::clone(&metrics);
                        async move { handle(req, metrics).await }
                    });
                    if let Err(e) =
                        http1::Builder::new().serve_connection(io, svc).await
                    {
                        debug!(error = %e, "metrics serve_connection ended");
                    }
                });
            }
        }
    }
    info!("sidecar metrics listener stopped");
}

async fn handle(
    req: Request<Incoming>,
    metrics: Arc<Metrics>,
) -> Result<Response<Full<Bytes>>, std::convert::Infallible> {
    let path = req.uri().path();
    let resp = match path {
        "/healthz" => healthz(&metrics),
        "/readyz" => readyz(&metrics),
        "/metrics" => prom_metrics(&metrics),
        _ => Response::builder()
            .status(StatusCode::NOT_FOUND)
            .body(Full::new(Bytes::from_static(b"not found\n")))
            .unwrap_or_else(|_| Response::new(Full::new(Bytes::new()))),
    };
    Ok(resp)
}

fn healthz(m: &Metrics) -> Response<Full<Bytes>> {
    let any_healthy = !m.pool.healthy_ids().is_empty();
    let (status, body) = if any_healthy {
        (StatusCode::OK, "ok\n")
    } else {
        (StatusCode::SERVICE_UNAVAILABLE, "no healthy tunnels\n")
    };
    Response::builder()
        .status(status)
        .header("content-type", "text/plain; charset=utf-8")
        .body(Full::new(Bytes::copy_from_slice(body.as_bytes())))
        .unwrap_or_else(|_| Response::new(Full::new(Bytes::new())))
}

fn readyz(m: &Metrics) -> Response<Full<Bytes>> {
    let ready = m.ready.load(Ordering::SeqCst);
    let (status, body) = if ready {
        (StatusCode::OK, "ready\n")
    } else {
        (StatusCode::SERVICE_UNAVAILABLE, "not ready\n")
    };
    Response::builder()
        .status(status)
        .header("content-type", "text/plain; charset=utf-8")
        .body(Full::new(Bytes::copy_from_slice(body.as_bytes())))
        .unwrap_or_else(|_| Response::new(Full::new(Bytes::new())))
}

fn prom_metrics(m: &Metrics) -> Response<Full<Bytes>> {
    let snap = m.pool.stats_snapshot();
    let mut out = String::new();

    out.push_str("# HELP mailcue_tunnel_up 1 if the tunnel is healthy.\n");
    out.push_str("# TYPE mailcue_tunnel_up gauge\n");
    for s in &snap {
        let up = u8::from(s.healthy);
        out.push_str(&format!(
            "mailcue_tunnel_up{{tunnel=\"{}\"}} {up}\n",
            esc(&s.id)
        ));
    }

    out.push_str("# HELP mailcue_tunnel_requests_total Per-tunnel relay outcomes.\n");
    out.push_str("# TYPE mailcue_tunnel_requests_total counter\n");
    for s in &snap {
        out.push_str(&format!(
            "mailcue_tunnel_requests_total{{tunnel=\"{}\",outcome=\"ok\"}} {}\n",
            esc(&s.id),
            s.requests_ok
        ));
        out.push_str(&format!(
            "mailcue_tunnel_requests_total{{tunnel=\"{}\",outcome=\"err\"}} {}\n",
            esc(&s.id),
            s.requests_err
        ));
    }

    out.push_str("# HELP mailcue_tunnel_bytes_total Bytes relayed per tunnel.\n");
    out.push_str("# TYPE mailcue_tunnel_bytes_total counter\n");
    for s in &snap {
        let bytes = m.pool.bytes_total(&s.id);
        out.push_str(&format!(
            "mailcue_tunnel_bytes_total{{tunnel=\"{}\"}} {bytes}\n",
            esc(&s.id)
        ));
    }

    out.push_str(
        "# HELP mailcue_tunnel_last_success_seconds Unix timestamp of last successful op.\n",
    );
    out.push_str("# TYPE mailcue_tunnel_last_success_seconds gauge\n");
    for s in &snap {
        let v = s.last_success.unwrap_or(0);
        out.push_str(&format!(
            "mailcue_tunnel_last_success_seconds{{tunnel=\"{}\"}} {v}\n",
            esc(&s.id)
        ));
    }

    out.push_str("# HELP mailcue_tunnel_inflight Currently-in-flight relays per tunnel.\n");
    out.push_str("# TYPE mailcue_tunnel_inflight gauge\n");
    for s in &snap {
        out.push_str(&format!(
            "mailcue_tunnel_inflight{{tunnel=\"{}\"}} {}\n",
            esc(&s.id),
            s.inflight
        ));
    }

    out.push_str("# HELP mailcue_tunnel_idle_connections Idle conns currently in the pool.\n");
    out.push_str("# TYPE mailcue_tunnel_idle_connections gauge\n");
    for s in &snap {
        out.push_str(&format!(
            "mailcue_tunnel_idle_connections{{tunnel=\"{}\"}} {}\n",
            esc(&s.id),
            s.idle
        ));
    }

    out.push_str("# HELP mailcue_smtp_messages_total SMTP submissions by reply class.\n");
    out.push_str("# TYPE mailcue_smtp_messages_total counter\n");
    out.push_str(&format!(
        "mailcue_smtp_messages_total{{outcome=\"2xx\"}} {}\n",
        m.smtp_2xx.load(Ordering::Relaxed)
    ));
    out.push_str(&format!(
        "mailcue_smtp_messages_total{{outcome=\"4xx\"}} {}\n",
        m.smtp_4xx.load(Ordering::Relaxed)
    ));
    out.push_str(&format!(
        "mailcue_smtp_messages_total{{outcome=\"5xx\"}} {}\n",
        m.smtp_5xx.load(Ordering::Relaxed)
    ));

    Response::builder()
        .status(StatusCode::OK)
        .header("content-type", "text/plain; version=0.0.4; charset=utf-8")
        .body(Full::new(Bytes::from(out.into_bytes())))
        .unwrap_or_else(|_| Response::new(Full::new(Bytes::new())))
}

fn esc(s: &str) -> String {
    s.replace('\\', "\\\\").replace('"', "\\\"")
}
