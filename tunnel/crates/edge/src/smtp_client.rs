//! Minimal SMTP client used by the edge to deliver to upstream MX.
//!
//! Implementation note: we wrote this by hand rather than using
//! `mail-send` / `lettre` because we need the **per-RCPT TO reply code**
//! to map onto [`mailcue_relay_proto::RelayStatus`]. Both crates abstract
//! that away (they treat the whole envelope as a single send).
//!
//! Connection lifecycle:
//!
//! 1. TCP connect (with timeout).
//! 2. Read server banner (220).
//! 3. EHLO; if rejected, fall back to HELO.
//! 4. If `STARTTLS` is advertised, attempt TLS upgrade. On failure with
//!    `require_tls = false`, fall back to plaintext (standard MX policy).
//! 5. MAIL FROM:<…>.
//! 6. RCPT TO:<…> for each recipient — record each reply.
//! 7. DATA + dot-stuffed message + `\r\n.\r\n`.
//! 8. QUIT (best effort).

use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result, anyhow, bail};
use rustls::{ClientConfig, RootCertStore};
use rustls_pki_types::ServerName;
use tokio::io::{AsyncBufReadExt, AsyncRead, AsyncWriteExt, BufStream};
use tokio::net::TcpStream;
use tokio::time::timeout;
use tokio_rustls::TlsConnector;
use tokio_rustls::client::TlsStream;
use tracing::{debug, warn};

use mailcue_relay_proto::RelayStatus;

/// Per-recipient SMTP outcome plus the MX hostname used.
#[derive(Debug)]
#[allow(dead_code)] // `recipient` is preserved for future logging / debug tracing.
pub struct RecipientOutcome {
    /// The recipient address as supplied by the caller.
    pub recipient: String,
    /// Mapped relay status for [`mailcue_relay_proto::RecipientResult`].
    pub status: RelayStatus,
}

/// Per-call configuration for [`deliver`].
#[derive(Debug, Clone)]
pub struct SmtpDelivery<'a> {
    /// Hostname / IP of the upstream MX.
    pub mx_host: &'a str,
    /// TCP port (typically 25).
    pub port: u16,
    /// HELO / EHLO name to present.
    pub helo_name: &'a str,
    /// Envelope `MAIL FROM`.
    pub envelope_from: &'a str,
    /// Recipients (one or more).
    pub recipients: &'a [String],
    /// Pre-dot-stuffed RFC 5322 message.
    pub raw_message: &'a [u8],
    /// Connect timeout.
    pub connect_timeout: Duration,
    /// Per-IO timeout (each line / DATA chunk).
    pub io_timeout: Duration,
    /// If `true`, fail closed when STARTTLS is not offered or fails.
    pub require_tls: bool,
}

/// Outcome of an attempted SMTP delivery against one MX.
#[derive(Debug)]
#[allow(dead_code)] // `transient` is informational; consumed via Debug only.
pub enum SmtpAttempt {
    /// Session reached MAIL FROM. `outcomes` contains one entry per
    /// recipient — some may be Delivered, some PermFail, some TempFail
    /// depending on per-RCPT and DATA replies.
    Reached(Vec<RecipientOutcome>),
    /// Session never reached the recipient stage (banner / EHLO /
    /// STARTTLS failure). The caller should try the next MX.
    Skipped {
        /// Free-form reason (network error, 4xx, etc).
        reason: String,
        /// `true` if the failure looks transient (network / 4xx).
        transient: bool,
    },
}

/// Try to deliver `delivery.raw_message` to `delivery.mx_host`.
///
/// # Errors
///
/// Returns an error only for unrecoverable internal failures (e.g.
/// invalid TLS configuration). All SMTP-level failures are reported via
/// [`SmtpAttempt`] / [`RelayStatus`].
pub async fn deliver(delivery: SmtpDelivery<'_>) -> Result<SmtpAttempt> {
    let connect_target = format!("{}:{}", delivery.mx_host, delivery.port);

    let tcp = match timeout(
        delivery.connect_timeout,
        TcpStream::connect(&connect_target),
    )
    .await
    {
        Ok(Ok(s)) => s,
        Ok(Err(e)) => {
            return Ok(SmtpAttempt::Skipped {
                reason: format!("connect {connect_target}: {e}"),
                transient: true,
            });
        }
        Err(_) => {
            return Ok(SmtpAttempt::Skipped {
                reason: format!("connect timeout {connect_target}"),
                transient: true,
            });
        }
    };
    tcp.set_nodelay(true).ok();

    let mut session = Session::Plain(BufStream::new(tcp));

    // Banner.
    let banner = match read_reply(&mut session, delivery.io_timeout).await {
        Ok(r) => r,
        Err(e) => {
            return Ok(SmtpAttempt::Skipped {
                reason: format!("banner: {e}"),
                transient: true,
            });
        }
    };
    if !banner.is_2xx() {
        return Ok(SmtpAttempt::Skipped {
            reason: format!("banner {}: {}", banner.code, banner.text),
            transient: banner.is_4xx(),
        });
    }

    // EHLO.
    let ehlo = send_cmd(
        &mut session,
        &format!("EHLO {}\r\n", delivery.helo_name),
        delivery.io_timeout,
    )
    .await?;
    let extensions = if ehlo.is_2xx() {
        ehlo.text.clone()
    } else {
        // HELO fallback.
        let helo = send_cmd(
            &mut session,
            &format!("HELO {}\r\n", delivery.helo_name),
            delivery.io_timeout,
        )
        .await?;
        if !helo.is_2xx() {
            return Ok(SmtpAttempt::Skipped {
                reason: format!("HELO/EHLO refused: {} {}", helo.code, helo.text),
                transient: helo.is_4xx(),
            });
        }
        String::new()
    };

    let starttls_offered = extensions.lines().any(|l| {
        l.trim().eq_ignore_ascii_case("STARTTLS")
            || l.trim().to_ascii_uppercase().contains(" STARTTLS")
    });

    if starttls_offered {
        match attempt_starttls(
            session,
            delivery.mx_host,
            delivery.io_timeout,
            delivery.helo_name,
        )
        .await
        {
            Ok(s) => session = s,
            Err(e) if delivery.require_tls => {
                return Ok(SmtpAttempt::Skipped {
                    reason: format!("STARTTLS required but failed: {e}"),
                    transient: true,
                });
            }
            Err(e) => {
                warn!(error = %e, "STARTTLS failed, falling back to plaintext");
                // Reconnect plain since the previous session is in an unknown
                // state. Standard MX policy: opportunistic encryption.
                let tcp = match timeout(
                    delivery.connect_timeout,
                    TcpStream::connect(&connect_target),
                )
                .await
                {
                    Ok(Ok(s)) => s,
                    _ => {
                        return Ok(SmtpAttempt::Skipped {
                            reason: "reconnect after STARTTLS failure failed".to_string(),
                            transient: true,
                        });
                    }
                };
                tcp.set_nodelay(true).ok();
                session = Session::Plain(BufStream::new(tcp));
                let banner = read_reply(&mut session, delivery.io_timeout).await?;
                if !banner.is_2xx() {
                    return Ok(SmtpAttempt::Skipped {
                        reason: format!("post-fallback banner {}: {}", banner.code, banner.text),
                        transient: banner.is_4xx(),
                    });
                }
                let helo = send_cmd(
                    &mut session,
                    &format!("EHLO {}\r\n", delivery.helo_name),
                    delivery.io_timeout,
                )
                .await?;
                if !helo.is_2xx() {
                    return Ok(SmtpAttempt::Skipped {
                        reason: format!("EHLO after fallback: {} {}", helo.code, helo.text),
                        transient: helo.is_4xx(),
                    });
                }
            }
        }
    } else if delivery.require_tls {
        return Ok(SmtpAttempt::Skipped {
            reason: "STARTTLS required but not offered".to_string(),
            transient: true,
        });
    }

    // MAIL FROM.
    let mail_from = send_cmd(
        &mut session,
        &format!("MAIL FROM:<{}>\r\n", delivery.envelope_from),
        delivery.io_timeout,
    )
    .await?;
    if !mail_from.is_2xx() {
        return Ok(SmtpAttempt::Skipped {
            reason: format!("MAIL FROM: {} {}", mail_from.code, mail_from.text),
            transient: mail_from.is_4xx(),
        });
    }

    // RCPT TO — track per-recipient outcomes.
    let mut outcomes: Vec<RecipientOutcome> = Vec::with_capacity(delivery.recipients.len());
    let mut accepted_indices: Vec<usize> = Vec::new();

    for (idx, rcpt) in delivery.recipients.iter().enumerate() {
        let reply = send_cmd(
            &mut session,
            &format!("RCPT TO:<{rcpt}>\r\n"),
            delivery.io_timeout,
        )
        .await?;
        if reply.is_2xx() {
            accepted_indices.push(idx);
            outcomes.push(RecipientOutcome {
                recipient: rcpt.clone(),
                status: RelayStatus::Delivered {
                    mx: delivery.mx_host.to_string(),
                    smtp_code: reply.code,
                    smtp_msg: first_line(&reply.text),
                },
            });
        } else if reply.is_4xx() {
            outcomes.push(RecipientOutcome {
                recipient: rcpt.clone(),
                status: RelayStatus::TempFail {
                    reason: format!("RCPT TO: {}", first_line(&reply.text)),
                    smtp_code: Some(reply.code),
                },
            });
        } else {
            outcomes.push(RecipientOutcome {
                recipient: rcpt.clone(),
                status: RelayStatus::PermFail {
                    reason: format!("RCPT TO: {}", first_line(&reply.text)),
                    smtp_code: Some(reply.code),
                },
            });
        }
    }

    if accepted_indices.is_empty() {
        // No recipients accepted; close cleanly and return the per-RCPT
        // verdicts as-is.
        let _ = send_cmd(&mut session, "QUIT\r\n", delivery.io_timeout).await;
        return Ok(SmtpAttempt::Reached(outcomes));
    }

    // DATA.
    let data = send_cmd(&mut session, "DATA\r\n", delivery.io_timeout).await?;
    if !data.is_3xx() {
        // 354 expected. Convert all accepted recipients to TempFail/PermFail.
        let transient = data.is_4xx();
        for idx in accepted_indices {
            let reason = format!("DATA: {}", first_line(&data.text));
            outcomes[idx].status = if transient {
                RelayStatus::TempFail {
                    reason,
                    smtp_code: Some(data.code),
                }
            } else {
                RelayStatus::PermFail {
                    reason,
                    smtp_code: Some(data.code),
                }
            };
        }
        let _ = send_cmd(&mut session, "QUIT\r\n", delivery.io_timeout).await;
        return Ok(SmtpAttempt::Reached(outcomes));
    }

    // Body — dot-stuff and terminate.
    write_body(&mut session, delivery.raw_message, delivery.io_timeout).await?;
    let final_reply = read_reply(&mut session, delivery.io_timeout).await?;

    let _ = send_cmd(&mut session, "QUIT\r\n", delivery.io_timeout).await;

    if !final_reply.is_2xx() {
        let transient = final_reply.is_4xx();
        for idx in accepted_indices {
            let reason = format!("DATA end: {}", first_line(&final_reply.text));
            outcomes[idx].status = if transient {
                RelayStatus::TempFail {
                    reason,
                    smtp_code: Some(final_reply.code),
                }
            } else {
                RelayStatus::PermFail {
                    reason,
                    smtp_code: Some(final_reply.code),
                }
            };
        }
    } else {
        // Update the canonical Delivered code/msg with the post-DATA reply
        // so downstream logs reflect the upstream's final acknowledgement.
        for idx in accepted_indices {
            let mx = match &outcomes[idx].status {
                RelayStatus::Delivered { mx, .. } => mx.clone(),
                _ => delivery.mx_host.to_string(),
            };
            outcomes[idx].status = RelayStatus::Delivered {
                mx,
                smtp_code: final_reply.code,
                smtp_msg: first_line(&final_reply.text),
            };
        }
    }

    Ok(SmtpAttempt::Reached(outcomes))
}

#[allow(clippy::large_enum_variant)] // Both variants are short-lived per session; boxing adds an unnecessary heap allocation in the hot plaintext path.
enum Session {
    Plain(BufStream<TcpStream>),
    Tls(BufStream<TlsStream<TcpStream>>),
}

#[derive(Debug, Clone)]
struct Reply {
    code: u16,
    text: String,
}

impl Reply {
    fn is_2xx(&self) -> bool {
        (200..300).contains(&self.code)
    }
    fn is_3xx(&self) -> bool {
        (300..400).contains(&self.code)
    }
    fn is_4xx(&self) -> bool {
        (400..500).contains(&self.code)
    }
}

async fn read_reply(session: &mut Session, io_timeout: Duration) -> Result<Reply> {
    match session {
        Session::Plain(s) => read_reply_inner(s, io_timeout).await,
        Session::Tls(s) => read_reply_inner(s, io_timeout).await,
    }
}

async fn read_reply_inner<R: AsyncBufReadExt + AsyncRead + Unpin>(
    s: &mut R,
    io_timeout: Duration,
) -> Result<Reply> {
    let mut text = String::new();
    let mut code: Option<u16> = None;
    loop {
        let mut line = String::new();
        let n = timeout(io_timeout, s.read_line(&mut line))
            .await
            .map_err(|_| anyhow!("smtp read timeout"))??;
        if n == 0 {
            bail!("smtp peer closed before final reply");
        }
        if line.len() < 4 {
            bail!("malformed smtp reply: {line:?}");
        }
        let this_code: u16 = line[..3].parse().context("smtp reply code")?;
        if let Some(prev) = code
            && prev != this_code
        {
            bail!("inconsistent multiline reply codes: {prev} vs {this_code}");
        }
        code = Some(this_code);
        let sep = line.as_bytes()[3];
        let rest = line[4..].trim_end_matches(['\r', '\n']).to_string();
        if !text.is_empty() {
            text.push('\n');
        }
        text.push_str(&rest);
        if sep == b' ' {
            return Ok(Reply {
                code: this_code,
                text,
            });
        }
        if sep != b'-' {
            bail!("malformed smtp reply separator: {sep}");
        }
    }
}

async fn send_cmd(session: &mut Session, line: &str, io_timeout: Duration) -> Result<Reply> {
    write_all(session, line.as_bytes(), io_timeout).await?;
    flush(session, io_timeout).await?;
    read_reply(session, io_timeout).await
}

async fn write_all(session: &mut Session, buf: &[u8], io_timeout: Duration) -> Result<()> {
    match session {
        Session::Plain(s) => timeout(io_timeout, s.write_all(buf))
            .await
            .map_err(|_| anyhow!("smtp write timeout"))??,
        Session::Tls(s) => timeout(io_timeout, s.write_all(buf))
            .await
            .map_err(|_| anyhow!("smtp write timeout"))??,
    }
    Ok(())
}

async fn flush(session: &mut Session, io_timeout: Duration) -> Result<()> {
    match session {
        Session::Plain(s) => timeout(io_timeout, s.flush())
            .await
            .map_err(|_| anyhow!("smtp flush timeout"))??,
        Session::Tls(s) => timeout(io_timeout, s.flush())
            .await
            .map_err(|_| anyhow!("smtp flush timeout"))??,
    }
    Ok(())
}

async fn write_body(session: &mut Session, raw: &[u8], io_timeout: Duration) -> Result<()> {
    // Dot-stuff: any line starting with '.' must be doubled.
    let stuffed = dot_stuff(raw);
    write_all(session, &stuffed, io_timeout).await?;
    if !stuffed.ends_with(b"\r\n") {
        write_all(session, b"\r\n", io_timeout).await?;
    }
    write_all(session, b".\r\n", io_timeout).await?;
    flush(session, io_timeout).await?;
    Ok(())
}

fn dot_stuff(raw: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(raw.len() + raw.len() / 64);
    let mut at_line_start = true;
    for &b in raw {
        if at_line_start && b == b'.' {
            out.push(b'.');
        }
        out.push(b);
        at_line_start = b == b'\n';
    }
    // Normalise stray bare-LF to CRLF — RFC 5321 strict transmission.
    crlf_normalise(out)
}

fn crlf_normalise(raw: Vec<u8>) -> Vec<u8> {
    let mut out = Vec::with_capacity(raw.len());
    let mut prev: Option<u8> = None;
    for b in raw {
        if b == b'\n' && prev != Some(b'\r') {
            out.push(b'\r');
        }
        out.push(b);
        prev = Some(b);
    }
    out
}

fn first_line(s: &str) -> String {
    s.lines().next().unwrap_or("").trim().to_string()
}

async fn attempt_starttls(
    mut session: Session,
    mx_host: &str,
    io_timeout: Duration,
    helo_name: &str,
) -> Result<Session> {
    let reply = send_cmd(&mut session, "STARTTLS\r\n", io_timeout).await?;
    if !reply.is_2xx() {
        bail!("STARTTLS refused: {} {}", reply.code, reply.text);
    }
    let plain = match session {
        Session::Plain(s) => s.into_inner(),
        Session::Tls(_) => bail!("STARTTLS on already-encrypted session"),
    };

    let mut roots = RootCertStore::empty();
    roots.extend(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());
    let cfg = ClientConfig::builder()
        .with_root_certificates(roots)
        .with_no_client_auth();
    let connector = TlsConnector::from(Arc::new(cfg));
    let server_name: ServerName<'_> = ServerName::try_from(mx_host.to_string())
        .map_err(|e| anyhow!("invalid TLS server name `{mx_host}`: {e}"))?;
    let tls = timeout(io_timeout, connector.connect(server_name, plain))
        .await
        .map_err(|_| anyhow!("TLS handshake timeout"))??;

    let mut session = Session::Tls(BufStream::new(tls));
    // Re-issue EHLO inside the TLS tunnel (RFC 3207).
    let reply = send_cmd(&mut session, &format!("EHLO {helo_name}\r\n"), io_timeout).await?;
    if !reply.is_2xx() {
        bail!("EHLO inside TLS: {} {}", reply.code, reply.text);
    }
    debug!("STARTTLS established with {}", mx_host);
    Ok(session)
}
