//! Wire protocol and Noise IK framing for the MailCue out-of-band SMTP tunnel.
//!
//! This crate is shared by `mailcue-relay-edge` (the OVH-side listener) and
//! `mailcue-relay-sidecar` (the loopback SMTP submission shim that runs next
//! to the MailCue mail server).
//!
//! # Wire format (summary)
//!
//! 1. TCP connection.
//! 2. Noise IK handshake using the `Noise_IK_25519_ChaChaPoly_BLAKE2s`
//!    pattern (the same as WireGuard). The initiator (sidecar) knows the
//!    responder's static key out-of-band and authenticates itself by
//!    presenting its own static key.
//! 3. After the handshake completes, both sides switch to transport mode
//!    and exchange [`Frame`] values:
//!    `[u32 BE length][snow-encrypted ciphertext]`.
//! 4. The plaintext payload is a [`postcard`]-encoded [`Frame`].
//!
//! See `docs/PROTOCOL.md` for the authoritative specification.

#![deny(unsafe_code, rust_2018_idioms)]
#![warn(missing_docs)]

pub mod authorized;
pub mod channel;
pub mod frame;
pub mod handshake;
pub mod keypair;

pub use authorized::{AuthorizedClients, AuthorizedError, ClientEntry};
pub use channel::{Channel, ChannelError, expect_hello};
pub use frame::{
    ErrorCode, Frame, MAX_PLAINTEXT_FRAME_BYTES, ProtoError, RecipientResult, RelayChunkPayload,
    RelayOpts, RelayStatus, decode_frame, encode_frame,
};
pub use handshake::{HandshakeError, HandshakeRole, perform_handshake};
pub use keypair::{KeyPair, KeyPairError, pub_path};

/// The protocol version negotiated in [`Frame::Hello`] / [`Frame::HelloAck`].
///
/// Any mismatch is rejected with [`ErrorCode::ProtocolViolation`] before any
/// `Relay` frame is processed.
pub const PROTO_VERSION: u16 = 1;

/// Noise pattern handled by this crate.
pub const NOISE_PATTERN: &str = "Noise_IK_25519_ChaChaPoly_BLAKE2s";

/// Maximum ciphertext bytes per Noise transport message we will accept.
///
/// Snow's transport messages are capped at 65 535 bytes (the Noise spec
/// limit) — we leave a small margin for the Noise auth tag.
pub const MAX_CIPHERTEXT_FRAME_BYTES: usize = 65_535;

// TODO(stream-tunnel-v2): When we add bidirectional stream tunnelling
// (forwarding raw TCP from sidecar to edge so MailCue can do its own
// SMTP), introduce new frame variants here:
//   `OpenStream { stream_id, target_host, target_port, opts }`,
//   `StreamData { stream_id, payload }`,
//   `CloseStream { stream_id, reason }`.
// Keep them additive — `serde(other)`-style fallbacks let older peers
// reject unknown variants cleanly through `ErrorCode::ProtocolViolation`.
