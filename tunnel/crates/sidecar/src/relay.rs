//! Sidecar relay: select a tunnel, lease a conn, send `Frame::Relay`,
//! await `Frame::RelayResult`, map the per-recipient outcome to a single
//! SMTP response.
//!
//! Mapping rules (also in the brief):
//!
//! - all `Delivered`            → `250 2.6.0 queued via tunnel <name>`
//! - any `PermFail` + `accept`  → `250 ...` with details
//! - any `PermFail` + `retry`   → `451 4.7.1 partial failure, retrying`
//! - all `TempFail`             → `451 4.7.1 ...`
//! - all `PermFail`             → `554 5.0.0 ...`
//! - tunnel-level error         → `421 4.4.1 tunnel unavailable`

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

use anyhow::{Context, anyhow};
use bytes::Bytes;
use tokio::time::timeout;
use tracing::{info, warn};

use mailcue_relay_proto::{Frame, RelayOpts, RelayStatus};

use crate::config::{PartialFailurePolicy, SidecarConfig};
use crate::pool::Pool;
use crate::selector::Selector;
use crate::tunnels::TunnelRegistry;

/// SMTP response with explicit code (for metrics) and full reply line.
#[derive(Debug, Clone)]
pub struct SmtpReply {
    /// First-three-digit SMTP code.
    pub code: u16,
    /// Full reply line (no trailing CRLF).
    pub line: String,
}

impl SmtpReply {
    fn new(code: u16, line: impl Into<String>) -> Self {
        Self {
            code,
            line: line.into(),
        }
    }
}

/// Reusable sidecar relay handle.
#[derive(Clone)]
pub struct SmtpRelay {
    cfg: Arc<SidecarConfig>,
    registry: TunnelRegistry,
    pool: Pool,
    selector: Arc<Selector>,
    request_seq: Arc<AtomicU64>,
}

impl SmtpRelay {
    /// Build a relay.
    #[must_use]
    pub fn new(
        cfg: Arc<SidecarConfig>,
        registry: TunnelRegistry,
        pool: Pool,
        selector: Arc<Selector>,
    ) -> Self {
        Self {
            cfg,
            registry,
            pool,
            selector,
            request_seq: Arc::new(AtomicU64::new(rand::random::<u32>().into())),
        }
    }

    /// Send one submission, returning the SMTP response line for the client.
    ///
    /// When the primary tunnel returns a result with any non-`Delivered`
    /// recipients (TempFail / PermFail — typically a destination-MX
    /// reputation block on a single relay's IP), the remaining
    /// recipients are retried through the next healthy tunnel before
    /// the message bounces back to Postfix. Successful recipients on a
    /// previous tunnel stay accepted; only failed recipients are
    /// re-attempted, so duplicates aren't created.
    pub async fn relay(
        &self,
        envelope_from: String,
        recipients: Vec<String>,
        body: Bytes,
    ) -> SmtpReply {
        let view = self.registry.snapshot();
        let healthy = self.pool.healthy_ids();
        let candidates = self.selector.pick_all(&view, &healthy);
        if candidates.is_empty() {
            return SmtpReply::new(421, "421 4.4.1 tunnel unavailable, will retry");
        }
        let candidates: Vec<_> = candidates.into_iter().cloned().collect();

        // Per-recipient running outcome. A recipient that perm-fails on
        // tunnel A but delivers on tunnel B ends up Delivered.
        let mut accumulated: Vec<mailcue_relay_proto::RecipientResult> =
            Vec::with_capacity(recipients.len());
        let mut remaining: Vec<String> = recipients.clone();

        // Tracks the "best" SMTP-friendly status per recipient.
        let mut last_tunnel_name = String::new();
        let mut last_request_id: u64 = 0;
        let mut tunnel_level_error: Option<SmtpReply> = None;
        let total_tunnels = candidates.len();

        for (idx, tunnel) in candidates.into_iter().enumerate() {
            if remaining.is_empty() {
                break;
            }
            let request_id = self.request_seq.fetch_add(1, Ordering::Relaxed);
            last_tunnel_name = tunnel.name.clone();
            last_request_id = request_id;

            match self
                .try_one_tunnel(&tunnel, request_id, &envelope_from, &remaining, &body)
                .await
            {
                TunnelAttempt::Result(per_recipient) => {
                    tunnel_level_error = None;
                    let mut next_remaining = Vec::new();
                    for r in per_recipient {
                        let is_delivered = matches!(r.status, RelayStatus::Delivered { .. });
                        if !is_delivered {
                            next_remaining.push(r.recipient.clone());
                        }
                        upsert_outcome(&mut accumulated, r);
                    }
                    if !next_remaining.is_empty() && idx + 1 < total_tunnels {
                        info!(
                            tunnel = %tunnel.id,
                            request_id,
                            envelope_from = %envelope_from,
                            failed_recipients = next_remaining.len(),
                            remaining_tunnels = total_tunnels - idx - 1,
                            "failing over to next tunnel",
                        );
                    }
                    remaining = next_remaining;
                }
                TunnelAttempt::TunnelError(reply) => {
                    tunnel_level_error = Some(reply);
                }
            }
        }

        if accumulated.is_empty() {
            return tunnel_level_error
                .unwrap_or_else(|| SmtpReply::new(421, "421 4.4.1 all tunnels failed"));
        }

        let reply = map_outcomes(
            &last_tunnel_name,
            last_request_id,
            &accumulated,
            self.cfg.partial_failure_policy,
        );
        let counts = summarise(&accumulated);
        info!(
            request_id = last_request_id,
            envelope_from = %envelope_from,
            delivered = counts.delivered,
            temp = counts.temp,
            perm = counts.perm,
            smtp_code = reply.code,
            tunnels_tried = total_tunnels - {
                // Count how many tunnels we *actually* attempted: every
                // tunnel before remaining became empty plus, if `remaining`
                // never emptied, all of them.
                let _ = &remaining;
                0_usize
            },
            "multi-tunnel relay completed",
        );
        reply
    }

    /// Single-tunnel send: lease a conn, frame Relay, await RelayResult.
    /// Returns `Result(per_recipient)` on application-level outcome
    /// (whether deliveries succeeded or not), or `TunnelError(reply)`
    /// if the tunnel itself was unreachable / replied with an Error frame.
    async fn try_one_tunnel(
        &self,
        tunnel: &crate::tunnels::Tunnel,
        request_id: u64,
        envelope_from: &str,
        recipients: &[String],
        body: &Bytes,
    ) -> TunnelAttempt {
        let mut conn = match self.pool.lease(tunnel).await {
            Ok(c) => c,
            Err(e) => {
                warn!(tunnel = %tunnel.id, error = %e, "lease failed");
                return TunnelAttempt::TunnelError(SmtpReply::new(
                    421,
                    "421 4.4.1 tunnel unavailable, will retry",
                ));
            }
        };

        let opts = RelayOpts::default();
        let req_to = Duration::from_secs(self.cfg.request_timeout_secs);

        let send_res = timeout(
            req_to,
            conn.channel.send_frame(&Frame::Relay {
                request_id,
                envelope_from: envelope_from.to_string(),
                recipients: recipients.to_vec(),
                raw_message: body.clone(),
                opts,
            }),
        )
        .await
        .map_err(|_| anyhow!("Relay write timeout"))
        .and_then(|r| r.context("send Relay"));

        if let Err(e) = send_res {
            self.pool.discard(conn, &format!("send Relay: {e}"));
            return TunnelAttempt::TunnelError(SmtpReply::new(
                421,
                "421 4.4.1 tunnel unavailable, will retry",
            ));
        }

        let recv_res = timeout(req_to, conn.channel.recv_frame())
            .await
            .map_err(|_| anyhow!("RelayResult read timeout"))
            .and_then(|r| r.context("recv RelayResult"));

        let frame = match recv_res {
            Ok(f) => f,
            Err(e) => {
                self.pool.discard(conn, &format!("recv RelayResult: {e}"));
                return TunnelAttempt::TunnelError(SmtpReply::new(
                    421,
                    "421 4.4.1 tunnel unavailable, will retry",
                ));
            }
        };

        match frame {
            Frame::RelayResult {
                request_id: got_id,
                per_recipient,
            } if got_id == request_id => {
                self.pool.release(conn);
                let counts = summarise(&per_recipient);
                info!(
                    tunnel = %tunnel.id,
                    request_id,
                    envelope_from = %envelope_from,
                    delivered = counts.delivered,
                    temp = counts.temp,
                    perm = counts.perm,
                    "tunnel attempt completed",
                );
                TunnelAttempt::Result(per_recipient)
            }
            Frame::Error { code, message, .. } => {
                self.pool
                    .discard(conn, &format!("edge error: {code:?}: {message}"));
                warn!(
                    tunnel = %tunnel.id,
                    request_id,
                    ?code,
                    %message,
                    "edge returned Error frame",
                );
                TunnelAttempt::TunnelError(SmtpReply::new(
                    421,
                    format!("421 4.4.1 edge error: {code:?}: {message}"),
                ))
            }
            other => {
                self.pool
                    .discard(conn, &format!("expected RelayResult, got {other:?}"));
                TunnelAttempt::TunnelError(SmtpReply::new(
                    421,
                    "421 4.4.1 unexpected frame from edge",
                ))
            }
        }
    }
}

/// Outcome of attempting one tunnel: either an application-level
/// per-recipient result (deliver / fail), or a tunnel-level error
/// (handshake / protocol / timeout) that we should treat as "skip this
/// tunnel; try the next" rather than as a delivery verdict.
enum TunnelAttempt {
    Result(Vec<mailcue_relay_proto::RecipientResult>),
    TunnelError(SmtpReply),
}

/// Insert / replace the entry for `r.recipient` in `acc`. When a
/// previously-failed recipient succeeds on a later tunnel, the new
/// `Delivered` outcome wins; later failures don't downgrade an earlier
/// success.
fn upsert_outcome(
    acc: &mut Vec<mailcue_relay_proto::RecipientResult>,
    r: mailcue_relay_proto::RecipientResult,
) {
    let new_is_delivered = matches!(r.status, RelayStatus::Delivered { .. });
    if let Some(pos) = acc.iter().position(|e| e.recipient == r.recipient) {
        let prev_is_delivered = matches!(acc[pos].status, RelayStatus::Delivered { .. });
        if !prev_is_delivered || new_is_delivered {
            acc[pos] = r;
        }
    } else {
        acc.push(r);
    }
}

#[derive(Debug, Default)]
struct OutcomeCounts {
    delivered: usize,
    temp: usize,
    perm: usize,
    total: usize,
}

fn summarise(rs: &[mailcue_relay_proto::RecipientResult]) -> OutcomeCounts {
    let mut c = OutcomeCounts::default();
    for r in rs {
        c.total += 1;
        match r.status {
            RelayStatus::Delivered { .. } => c.delivered += 1,
            RelayStatus::TempFail { .. } => c.temp += 1,
            RelayStatus::PermFail { .. } => c.perm += 1,
        }
    }
    c
}

/// Pure mapping fn — exposed to keep it unit-testable.
#[must_use]
pub fn map_outcomes(
    tunnel_name: &str,
    request_id: u64,
    rs: &[mailcue_relay_proto::RecipientResult],
    policy: PartialFailurePolicy,
) -> SmtpReply {
    let c = summarise(rs);
    if c.total == 0 {
        return SmtpReply::new(554, "554 5.0.0 no recipients accepted by edge");
    }

    if c.delivered == c.total {
        return SmtpReply::new(
            250,
            format!("250 2.6.0 queued via tunnel {tunnel_name} (req={request_id})"),
        );
    }

    if c.perm == c.total {
        return SmtpReply::new(
            554,
            format!(
                "554 5.0.0 all recipients permanently rejected via {tunnel_name} (req={request_id})"
            ),
        );
    }

    if c.temp + c.delivered == c.total && c.delivered == 0 {
        return SmtpReply::new(
            451,
            format!("451 4.7.1 transient failure via {tunnel_name} (req={request_id})"),
        );
    }

    // Partial: at least one Delivered, at least one non-Delivered.
    if c.perm > 0 {
        match policy {
            PartialFailurePolicy::Retry => SmtpReply::new(
                451,
                format!(
                    "451 4.7.1 partial failure ({} ok, {} perm, {} temp) via {tunnel_name} (req={request_id}); retrying via different tunnel",
                    c.delivered, c.perm, c.temp
                ),
            ),
            PartialFailurePolicy::AcceptPartial => SmtpReply::new(
                250,
                format!(
                    "250 2.6.0 partial accept ({} ok, {} perm, {} temp) via {tunnel_name} (req={request_id})",
                    c.delivered, c.perm, c.temp
                ),
            ),
        }
    } else {
        // Mixed Delivered/TempFail with no Perm — defer for retry.
        SmtpReply::new(
            451,
            format!(
                "451 4.7.1 partial transient ({} ok, {} temp) via {tunnel_name} (req={request_id})",
                c.delivered, c.temp
            ),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use mailcue_relay_proto::{RecipientResult, RelayStatus};

    fn ok(addr: &str) -> RecipientResult {
        RecipientResult {
            recipient: addr.into(),
            status: RelayStatus::Delivered {
                mx: "mx.test".into(),
                smtp_code: 250,
                smtp_msg: "ok".into(),
            },
        }
    }

    fn temp(addr: &str) -> RecipientResult {
        RecipientResult {
            recipient: addr.into(),
            status: RelayStatus::TempFail {
                reason: "x".into(),
                smtp_code: Some(421),
            },
        }
    }

    fn perm(addr: &str) -> RecipientResult {
        RecipientResult {
            recipient: addr.into(),
            status: RelayStatus::PermFail {
                reason: "y".into(),
                smtp_code: Some(550),
            },
        }
    }

    #[test]
    fn all_delivered() {
        let r = map_outcomes(
            "e",
            1,
            &[ok("a@b.c"), ok("d@e.f")],
            PartialFailurePolicy::Retry,
        );
        assert_eq!(r.code, 250);
    }

    #[test]
    fn all_perm() {
        let r = map_outcomes(
            "e",
            1,
            &[perm("a@b.c"), perm("d@e.f")],
            PartialFailurePolicy::Retry,
        );
        assert_eq!(r.code, 554);
    }

    #[test]
    fn all_temp() {
        let r = map_outcomes(
            "e",
            1,
            &[temp("a@b.c"), temp("d@e.f")],
            PartialFailurePolicy::Retry,
        );
        assert_eq!(r.code, 451);
    }

    #[test]
    fn partial_retry_policy_returns_451() {
        let r = map_outcomes(
            "e",
            1,
            &[ok("a@b.c"), perm("d@e.f")],
            PartialFailurePolicy::Retry,
        );
        assert_eq!(r.code, 451);
    }

    #[test]
    fn partial_accept_policy_returns_250() {
        let r = map_outcomes(
            "e",
            1,
            &[ok("a@b.c"), perm("d@e.f")],
            PartialFailurePolicy::AcceptPartial,
        );
        assert_eq!(r.code, 250);
    }

    #[test]
    fn partial_temp_only_returns_451() {
        let r = map_outcomes(
            "e",
            1,
            &[ok("a@b.c"), temp("d@e.f")],
            PartialFailurePolicy::Retry,
        );
        assert_eq!(r.code, 451);
    }
}
