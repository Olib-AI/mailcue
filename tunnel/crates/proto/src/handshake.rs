//! Noise IK handshake driver.
//!
//! `Noise_IK_25519_ChaChaPoly_BLAKE2s` is a one-round-trip pattern: the
//! initiator (the sidecar) sends an opening message that includes its own
//! static public key (encrypted to the responder), and the responder
//! replies with a single message. After the second message, both sides
//! have a [`snow::TransportState`] and the responder also knows the
//! initiator's static public key (recoverable via
//! [`snow::HandshakeState::get_remote_static`]).
//!
//! Wire layout for handshake messages on top of TCP — same length-prefixed
//! framing as transport frames:
//!
//! ```text
//! [ u32 BE message length ][ noise message bytes ]
//! ```

use snow::{Builder, HandshakeState, TransportState};
use thiserror::Error;
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};

use crate::{MAX_CIPHERTEXT_FRAME_BYTES, NOISE_PATTERN};

/// Maximum bytes for a single Noise handshake message (well above the
/// 96-byte IK first message and 48-byte IK second message — leaves
/// generous slack for future PSK extensions).
const MAX_HANDSHAKE_MSG: usize = 1024;

/// Noise handshake errors.
#[derive(Debug, Error)]
pub enum HandshakeError {
    /// Underlying I/O error.
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    /// `snow` handshake / cipher error.
    #[error("snow: {0}")]
    Snow(#[from] snow::Error),
    /// Failed to parse the Noise pattern string.
    #[error("invalid noise pattern: {0}")]
    Pattern(String),
    /// Peer sent a handshake message larger than [`MAX_HANDSHAKE_MSG`] or
    /// larger than [`MAX_CIPHERTEXT_FRAME_BYTES`].
    #[error("handshake message too large: {0} bytes")]
    MessageTooLarge(usize),
    /// Connection closed mid-handshake.
    #[error("eof during handshake")]
    UnexpectedEof,
}

/// Which side of the Noise IK handshake we are.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HandshakeRole {
    /// Sidecar — we know the edge's static public key out-of-band.
    Initiator {
        /// Edge's expected static public key (32 bytes).
        remote_static: [u8; 32],
    },
    /// Edge — we accept any initiator and check their key against the
    /// allow-list *after* the handshake completes.
    Responder,
}

/// Drive the Noise IK handshake on `stream` to completion.
///
/// On success returns the [`TransportState`] (ready for [`crate::Channel`])
/// plus the peer's 32-byte static public key.
///
/// # Errors
///
/// Returns [`HandshakeError`] on snow / I/O failure.
pub async fn perform_handshake<S>(
    stream: &mut S,
    local_static_private: &[u8; 32],
    role: HandshakeRole,
) -> Result<(TransportState, [u8; 32]), HandshakeError>
where
    S: AsyncRead + AsyncWrite + Unpin,
{
    let params = NOISE_PATTERN
        .parse()
        .map_err(|e: snow::Error| HandshakeError::Pattern(e.to_string()))?;

    // snow 0.10 changed `local_private_key` and `remote_public_key` to
    // return `Result<Self, Error>` instead of `Self`.
    let builder = Builder::new(params).local_private_key(local_static_private)?;

    let mut state: HandshakeState = match role {
        HandshakeRole::Initiator { remote_static } => builder
            .remote_public_key(&remote_static)?
            .build_initiator()?,
        HandshakeRole::Responder => builder.build_responder()?,
    };

    let mut buf = vec![0u8; MAX_HANDSHAKE_MSG];

    while !state.is_handshake_finished() {
        if state.is_my_turn() {
            let n = state.write_message(&[], &mut buf)?;
            write_msg(stream, &buf[..n]).await?;
        } else {
            let msg = read_msg(stream).await?;
            let mut payload = vec![0u8; MAX_HANDSHAKE_MSG];
            let _ = state.read_message(&msg, &mut payload)?;
        }
    }

    let remote_static = state
        .get_remote_static()
        .ok_or(HandshakeError::Snow(snow::Error::Input))?;
    let mut rs = [0u8; 32];
    rs.copy_from_slice(&remote_static[..32]);

    let transport = state.into_transport_mode()?;
    Ok((transport, rs))
}

async fn write_msg<S: AsyncWrite + Unpin>(
    stream: &mut S,
    msg: &[u8],
) -> Result<(), HandshakeError> {
    if msg.len() > MAX_HANDSHAKE_MSG || msg.len() > MAX_CIPHERTEXT_FRAME_BYTES {
        return Err(HandshakeError::MessageTooLarge(msg.len()));
    }
    let len = u32::try_from(msg.len()).map_err(|_| HandshakeError::MessageTooLarge(msg.len()))?;
    stream.write_all(&len.to_be_bytes()).await?;
    stream.write_all(msg).await?;
    stream.flush().await?;
    Ok(())
}

async fn read_msg<S: AsyncRead + Unpin>(stream: &mut S) -> Result<Vec<u8>, HandshakeError> {
    let mut len_buf = [0u8; 4];
    match stream.read_exact(&mut len_buf).await {
        Ok(_) => {}
        Err(e) if e.kind() == std::io::ErrorKind::UnexpectedEof => {
            return Err(HandshakeError::UnexpectedEof);
        }
        Err(e) => return Err(HandshakeError::Io(e)),
    }
    let len = u32::from_be_bytes(len_buf) as usize;
    if len > MAX_HANDSHAKE_MSG {
        return Err(HandshakeError::MessageTooLarge(len));
    }
    let mut buf = vec![0u8; len];
    stream.read_exact(&mut buf).await?;
    Ok(buf)
}
