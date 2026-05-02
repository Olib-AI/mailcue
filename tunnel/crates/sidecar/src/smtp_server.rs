//! Loopback SMTP submission server.
//!
//! Listens on `cfg.smtp_listen` (default `127.0.0.1:2525`). Accepts only
//! loopback peers; non-loopback peers get `554` and disconnect.
//!
//! State machine: EHLO/HELO → MAIL FROM → RCPT TO* → DATA → final reply.
//! The body is dot-unstuffed per RFC 5321 §4.5.2 and bounded by
//! `cfg.max_message_size_bytes`.
//!
//! After successful DATA, the message is handed off to the relay layer
//! which selects a tunnel and returns a single SMTP reply line.

use std::net::IpAddr;
use std::sync::Arc;

use bytes::Bytes;
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::net::{TcpListener, TcpStream};
use tracing::{debug, info, warn};

use crate::config::SidecarConfig;
use crate::metrics::Metrics;
use crate::relay::SmtpRelay;

/// Run the SMTP listener forever (until `cancel` fires).
pub async fn run(
    listener: TcpListener,
    cfg: Arc<SidecarConfig>,
    relay: SmtpRelay,
    metrics: Arc<Metrics>,
    mut cancel: tokio::sync::watch::Receiver<bool>,
) {
    info!(listen = %cfg.smtp_listen, "sidecar SMTP listener up");

    let mut tasks: tokio::task::JoinSet<()> = tokio::task::JoinSet::new();

    loop {
        tokio::select! {
            biased;
            res = cancel.changed() => {
                if res.is_err() || *cancel.borrow() {
                    break;
                }
            }
            accept_res = listener.accept() => {
                let (stream, peer) = match accept_res {
                    Ok(p) => p,
                    Err(e) => {
                        warn!(error = %e, "smtp accept failed");
                        continue;
                    }
                };
                let _ = stream.set_nodelay(true);
                let cfg = Arc::clone(&cfg);
                let relay = relay.clone();
                let metrics = Arc::clone(&metrics);
                tasks.spawn(async move {
                    if let Err(e) = handle_session(stream, peer.ip(), cfg, relay, metrics).await {
                        debug!(peer = %peer, error = %format!("{e:#}"), "smtp session ended");
                    }
                });
            }
        }
    }

    info!("sidecar SMTP listener stopped; draining sessions");
    while tasks.join_next().await.is_some() {}
}

async fn handle_session(
    stream: TcpStream,
    peer_ip: IpAddr,
    cfg: Arc<SidecarConfig>,
    relay: SmtpRelay,
    metrics: Arc<Metrics>,
) -> std::io::Result<()> {
    let (read_half, mut write_half) = stream.into_split();
    let mut reader = BufReader::new(read_half);

    let helo_self = gethostname::gethostname().to_string_lossy().into_owned();

    if !is_loopback(peer_ip) {
        let _ = write_line(&mut write_half, "554 5.7.1 only loopback peers allowed").await;
        return Ok(());
    }

    write_line(
        &mut write_half,
        &format!("220 {helo_self} mailcue-sidecar ready"),
    )
    .await?;

    let mut state = SessionState::default();

    loop {
        let mut line = String::new();
        let n = reader.read_line(&mut line).await?;
        if n == 0 {
            return Ok(());
        }

        let trimmed = line.trim_end_matches(['\r', '\n']).to_string();
        let upper = trimmed.to_ascii_uppercase();
        let cmd = first_word(&upper);

        match cmd.as_str() {
            "EHLO" => {
                state = SessionState::default();
                let domain = trimmed.get(5..).unwrap_or("").trim();
                state.helo = Some(domain.to_string());
                write_line(&mut write_half, &format!("250-{helo_self} hello {domain}")).await?;
                write_line(
                    &mut write_half,
                    &format!("250-SIZE {}", cfg.max_message_size_bytes),
                )
                .await?;
                write_line(&mut write_half, "250-8BITMIME").await?;
                write_line(&mut write_half, "250-PIPELINING").await?;
                write_line(&mut write_half, "250 ENHANCEDSTATUSCODES").await?;
            }
            "HELO" => {
                state = SessionState::default();
                let domain = trimmed.get(5..).unwrap_or("").trim();
                state.helo = Some(domain.to_string());
                write_line(&mut write_half, &format!("250 {helo_self} hello {domain}")).await?;
            }
            "MAIL" => {
                if state.helo.is_none() {
                    write_line(&mut write_half, "503 5.5.1 send EHLO/HELO first").await?;
                    continue;
                }
                let Some(rest) = trimmed.get(4..) else {
                    write_line(&mut write_half, "501 5.5.4 syntax: MAIL FROM:<addr>").await?;
                    continue;
                };
                match parse_mail_from(rest) {
                    Ok((addr, _size)) => {
                        state.envelope_from = Some(addr);
                        state.recipients.clear();
                        state.body = None;
                        write_line(&mut write_half, "250 2.1.0 sender ok").await?;
                    }
                    Err(reason) => {
                        write_line(&mut write_half, &format!("501 5.5.4 syntax: {reason}")).await?;
                    }
                }
            }
            "RCPT" => {
                if state.envelope_from.is_none() {
                    write_line(&mut write_half, "503 5.5.1 need MAIL FROM first").await?;
                    continue;
                }
                if state.recipients.len() >= cfg.max_recipients_per_request {
                    write_line(&mut write_half, "452 4.5.3 too many recipients").await?;
                    continue;
                }
                let Some(rest) = trimmed.get(4..) else {
                    write_line(&mut write_half, "501 5.5.4 syntax: RCPT TO:<addr>").await?;
                    continue;
                };
                match parse_rcpt_to(rest) {
                    Ok(addr) => {
                        state.recipients.push(addr);
                        write_line(&mut write_half, "250 2.1.5 recipient ok").await?;
                    }
                    Err(reason) => {
                        write_line(&mut write_half, &format!("501 5.5.4 syntax: {reason}")).await?;
                    }
                }
            }
            "DATA" => {
                if state.envelope_from.is_none() || state.recipients.is_empty() {
                    write_line(&mut write_half, "503 5.5.1 need MAIL/RCPT first").await?;
                    continue;
                }
                write_line(&mut write_half, "354 end data with <CR><LF>.<CR><LF>").await?;

                let body = match read_data(&mut reader, cfg.max_message_size_bytes).await {
                    Ok(b) => b,
                    Err(ReadDataError::TooLarge) => {
                        write_line(&mut write_half, "552 5.3.4 message too large").await?;
                        // Drain the dot-line; cheap reset.
                        state.envelope_from = None;
                        state.recipients.clear();
                        continue;
                    }
                    Err(ReadDataError::Io(e)) => return Err(e),
                };

                let envelope_from = state.envelope_from.take().unwrap_or_default();
                let recipients = std::mem::take(&mut state.recipients);
                let recipient_count = recipients.len();
                let body_len = body.len();

                let reply = relay.relay(envelope_from.clone(), recipients, body).await;

                metrics.smtp_record(&reply);
                info!(
                    smtp_code = reply.code,
                    envelope_from = %envelope_from,
                    recipient_count,
                    body_len,
                    "submission completed",
                );
                write_line(&mut write_half, &reply.line).await?;
                state = SessionState {
                    helo: state.helo.clone(),
                    ..Default::default()
                };
            }
            "RSET" => {
                state = SessionState {
                    helo: state.helo.clone(),
                    ..Default::default()
                };
                write_line(&mut write_half, "250 2.0.0 ok").await?;
            }
            "NOOP" => {
                write_line(&mut write_half, "250 2.0.0 ok").await?;
            }
            "VRFY" => {
                write_line(&mut write_half, "502 5.5.1 VRFY not implemented").await?;
            }
            "QUIT" => {
                let _ = write_line(&mut write_half, "221 2.0.0 bye").await;
                return Ok(());
            }
            _ => {
                write_line(&mut write_half, "500 5.5.1 unknown command").await?;
            }
        }
    }
}

#[derive(Debug, Default)]
struct SessionState {
    helo: Option<String>,
    envelope_from: Option<String>,
    recipients: Vec<String>,
    body: Option<Bytes>,
}

#[derive(Debug)]
enum ReadDataError {
    TooLarge,
    Io(std::io::Error),
}

impl From<std::io::Error> for ReadDataError {
    fn from(e: std::io::Error) -> Self {
        Self::Io(e)
    }
}

/// Read DATA body until `\r\n.\r\n`, dot-unstuffing, capped at `max`.
async fn read_data<R: AsyncReadExt + AsyncBufReadExt + Unpin>(
    reader: &mut R,
    max: usize,
) -> Result<Bytes, ReadDataError> {
    let mut buf: Vec<u8> = Vec::with_capacity(8192);
    let mut line = String::new();
    loop {
        line.clear();
        let n = reader.read_line(&mut line).await?;
        if n == 0 {
            return Err(ReadDataError::Io(std::io::Error::new(
                std::io::ErrorKind::UnexpectedEof,
                "client closed during DATA",
            )));
        }
        // Normalise \n → \r\n if needed (ensures CRLF on the wire).
        let raw = line.as_bytes();
        let trimmed = if raw.ends_with(b"\r\n") {
            &raw[..raw.len() - 2]
        } else if raw.ends_with(b"\n") {
            &raw[..raw.len() - 1]
        } else {
            raw
        };

        if trimmed == b"." {
            return Ok(Bytes::from(buf));
        }

        // Dot-unstuff: a leading '.' on a stuffed line is removed.
        let payload = if trimmed.first() == Some(&b'.') {
            &trimmed[1..]
        } else {
            trimmed
        };

        if buf.len() + payload.len() + 2 > max {
            return Err(ReadDataError::TooLarge);
        }
        buf.extend_from_slice(payload);
        buf.extend_from_slice(b"\r\n");
    }
}

fn first_word(s: &str) -> String {
    s.split_whitespace().next().unwrap_or("").to_string()
}

fn parse_mail_from(rest: &str) -> Result<(String, Option<usize>), String> {
    // Accepts forms like: " FROM:<addr> [SIZE=n]"
    let upper = rest.to_ascii_uppercase();
    let from_idx = upper
        .find("FROM:")
        .ok_or_else(|| "missing FROM:".to_string())?;
    let after = &rest[from_idx + 5..].trim_start();
    let (angled, tail) = extract_angled(after).ok_or_else(|| "expected <addr>".to_string())?;
    let addr = angled.trim().to_string();
    if !addr.is_empty() && !is_valid_mailbox(&addr) {
        return Err(format!("invalid mailbox `{addr}`"));
    }
    let mut size: Option<usize> = None;
    for tok in tail.split_whitespace() {
        let upper = tok.to_ascii_uppercase();
        if let Some(rest) = upper.strip_prefix("SIZE=") {
            size = rest.parse().ok();
        }
    }
    Ok((addr, size))
}

fn parse_rcpt_to(rest: &str) -> Result<String, String> {
    let upper = rest.to_ascii_uppercase();
    let to_idx = upper.find("TO:").ok_or_else(|| "missing TO:".to_string())?;
    let after = &rest[to_idx + 3..].trim_start();
    let (angled, _tail) = extract_angled(after).ok_or_else(|| "expected <addr>".to_string())?;
    let addr = angled.trim().to_string();
    if !is_valid_mailbox(&addr) {
        return Err(format!("invalid mailbox `{addr}`"));
    }
    Ok(addr)
}

fn extract_angled(s: &str) -> Option<(String, &str)> {
    let s = s.trim_start();
    let bytes = s.as_bytes();
    if bytes.first() == Some(&b'<') {
        let close = s.find('>')?;
        Some((s[1..close].to_string(), &s[close + 1..]))
    } else {
        None
    }
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

fn is_loopback(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(v4) => v4.is_loopback(),
        IpAddr::V6(v6) => v6.is_loopback(),
    }
}

async fn write_line<W: AsyncWriteExt + Unpin>(w: &mut W, line: &str) -> std::io::Result<()> {
    w.write_all(line.as_bytes()).await?;
    w.write_all(b"\r\n").await?;
    w.flush().await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_mail_from_with_size() {
        let (addr, size) = parse_mail_from(" FROM:<a@b.example> SIZE=12345").unwrap();
        assert_eq!(addr, "a@b.example");
        assert_eq!(size, Some(12345));
    }

    #[test]
    fn parses_empty_mail_from() {
        let (addr, _) = parse_mail_from(" FROM:<>").unwrap();
        assert!(addr.is_empty());
    }

    #[test]
    fn rejects_unangled_rcpt() {
        assert!(parse_rcpt_to(" TO: a@b.example").is_err());
    }

    #[test]
    fn rcpt_accepts_addr() {
        let a = parse_rcpt_to(" TO:<a@b.example>").unwrap();
        assert_eq!(a, "a@b.example");
    }

    #[tokio::test]
    async fn dot_unstuff_basic() {
        let payload = "Subject: t\r\n\r\n..hello\r\n.\r\n";
        let mut cursor = std::io::Cursor::new(payload.as_bytes());
        let mut buf = tokio::io::BufReader::new(&mut cursor);
        let body = read_data(&mut buf, 1024).await.unwrap();
        // Leading dot stuffed → unstuffed to single dot.
        assert!(body.windows(7).any(|w| w == b".hello\r"));
    }

    #[tokio::test]
    async fn data_too_large() {
        let mut payload = String::from("Subject: t\r\n\r\n");
        for _ in 0..200 {
            payload.push_str("AAAAAAAAAAAAAAAA\r\n");
        }
        payload.push_str(".\r\n");
        let mut cursor = std::io::Cursor::new(payload.as_bytes());
        let mut buf = tokio::io::BufReader::new(&mut cursor);
        let r = read_data(&mut buf, 256).await;
        assert!(matches!(r, Err(ReadDataError::TooLarge)));
    }

    #[test]
    fn validates_loopback_only() {
        assert!(is_loopback(IpAddr::V4("127.0.0.1".parse().unwrap())));
        assert!(is_loopback(IpAddr::V6("::1".parse().unwrap())));
        assert!(!is_loopback(IpAddr::V4("8.8.8.8".parse().unwrap())));
    }
}
