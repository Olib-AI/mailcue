//! Wire-level [`Frame`] enum exchanged after the Noise handshake.
//!
//! Frames are encoded with [`postcard`] for stable, compact serialization,
//! then split into 60 KiB plaintext chunks before being handed to the
//! Noise transport layer. See [`crate::channel::Channel`] for the
//! framing / chunking implementation.

use bytes::Bytes;
use serde::{Deserialize, Serialize};
use thiserror::Error;

/// Maximum *plaintext* bytes per Noise transport message.
///
/// We cap this well under Noise's 65 535-byte payload limit so the encrypted
/// frame (plus auth tag and length prefix) always fits below
/// [`crate::MAX_CIPHERTEXT_FRAME_BYTES`].
pub const MAX_PLAINTEXT_FRAME_BYTES: usize = 60 * 1024;

/// All wire-level frames exchanged on a tunnel.
///
/// Frames are versioned implicitly by [`crate::PROTO_VERSION`] inside
/// [`Frame::Hello`] / [`Frame::HelloAck`]. New variants must always be
/// added at the *end* to preserve `postcard`'s positional encoding.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum Frame {
    /// Sidecar → edge: opening greeting after Noise handshake.
    Hello {
        /// Negotiated protocol version. Must equal [`crate::PROTO_VERSION`].
        proto_version: u16,
        /// Sidecar-supplied identifier (free-form, used only for logging).
        client_id: String,
        /// `mailcue-relay-sidecar` semver string.
        sidecar_version: String,
    },
    /// Edge → sidecar: greeting acknowledgement.
    HelloAck {
        /// Edge protocol version. Must equal [`crate::PROTO_VERSION`].
        proto_version: u16,
        /// `mailcue-relay-edge` semver string.
        edge_version: String,
        /// Edge wall-clock at handshake completion (seconds since epoch).
        server_time_unix: u64,
    },
    /// Sidecar → edge: relay an outbound mail through the edge's network.
    ///
    /// `raw_message` is the full RFC 5322 message *as it should appear on
    /// the wire* (DOT-stuffing is applied by the edge during DATA).
    Relay {
        /// Sidecar-chosen request id. Must be unique on this channel.
        request_id: u64,
        /// Envelope `MAIL FROM`. Must parse as a mailbox.
        envelope_from: String,
        /// Envelope `RCPT TO` list. Bounded by the edge's
        /// `max_recipients_per_request`.
        recipients: Vec<String>,
        /// RFC 5322 message bytes.
        raw_message: Bytes,
        /// Per-request relay options.
        opts: RelayOpts,
    },
    /// One chunk of a [`Frame::Relay`] payload that exceeded
    /// [`MAX_PLAINTEXT_FRAME_BYTES`] when serialized whole.
    ///
    /// See [`crate::channel::Channel::send_frame`] for chunking semantics.
    RelayChunk(RelayChunkPayload),
    /// Edge → sidecar: per-recipient relay outcome.
    RelayResult {
        /// Echoes the `request_id` from the matching [`Frame::Relay`].
        request_id: u64,
        /// One [`RecipientResult`] per recipient, in the input order.
        per_recipient: Vec<RecipientResult>,
    },
    /// Sidecar → edge: liveness probe.
    Ping {
        /// Sender wall-clock (seconds since epoch).
        ts_unix: u64,
        /// Random probe id, echoed in [`Frame::Pong`].
        nonce: u64,
    },
    /// Edge → sidecar: liveness response.
    Pong {
        /// Sender wall-clock (seconds since epoch).
        ts_unix: u64,
        /// Echoes the [`Frame::Ping`] nonce.
        nonce: u64,
    },
    /// Either side: fatal protocol error. The connection is closed after
    /// sending or receiving an `Error`.
    Error {
        /// `request_id` of the offending frame, if applicable.
        request_id: Option<u64>,
        /// Machine-readable error class.
        code: ErrorCode,
        /// Human-readable detail. Never contains message content.
        message: String,
    },
}

/// Continuation payload for a multi-frame [`Frame::Relay`].
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RelayChunkPayload {
    /// Sidecar-chosen reassembly id (matches the eventual `request_id`).
    pub request_id: u64,
    /// Zero-based chunk index.
    pub seq: u32,
    /// Total chunk count for this `request_id`.
    pub total: u32,
    /// Raw bytes of the underlying serialized [`Frame::Relay`].
    #[serde(with = "serde_bytes_as_vec")]
    pub data: Vec<u8>,
}

/// Per-relay options, carried inside [`Frame::Relay`].
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct RelayOpts {
    /// Override the EHLO/HELO hostname the edge presents to upstream MX.
    pub helo_name: Option<String>,
    /// If `true`, fail the relay rather than fall back to plaintext SMTP
    /// when STARTTLS is unavailable. Defaults to `false` on the wire.
    pub require_tls: bool,
    /// Per-relay timeout override, in seconds (0 = use edge default).
    pub timeout_secs: u32,
}

/// Outcome for one recipient in a [`Frame::RelayResult`].
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RecipientResult {
    /// Recipient address (SMTP-encoded mailbox).
    pub recipient: String,
    /// Final relay status.
    pub status: RelayStatus,
}

/// Per-recipient delivery outcome.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum RelayStatus {
    /// 2xx response from the upstream MX. The mail is the upstream's problem now.
    Delivered {
        /// MX hostname that accepted the message.
        mx: String,
        /// SMTP reply code (e.g. 250).
        smtp_code: u16,
        /// First line of the SMTP reply, trimmed.
        smtp_msg: String,
    },
    /// Transient failure — Postfix will retry.
    TempFail {
        /// Free-form explanation (timeout / 4xx text / network error).
        reason: String,
        /// Last SMTP reply code seen, if any.
        smtp_code: Option<u16>,
    },
    /// Permanent failure — Postfix will bounce.
    PermFail {
        /// Free-form explanation (5xx text / unrecoverable parse error).
        reason: String,
        /// Last SMTP reply code seen, if any.
        smtp_code: Option<u16>,
    },
}

/// Machine-readable error categories for [`Frame::Error`].
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ErrorCode {
    /// Frame did not match the negotiated protocol.
    ProtocolViolation,
    /// Static key not present in the edge's allow-list.
    Unauthorized,
    /// Per-client concurrency / rate limit exceeded.
    RateLimited,
    /// Message size > `max_message_size_bytes`.
    MessageTooLarge,
    /// Recipient list > `max_recipients_per_request`.
    TooManyRecipients,
    /// Catch-all for unexpected internal errors.
    Internal,
}

/// Frame encode/decode failures.
#[derive(Debug, Error)]
pub enum ProtoError {
    /// `postcard` serialization failure.
    #[error("postcard encode: {0}")]
    Encode(postcard::Error),
    /// `postcard` deserialization failure.
    #[error("postcard decode: {0}")]
    Decode(postcard::Error),
}

/// Encode a [`Frame`] to a `postcard` byte vector.
///
/// # Errors
///
/// Returns [`ProtoError::Encode`] if the underlying `postcard` serializer
/// fails, which in practice only happens for malformed UTF-8 in
/// caller-supplied strings (postcard validates internally).
pub fn encode_frame(frame: &Frame) -> Result<Vec<u8>, ProtoError> {
    postcard::to_allocvec(frame).map_err(ProtoError::Encode)
}

/// Decode a [`Frame`] from a `postcard` byte slice.
///
/// # Errors
///
/// Returns [`ProtoError::Decode`] if `bytes` is truncated, contains an
/// unknown variant tag, or otherwise fails `postcard`'s checks.
pub fn decode_frame(bytes: &[u8]) -> Result<Frame, ProtoError> {
    postcard::from_bytes(bytes).map_err(ProtoError::Decode)
}

mod serde_bytes_as_vec {
    use serde::{Deserialize, Deserializer, Serializer};

    pub fn serialize<S: Serializer>(v: &Vec<u8>, s: S) -> Result<S::Ok, S::Error> {
        serde::Serialize::serialize(v, s)
    }

    pub fn deserialize<'de, D: Deserializer<'de>>(d: D) -> Result<Vec<u8>, D::Error> {
        Vec::<u8>::deserialize(d)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use bytes::Bytes;

    #[test]
    fn hello_roundtrip() {
        let f = Frame::Hello {
            proto_version: 1,
            client_id: "test".into(),
            sidecar_version: "0.1.0".into(),
        };
        let enc = encode_frame(&f).unwrap();
        match decode_frame(&enc).unwrap() {
            Frame::Hello { client_id, .. } => assert_eq!(client_id, "test"),
            _ => panic!("wrong variant"),
        }
    }

    #[test]
    fn relay_roundtrip() {
        let f = Frame::Relay {
            request_id: 42,
            envelope_from: "a@b".into(),
            recipients: vec!["c@d".into()],
            raw_message: Bytes::from_static(b"From: a@b\r\nTo: c@d\r\n\r\nbody"),
            opts: RelayOpts::default(),
        };
        let enc = encode_frame(&f).unwrap();
        match decode_frame(&enc).unwrap() {
            Frame::Relay {
                request_id,
                recipients,
                ..
            } => {
                assert_eq!(request_id, 42);
                assert_eq!(recipients, vec!["c@d".to_string()]);
            }
            _ => panic!("wrong variant"),
        }
    }
}
