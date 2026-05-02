//! Length-prefixed Noise transport framing on top of any
//! [`AsyncRead`] + [`AsyncWrite`] stream.
//!
//! Wire layout per Noise transport message:
//!
//! ```text
//! [ u32 BE ciphertext length ][ ciphertext bytes ]
//! ```
//!
//! Plaintext payloads are [`postcard`]-encoded [`Frame`] values. If a
//! single serialized frame exceeds [`MAX_PLAINTEXT_FRAME_BYTES`], the
//! sender splits it into [`Frame::RelayChunk`] continuations. The
//! receiver reassembles transparently inside [`Channel::recv_frame`].

use std::collections::HashMap;

use thiserror::Error;
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};

use crate::frame::{
    Frame, MAX_PLAINTEXT_FRAME_BYTES, ProtoError, RelayChunkPayload, decode_frame, encode_frame,
};
use crate::{MAX_CIPHERTEXT_FRAME_BYTES, PROTO_VERSION};

/// Errors produced by [`Channel`].
#[derive(Debug, Error)]
pub enum ChannelError {
    /// Underlying I/O error.
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    /// Encoded ciphertext exceeded [`MAX_CIPHERTEXT_FRAME_BYTES`].
    #[error("ciphertext frame too large: {0} bytes")]
    FrameTooLarge(usize),
    /// `snow` transport encrypt/decrypt failure.
    #[error("snow transport: {0}")]
    Snow(#[from] snow::Error),
    /// Frame encoding / decoding failure.
    #[error("proto: {0}")]
    Proto(#[from] ProtoError),
    /// Reassembly received an out-of-order or duplicate chunk.
    #[error("invalid relay chunking: {0}")]
    BadChunking(&'static str),
    /// Peer closed the channel mid-message.
    #[error("eof while reading frame")]
    UnexpectedEof,
    /// Reassembly buffer would exceed the configured cap.
    #[error("reassembled frame exceeds {limit} bytes")]
    ReassemblyOverflow {
        /// Configured maximum reassembled-frame size.
        limit: usize,
    },
    /// Negotiation precondition failed (e.g. unexpected first frame).
    #[error("protocol violation: {0}")]
    Protocol(&'static str),
}

/// Bidirectional Noise transport channel.
///
/// `S` is typically `tokio::net::TcpStream`, but anything implementing
/// `AsyncRead + AsyncWrite + Unpin` works (test doubles, TLS streams, ...).
#[derive(Debug)]
pub struct Channel<S> {
    inner: S,
    transport: snow::TransportState,
    /// In-flight reassembly buffers keyed by `request_id`.
    pending: HashMap<u64, ReassemblyState>,
    /// Maximum reassembled plaintext per logical frame.
    max_reassembled: usize,
}

#[derive(Debug)]
struct ReassemblyState {
    total: u32,
    received: u32,
    buf: Vec<u8>,
}

impl<S: AsyncRead + AsyncWrite + Unpin> Channel<S> {
    /// Wrap a Noise [`snow::TransportState`] (post-handshake) and the
    /// underlying byte stream into a framed channel.
    ///
    /// `max_reassembled_plaintext` caps the total size of any reassembled
    /// `Relay` payload (defends against a malicious peer claiming a huge
    /// `total` chunk count).
    #[must_use]
    pub fn new(
        inner: S,
        transport: snow::TransportState,
        max_reassembled_plaintext: usize,
    ) -> Self {
        Self {
            inner,
            transport,
            pending: HashMap::new(),
            max_reassembled: max_reassembled_plaintext,
        }
    }

    /// Send one logical [`Frame`], chunking if the serialized payload is
    /// larger than [`MAX_PLAINTEXT_FRAME_BYTES`].
    ///
    /// # Errors
    ///
    /// Returns [`ChannelError::Io`], [`ChannelError::Snow`], or
    /// [`ChannelError::Proto`] on encoding / encryption / write failure.
    pub async fn send_frame(&mut self, frame: &Frame) -> Result<(), ChannelError> {
        let plaintext = encode_frame(frame)?;
        if plaintext.len() <= MAX_PLAINTEXT_FRAME_BYTES {
            return self.write_plaintext(&plaintext).await;
        }

        // Only Relay frames are eligible for chunking — everything else
        // is bounded by design. If a non-Relay frame ever exceeds the
        // limit, it's a programming error.
        let request_id = match frame {
            Frame::Relay { request_id, .. } => *request_id,
            _ => {
                return Err(ChannelError::BadChunking(
                    "non-Relay frame too large to fit in one Noise transport message",
                ));
            }
        };

        let total_chunks = plaintext.len().div_ceil(MAX_PLAINTEXT_FRAME_BYTES);
        let total_u32 = u32::try_from(total_chunks)
            .map_err(|_| ChannelError::BadChunking("relay too large to chunk"))?;

        for (seq, chunk) in plaintext.chunks(MAX_PLAINTEXT_FRAME_BYTES).enumerate() {
            let payload = RelayChunkPayload {
                request_id,
                seq: u32::try_from(seq).map_err(|_| ChannelError::BadChunking("seq overflow"))?,
                total: total_u32,
                data: chunk.to_vec(),
            };
            let chunk_frame = Frame::RelayChunk(payload);
            let chunk_bytes = encode_frame(&chunk_frame)?;
            // Each chunk carries up to MAX_PLAINTEXT_FRAME_BYTES of payload
            // plus a small postcard header — leaves room under the Noise
            // 65 535-byte transport limit.
            self.write_plaintext(&chunk_bytes).await?;
        }
        Ok(())
    }

    /// Receive one logical [`Frame`], reassembling [`Frame::RelayChunk`]
    /// continuations transparently.
    ///
    /// # Errors
    ///
    /// Returns [`ChannelError`] variants for I/O, decryption, decoding,
    /// reassembly, or peer EOF conditions.
    pub async fn recv_frame(&mut self) -> Result<Frame, ChannelError> {
        loop {
            let plaintext = self.read_plaintext().await?;
            let frame = decode_frame(&plaintext)?;

            let chunk = match frame {
                Frame::RelayChunk(c) => c,
                other => return Ok(other),
            };

            let entry = self
                .pending
                .entry(chunk.request_id)
                .or_insert_with(|| ReassemblyState {
                    total: chunk.total,
                    received: 0,
                    buf: Vec::new(),
                });

            if chunk.total != entry.total {
                self.pending.remove(&chunk.request_id);
                return Err(ChannelError::BadChunking("total mismatch across chunks"));
            }
            if chunk.seq != entry.received {
                self.pending.remove(&chunk.request_id);
                return Err(ChannelError::BadChunking("out-of-order chunk"));
            }
            if entry.buf.len() + chunk.data.len() > self.max_reassembled {
                self.pending.remove(&chunk.request_id);
                return Err(ChannelError::ReassemblyOverflow {
                    limit: self.max_reassembled,
                });
            }

            entry.buf.extend_from_slice(&chunk.data);
            entry.received += 1;

            if entry.received == entry.total {
                let state = self
                    .pending
                    .remove(&chunk.request_id)
                    .ok_or(ChannelError::BadChunking("internal: missing state"))?;
                return Ok(decode_frame(&state.buf)?);
            }
            // else: keep reading more chunks.
        }
    }

    /// Consume the channel and return the wrapped stream + transport.
    pub fn into_inner(self) -> (S, snow::TransportState) {
        (self.inner, self.transport)
    }

    async fn write_plaintext(&mut self, plaintext: &[u8]) -> Result<(), ChannelError> {
        // Noise tag is 16 bytes for ChaCha20-Poly1305.
        let mut buf = vec![0u8; plaintext.len() + 16];
        let n = self.transport.write_message(plaintext, &mut buf)?;
        if n > MAX_CIPHERTEXT_FRAME_BYTES {
            return Err(ChannelError::FrameTooLarge(n));
        }
        let len = u32::try_from(n).map_err(|_| ChannelError::FrameTooLarge(n))?;
        self.inner.write_all(&len.to_be_bytes()).await?;
        self.inner.write_all(&buf[..n]).await?;
        self.inner.flush().await?;
        Ok(())
    }

    async fn read_plaintext(&mut self) -> Result<Vec<u8>, ChannelError> {
        let mut len_buf = [0u8; 4];
        match self.inner.read_exact(&mut len_buf).await {
            Ok(_) => {}
            Err(e) if e.kind() == std::io::ErrorKind::UnexpectedEof => {
                return Err(ChannelError::UnexpectedEof);
            }
            Err(e) => return Err(ChannelError::Io(e)),
        }
        let len = u32::from_be_bytes(len_buf) as usize;
        if len > MAX_CIPHERTEXT_FRAME_BYTES {
            return Err(ChannelError::FrameTooLarge(len));
        }
        let mut ct = vec![0u8; len];
        self.inner.read_exact(&mut ct).await?;
        let mut pt = vec![0u8; len];
        let n = self.transport.read_message(&ct, &mut pt)?;
        pt.truncate(n);
        Ok(pt)
    }
}

/// Convenience: assert that the first frame received is a [`Frame::Hello`]
/// matching the negotiated [`PROTO_VERSION`]; return the parsed components.
///
/// # Errors
///
/// Returns [`ChannelError::Protocol`] if the first frame is not `Hello`,
/// or [`ChannelError`] on I/O / decoding errors.
pub async fn expect_hello<S: AsyncRead + AsyncWrite + Unpin>(
    ch: &mut Channel<S>,
) -> Result<(String, String), ChannelError> {
    match ch.recv_frame().await? {
        Frame::Hello {
            proto_version,
            client_id,
            sidecar_version,
        } if proto_version == PROTO_VERSION => Ok((client_id, sidecar_version)),
        Frame::Hello { .. } => Err(ChannelError::Protocol("hello: proto version mismatch")),
        _ => Err(ChannelError::Protocol("expected Hello frame first")),
    }
}
