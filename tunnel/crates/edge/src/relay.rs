//! Relay request handler — resolves MX, walks MX records in priority
//! order, calls into [`crate::smtp_client`], aggregates per-recipient
//! outcomes.

use std::collections::BTreeMap;
use std::time::Duration;

use bytes::Bytes;
use tracing::{debug, info, warn};

use mailcue_relay_proto::{ProbeOutcome, ProbeStatus, RecipientResult, RelayOpts, RelayStatus};

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
                    probe_only: false,
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

    // Surface non-success outcomes at info level so operators don't
    // need to flip on debug logging just to see why a recipient was
    // rejected. Successful deliveries stay quiet (the count above is
    // enough for the happy path).
    for r in &final_results {
        match &r.status {
            RelayStatus::Delivered { .. } => {}
            RelayStatus::TempFail { reason, smtp_code } => {
                info!(
                    recipient = %r.recipient,
                    smtp_code = ?smtp_code,
                    reason = %reason,
                    "delivery temp-fail",
                );
            }
            RelayStatus::PermFail { reason, smtp_code } => {
                info!(
                    recipient = %r.recipient,
                    smtp_code = ?smtp_code,
                    reason = %reason,
                    "delivery perm-fail",
                );
            }
        }
    }

    Ok(final_results)
}

/// Probe one recipient plus a random control address, stopping before DATA.
pub async fn handle_probe(
    cfg: &EdgeConfig,
    resolver: &MxResolver,
    helo_name: &str,
    envelope_from: &str,
    recipient: &str,
    control_recipients: &[String],
    opts: &RelayOpts,
) -> Result<(ProbeOutcome, Vec<ProbeOutcome>), RelayReject> {
    if !is_valid_mailbox_or_empty(envelope_from) {
        return Err(RelayReject::BadSender("invalid probe sender".to_string()));
    }
    if !is_valid_mailbox(recipient) {
        return Err(RelayReject::BadRecipients(
            "invalid probe recipient".to_string(),
        ));
    }
    let domain = recipient
        .rsplit_once('@')
        .map(|(_, value)| value.to_ascii_lowercase())
        .ok_or_else(|| RelayReject::BadRecipients("recipient missing @".to_string()))?;
    for control in control_recipients {
        if !is_valid_mailbox(control) {
            return Err(RelayReject::BadRecipients(
                "invalid probe control recipient".to_string(),
            ));
        }
        let control_domain = control
            .rsplit_once('@')
            .map(|(_, value)| value.to_ascii_lowercase())
            .ok_or_else(|| RelayReject::BadRecipients("control recipient missing @".to_string()))?;
        if domain != control_domain {
            return Err(RelayReject::BadRecipients(
                "probe recipients must share a domain".to_string(),
            ));
        }
    }

    let mxs = resolver
        .resolve_mx(&domain)
        .await
        .map_err(|e| RelayReject::BadRecipients(format!("MX lookup for {domain} failed: {e}")))?;
    let timeout_secs = if opts.timeout_secs == 0 {
        cfg.smtp_io_timeout_secs
    } else {
        u64::from(opts.timeout_secs)
    };
    let mut last_reason = "no reachable MX".to_string();

    for mx in &mxs {
        for (sender_index, probe_sender) in [envelope_from, ""].into_iter().enumerate() {
            if sender_index == 1 && envelope_from.is_empty() {
                break;
            }

            // One control is probed before the target. A destination that
            // tarpits after the first recipient in a session would otherwise
            // make every control look rejected, which reads as recipient
            // validation when it is only throttling.
            let leading = control_recipients.first();
            let mut controls: Vec<ProbeOutcome> = Vec::new();
            if let Some(control) = leading {
                match probe_single(
                    cfg,
                    mx,
                    helo_name,
                    probe_sender,
                    control,
                    timeout_secs,
                    opts,
                )
                .await
                {
                    ProbeAttemptResult::Reached(outcome) => controls.push(outcome),
                    ProbeAttemptResult::SenderRejected(reason) => {
                        last_reason = reason;
                        if sender_index == 0 {
                            continue;
                        }
                        break;
                    }
                    ProbeAttemptResult::Unreachable(reason) => {
                        last_reason = reason;
                        break;
                    }
                }
            }

            let target = match probe_single(
                cfg,
                mx,
                helo_name,
                probe_sender,
                recipient,
                timeout_secs,
                opts,
            )
            .await
            {
                ProbeAttemptResult::Reached(outcome) => outcome,
                ProbeAttemptResult::SenderRejected(reason) => {
                    last_reason = reason;
                    if sender_index == 0 {
                        continue;
                    }
                    break;
                }
                ProbeAttemptResult::Unreachable(reason) => {
                    last_reason = reason;
                    break;
                }
            };

            // A rejected target settles the question; probing the remaining
            // controls would only cost the destination extra connections.
            if target.status != ProbeStatus::Accepted {
                return Ok((target, controls));
            }

            for control in control_recipients.iter().skip(1) {
                match probe_single(
                    cfg,
                    mx,
                    helo_name,
                    probe_sender,
                    control,
                    timeout_secs,
                    opts,
                )
                .await
                {
                    ProbeAttemptResult::Reached(outcome) => controls.push(outcome),
                    ProbeAttemptResult::SenderRejected(reason)
                    | ProbeAttemptResult::Unreachable(reason) => {
                        controls.push(unknown_probe(&mx.host, &reason));
                        break;
                    }
                }
            }
            return Ok((target, controls));
        }
    }
    Ok((unknown_probe("", &last_reason), Vec::new()))
}

/// Outcome of one single-recipient probe attempt.
enum ProbeAttemptResult {
    Reached(ProbeOutcome),
    SenderRejected(String),
    Unreachable(String),
}

/// Probe one recipient in its own SMTP envelope.
///
/// Each recipient gets its own connection so per-envelope recipient limits and
/// policy cannot let one probe distort the next.
async fn probe_single(
    cfg: &EdgeConfig,
    mx: &crate::dns::MxRecord,
    helo_name: &str,
    envelope_from: &str,
    recipient: &str,
    timeout_secs: u64,
    opts: &RelayOpts,
) -> ProbeAttemptResult {
    let recipients = vec![recipient.to_string()];
    let attempt = deliver(SmtpDelivery {
        mx_host: &mx.host,
        port: 25,
        helo_name,
        envelope_from,
        recipients: &recipients,
        raw_message: &[],
        connect_timeout: Duration::from_secs(cfg.connect_timeout_secs),
        io_timeout: Duration::from_secs(timeout_secs),
        require_tls: opts.require_tls,
        probe_only: true,
    })
    .await;

    match attempt {
        Ok(SmtpAttempt::Reached(outcomes)) => {
            let outcome = outcomes
                .into_iter()
                .map(|value| probe_outcome(&mx.host, value.status, value.latency_ms))
                .next()
                .unwrap_or_else(|| unknown_probe(&mx.host, "missing probe outcome"));
            ProbeAttemptResult::Reached(outcome)
        }
        Ok(SmtpAttempt::Skipped { reason, .. }) => {
            if reason.starts_with("MAIL FROM:") {
                ProbeAttemptResult::SenderRejected(reason)
            } else {
                ProbeAttemptResult::Unreachable(reason)
            }
        }
        Err(error) => ProbeAttemptResult::Unreachable(error.to_string()),
    }
}

fn probe_outcome(mx: &str, status: RelayStatus, latency_ms: u32) -> ProbeOutcome {
    match status {
        RelayStatus::Delivered {
            smtp_code,
            smtp_msg,
            ..
        } => ProbeOutcome {
            mx: mx.to_string(),
            smtp_code: Some(smtp_code),
            smtp_msg,
            status: ProbeStatus::Accepted,
            latency_ms,
        },
        RelayStatus::TempFail { reason, smtp_code } => ProbeOutcome {
            mx: mx.to_string(),
            smtp_code,
            smtp_msg: reason,
            status: ProbeStatus::Unknown,
            latency_ms,
        },
        RelayStatus::PermFail { reason, smtp_code } => {
            let status = if definitive_recipient_rejection(&reason, mx) {
                ProbeStatus::Rejected
            } else {
                ProbeStatus::Unknown
            };
            ProbeOutcome {
                mx: mx.to_string(),
                smtp_code,
                smtp_msg: reason,
                status,
                latency_ms,
            }
        }
    }
}

fn unknown_probe(mx: &str, reason: &str) -> ProbeOutcome {
    ProbeOutcome {
        mx: mx.to_string(),
        smtp_code: None,
        smtp_msg: reason.chars().take(300).collect(),
        status: ProbeStatus::Unknown,
        latency_ms: 0,
    }
}

/// Whether the MX belongs to Microsoft, which uses codes no other receiver
/// uses for a missing recipient.
fn is_microsoft_mx(mx: &str) -> bool {
    let lower = mx.trim_end_matches('.').to_ascii_lowercase();
    lower.ends_with("mail.protection.outlook.com")
        || lower.ends_with("mail.eo.outlook.com")
        || lower.ends_with("olc.protection.outlook.com")
        || lower.ends_with("mail.protection.office365.us")
}

/// Phrases that mean the receiver refused the sending host rather than the
/// recipient. They must never be read as evidence about the mailbox.
const POLICY_MARKERS: [&str; 12] = [
    "blocked",
    "blacklist",
    "blocklist",
    "denylist",
    "spamhaus",
    "reputation",
    "access denied",
    "relay access denied",
    "relaying denied",
    "client host rejected",
    "not authorized",
    "sender verify failed",
];

/// Decide whether a permanent RCPT rejection proves the mailbox is absent.
///
/// Restricting this to the RFC 3463 `5.1.x` codes discards the codes the
/// largest business providers actually use. Microsoft signals Directory Based
/// Edge Blocking with `5.4.1` and Exchange reports `RESOLVER.ADR.RecipientNotFound`
/// as `5.1.10`; both are conclusive, but `5.4.1` is conclusive only from a
/// Microsoft edge, so the MX has to be taken into account.
fn definitive_recipient_rejection(message: &str, mx: &str) -> bool {
    let lower = message.to_ascii_lowercase();

    const UNIVERSAL_CODES: [&str; 7] = [
        "5.1.0", "5.1.1", "5.1.2", "5.1.3", "5.1.6", "5.1.10", "5.2.1",
    ];
    if UNIVERSAL_CODES.iter().any(|code| lower.contains(code)) {
        return true;
    }
    if is_microsoft_mx(mx) && lower.contains("5.4.1") {
        return true;
    }

    const STRONG_MARKERS: [&str; 16] = [
        "no such user",
        "no such recipient",
        "no such mailbox",
        "user unknown",
        "unknown user",
        "unknown recipient",
        "unknown mailbox",
        "recipient not found",
        "recipient unknown",
        "user not found",
        "mailbox not found",
        "mailbox does not exist",
        "does not exist",
        "invalid recipient",
        "recipientnotfound",
        "unrouteable address",
    ];
    if STRONG_MARKERS.iter().any(|marker| lower.contains(marker)) {
        return true;
    }
    if POLICY_MARKERS.iter().any(|marker| lower.contains(marker)) {
        return false;
    }

    // Ambiguous wording only counts when no policy refusal accompanies it.
    const WEAK_MARKERS: [&str; 3] = ["recipient rejected", "address rejected", "invalid address"];
    WEAK_MARKERS.iter().any(|marker| lower.contains(marker))
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

#[cfg(test)]
mod tests {
    use super::{definitive_recipient_rejection, is_microsoft_mx};

    const MICROSOFT_MX: &str = "acme-com.mail.protection.outlook.com";
    const GENERIC_MX: &str = "mx1.example.net";

    #[test]
    fn universal_codes_are_definitive_anywhere() {
        for message in [
            "RCPT TO: 550 5.1.1 The email account that you tried to reach does not exist",
            "RCPT TO: 550 5.1.10 RESOLVER.ADR.RecipientNotFound; Recipient not found",
            "RCPT TO: 550 5.2.1 mailbox disabled",
        ] {
            assert!(
                definitive_recipient_rejection(message, GENERIC_MX),
                "{message}"
            );
        }
    }

    #[test]
    fn directory_edge_blocking_is_definitive_only_at_microsoft() {
        // 5.4.1 is how Microsoft reports an unknown recipient, and how most
        // other receivers report an unexplained policy refusal.
        let message = "RCPT TO: 550 5.4.1 Recipient address rejected: Access denied";
        assert!(definitive_recipient_rejection(message, MICROSOFT_MX));
        assert!(!definitive_recipient_rejection(message, GENERIC_MX));
    }

    #[test]
    fn phrases_outrank_an_inaccurate_class() {
        assert!(definitive_recipient_rejection(
            "RCPT TO: 550 5.7.1 delivery refused, user unknown",
            GENERIC_MX
        ));
    }

    #[test]
    fn sender_refusals_are_never_recipient_evidence() {
        for message in [
            "RCPT TO: 550 5.7.1 Service unavailable, client host blocked using Spamhaus",
            "RCPT TO: 554 5.7.1 Your IP has a poor reputation",
            "RCPT TO: 550 5.7.1 Relay access denied",
        ] {
            assert!(
                !definitive_recipient_rejection(message, GENERIC_MX),
                "{message}"
            );
        }
    }

    #[test]
    fn ambiguous_wording_counts_only_without_a_policy_refusal() {
        assert!(definitive_recipient_rejection(
            "RCPT TO: 550 Recipient rejected",
            GENERIC_MX
        ));
        assert!(!definitive_recipient_rejection(
            "RCPT TO: 550 Recipient address rejected: Access denied",
            GENERIC_MX
        ));
    }

    #[test]
    fn microsoft_mx_detection_covers_the_published_suffixes() {
        assert!(is_microsoft_mx("acme-com.mail.protection.outlook.com."));
        assert!(is_microsoft_mx("HOTMAIL-COM.OLC.PROTECTION.OUTLOOK.COM"));
        assert!(!is_microsoft_mx("aspmx.l.google.com"));
    }
}
