//! Relay request handler — resolves MX, walks MX records in priority
//! order, calls into [`crate::smtp_client`], aggregates per-recipient
//! outcomes.

use std::collections::BTreeMap;
use std::time::Duration;

use bytes::Bytes;
use tracing::{debug, info, warn};

use mailcue_relay_proto::{RecipientResult, RelayOpts, RelayStatus};

use crate::config::EdgeConfig;
use crate::dns::MxResolver;
use crate::smtp_client::{SmtpAttempt, SmtpDelivery, deliver};

/// Edge-side validation / processing errors that cause us to send
/// `Frame::Error` instead of `Frame::RelayResult`.
#[derive(Debug)]
pub enum RelayReject {
    /// Envelope sender failed validation.
    BadSender(String),
    /// Recipient list empty or malformed.
    BadRecipients(String),
    /// Message body exceeded `max_message_size_bytes`.
    MessageTooLarge,
    /// Recipient list exceeded `max_recipients_per_request`.
    TooManyRecipients,
}

/// Run a relay request to completion. The returned vector preserves the
/// caller's recipient ordering.
pub async fn handle_relay(
    cfg: &EdgeConfig,
    resolver: &MxResolver,
    helo_name: &str,
    envelope_from: &str,
    recipients: &[String],
    raw_message: &Bytes,
    opts: &RelayOpts,
) -> Result<Vec<RecipientResult>, RelayReject> {
    if !is_valid_mailbox_or_empty(envelope_from) {
        return Err(RelayReject::BadSender(format!(
            "envelope_from `{envelope_from}` is not a valid mailbox"
        )));
    }
    if recipients.is_empty() {
        return Err(RelayReject::BadRecipients("no recipients".to_string()));
    }
    if recipients.len() > cfg.max_recipients_per_request {
        return Err(RelayReject::TooManyRecipients);
    }
    if raw_message.len() > cfg.max_message_size_bytes {
        return Err(RelayReject::MessageTooLarge);
    }
    for r in recipients {
        if !is_valid_mailbox(r) {
            return Err(RelayReject::BadRecipients(format!(
                "invalid recipient `{r}`"
            )));
        }
    }

    // Group recipients by domain, preserving the original index so we can
    // place outcomes back in caller order.
    let mut by_domain: BTreeMap<String, Vec<(usize, String)>> = BTreeMap::new();
    for (idx, rcpt) in recipients.iter().enumerate() {
        let Some(domain) = rcpt.rsplit_once('@').map(|(_, d)| d.to_ascii_lowercase()) else {
            return Err(RelayReject::BadRecipients(format!("missing @ in `{rcpt}`")));
        };
        by_domain
            .entry(domain)
            .or_default()
            .push((idx, rcpt.clone()));
    }

    let mut results: Vec<Option<RelayStatus>> = vec![None; recipients.len()];

    for (domain, group) in by_domain {
        let group_rcpts: Vec<String> = group.iter().map(|(_, r)| r.clone()).collect();
        let group_indices: Vec<usize> = group.iter().map(|(i, _)| *i).collect();

        let mxs = match resolver.resolve_mx(&domain).await {
            Ok(m) => m,
            Err(e) => {
                warn!(domain = %domain, error = %e, "MX lookup failed");
                for idx in &group_indices {
                    results[*idx] = Some(RelayStatus::TempFail {
                        reason: format!("MX lookup for {domain}: {e}"),
                        smtp_code: None,
                    });
                }
                continue;
            }
        };

        let timeout_secs = if opts.timeout_secs == 0 {
            cfg.smtp_io_timeout_secs
        } else {
            u64::from(opts.timeout_secs)
        };

        let mut domain_outcomes: Option<Vec<RelayStatus>> = None;
        let mut last_skip: Option<String> = None;

        'mx: for mx in &mxs {
            for &port in &cfg.allowed_smtp_ports {
                if port != 25 {
                    // For MX delivery we always use port 25 — 465/587 are
                    // allowed in config only so future operators can carve
                    // out submission relays. Skip non-25 quietly.
                    continue;
                }
                let attempt = match deliver(SmtpDelivery {
                    mx_host: &mx.host,
                    port,
                    helo_name,
                    envelope_from,
                    recipients: &group_rcpts,
                    raw_message,
                    connect_timeout: Duration::from_secs(cfg.connect_timeout_secs),
                    io_timeout: Duration::from_secs(timeout_secs),
                    require_tls: opts.require_tls,
                })
                .await
                {
                    Ok(a) => a,
                    Err(e) => {
                        warn!(mx = %mx.host, error = %e, "smtp client error");
                        last_skip = Some(format!("{}: {e}", mx.host));
                        continue;
                    }
                };

                match attempt {
                    SmtpAttempt::Reached(outcomes) => {
                        debug!(domain = %domain, mx = %mx.host, "delivered");
                        let mut out = Vec::with_capacity(outcomes.len());
                        // Re-align outcomes to group order: SmtpDelivery
                        // preserved input order so 1:1.
                        for o in outcomes {
                            out.push(o.status);
                        }
                        domain_outcomes = Some(out);
                        break 'mx;
                    }
                    SmtpAttempt::Skipped {
                        reason,
                        transient: _,
                    } => {
                        debug!(mx = %mx.host, %reason, "mx skipped");
                        last_skip = Some(format!("{}: {reason}", mx.host));
                        continue;
                    }
                }
            }
        }

        if let Some(outcomes) = domain_outcomes {
            for (idx, status) in group_indices.iter().zip(outcomes) {
                results[*idx] = Some(status);
            }
        } else {
            let reason = last_skip.unwrap_or_else(|| format!("no usable MX for {domain}"));
            for idx in &group_indices {
                results[*idx] = Some(RelayStatus::TempFail {
                    reason: reason.clone(),
                    smtp_code: None,
                });
            }
        }
    }

    let final_results: Vec<RecipientResult> = recipients
        .iter()
        .enumerate()
        .map(|(idx, rcpt)| RecipientResult {
            recipient: rcpt.clone(),
            status: results[idx].clone().unwrap_or(RelayStatus::TempFail {
                reason: "internal: missing outcome".to_string(),
                smtp_code: None,
            }),
        })
        .collect();

    let counts = summarise(&final_results);
    info!(
        delivered = counts.delivered,
        temp = counts.temp,
        perm = counts.perm,
        "relay complete"
    );

    Ok(final_results)
}

#[derive(Debug, Default)]
pub struct OutcomeCounts {
    pub delivered: usize,
    pub temp: usize,
    pub perm: usize,
}

pub fn summarise(rs: &[RecipientResult]) -> OutcomeCounts {
    let mut c = OutcomeCounts::default();
    for r in rs {
        match r.status {
            RelayStatus::Delivered { .. } => c.delivered += 1,
            RelayStatus::TempFail { .. } => c.temp += 1,
            RelayStatus::PermFail { .. } => c.perm += 1,
        }
    }
    c
}

fn is_valid_mailbox(s: &str) -> bool {
    if s.is_empty() || s.len() > 254 {
        return false;
    }
    let Some((local, domain)) = s.rsplit_once('@') else {
        return false;
    };
    if local.is_empty() || local.len() > 64 || domain.is_empty() || !domain.contains('.') {
        return false;
    }
    !s.bytes()
        .any(|b| b.is_ascii_control() || b == b' ' || b == b'<' || b == b'>')
}

fn is_valid_mailbox_or_empty(s: &str) -> bool {
    s.is_empty() || is_valid_mailbox(s)
}
