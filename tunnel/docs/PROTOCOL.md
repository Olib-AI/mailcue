# MailCue tunnel wire protocol

This document is the authoritative specification for the wire protocol
spoken between `mailcue-relay-sidecar` (the **initiator**) and
`mailcue-relay-edge` (the **responder**). It is what an alternate
implementation needs to interoperate with the reference Rust
implementation in `tunnel/crates/proto/`.

The current protocol version, exchanged in `Hello` / `HelloAck`, is
`PROTO_VERSION = 3`.

## 1. Transport

- **TCP only.** No UDP, no QUIC. Default listen port `7843/tcp`. There is
  no fallback transport; if the sidecar can't reach the edge over TCP, it
  refuses to relay and Postfix queues mail locally.
- **No TLS at the transport layer.** Confidentiality, integrity, and
  mutual authentication are provided by Noise IK directly on the TCP
  byte stream — see §2.
- **One logical tunnel per TCP connection.** A sidecar may hold multiple
  TCP connections to one or more edges concurrently for throughput and
  redundancy.

## 2. Handshake — Noise_IK_25519_ChaChaPoly_BLAKE2s

The handshake follows the Noise Protocol Framework rev 34 IK pattern with
the `Noise_IK_25519_ChaChaPoly_BLAKE2s` cipher suite (the same suite
WireGuard uses at the transport layer; this is well-vetted territory).

- DH: Curve25519.
- Cipher: ChaCha20-Poly1305 (AEAD).
- Hash: BLAKE2s.

### Pre-shared knowledge

| Side                | Knows out-of-band                    |
|---------------------|--------------------------------------|
| Initiator (sidecar) | Responder's static public key (32 B) |
| Responder (edge)    | Nothing about the initiator a priori |

The responder authenticates the initiator **after** the handshake
completes by looking up the initiator's static public key (recovered
from the IK first message) in its `authorized_clients` allow-list. A
miss results in `Frame::Error { code: Unauthorized, ... }` and an
immediate close. See §6.

### Prologue

Empty. There is no protocol-level prologue mixed into the Noise hash
state at this version. (A future version may bind `proto_version` into
the prologue to refuse downgrade attacks; this is a forward-compatible
breaking change requiring a `proto_version` bump.)

### Message framing during handshake

Each Noise handshake message is sent on the TCP stream as:

```
[ u32 BE length ][ noise_message_bytes ]
```

Both handshake messages are well under 1 KiB (IK msg1 is 96 B + payload,
msg2 is 48 B + payload). Implementations MUST reject any handshake
message larger than 1024 bytes (`MAX_HANDSHAKE_MSG`).

### Payloads

Both Noise handshake messages carry **empty** payloads. Application
data (`Hello`, `HelloAck`, `Relay`, ...) only flows after both sides
have transitioned to transport mode.

## 3. Transport framing

Once Noise transport mode is reached, both sides exchange
length-prefixed Noise transport messages on the same TCP stream:

```
[ u32 BE ciphertext length ][ ciphertext bytes ]
```

The ciphertext is a Noise transport message — an AEAD ciphertext with
a 16-byte authentication tag.

Limits:

- Ciphertext length **MUST NOT** exceed **65535 bytes**
  (`MAX_CIPHERTEXT_FRAME_BYTES`). This is the Noise spec's per-message
  limit.
- After AEAD decryption, the plaintext is a [`postcard`](https://crates.io/crates/postcard)-encoded `Frame`.
- A single serialized `Frame` is bounded at **60 KiB**
  (`MAX_PLAINTEXT_FRAME_BYTES`). `Frame::Relay` payloads larger than
  this are split into `Frame::RelayChunk` continuations — see §5.

## 4. Frames

The plaintext payload of every transport message is a
`postcard`-encoded `Frame` enum. The Rust definition is the canonical
schema; see [`tunnel/crates/proto/src/frame.rs`](../crates/proto/src/frame.rs).
Variants, in declaration order (postcard encodes enum tags as varints
positionally — order matters):

| Tag | Variant         | Direction      | Notes |
|-----|-----------------|----------------|-------|
| 0   | `Hello`         | sidecar → edge | First app frame after handshake. Carries `proto_version`, `client_id`, `sidecar_version`. |
| 1   | `HelloAck`      | edge → sidecar | Reply to `Hello`. Carries `proto_version`, `edge_version`, `server_time_unix`. |
| 2   | `Relay`         | sidecar → edge | Outbound message. Fields: `request_id` (u64), `envelope_from` (String), `recipients` (Vec\<String\>), `raw_message` (Bytes), `opts` (RelayOpts). |
| 3   | `RelayChunk`    | sidecar → edge | Continuation chunk for an oversized `Relay`. See §5. |
| 4   | `RelayResult`   | edge → sidecar | Per-recipient outcome (Vec\<RecipientResult\>). |
| 5   | `Ping`          | sidecar → edge | Liveness probe (`ts_unix`, `nonce`). |
| 6   | `Pong`          | edge → sidecar | Liveness response (`ts_unix`, `nonce`). |
| 7   | `Error`         | either         | Fatal protocol error; connection closes after send/receive. |
| 8   | `Probe`         | sidecar → edge | Tests a target against several control recipients; never sends DATA. |
| 9   | `ProbeResult`   | edge → sidecar | Conservative target and control outcomes, with per-RCPT latency. |

`RelayOpts`:

```rust
struct RelayOpts {
    helo_name: Option<String>,   // override EHLO/HELO sent to upstream MX
    require_tls: bool,           // false = opportunistic (default)
    timeout_secs: u32,           // 0 = use edge default
}
```

`RecipientResult`:

```rust
struct RecipientResult {
    recipient: String,
    status: RelayStatus,         // Delivered | TempFail | PermFail
}
```

`ErrorCode`:

```rust
enum ErrorCode {
    ProtocolViolation,   // unknown variant, bad ordering, version mismatch
    Unauthorized,        // initiator pubkey not in allow-list
    RateLimited,         // per-client concurrency / rate cap exceeded
    MessageTooLarge,     // raw_message > max_message_size_bytes
    TooManyRecipients,   // recipients.len() > max_recipients_per_request
    Internal,            // unexpected edge-side failure
}
```

### Recipient probing

`Probe` carries one target recipient and a list of control recipients that do
not exist at the same domain. The edge probes each recipient in its own SMTP
envelope and returns a `ProbeOutcome` per recipient, each carrying the RCPT TO
latency in milliseconds.

Several controls are sent because one is not enough to tell an accept-all
destination apart from a receiver that refuses obviously synthetic local parts
while accepting plausible ones. The sidecar builds controls of three shapes: a
plausible personal name, a copy of the target's separator layout and token
lengths with the letters randomised, and a high-entropy string.

The first control in the list is probed **before** the target. A destination
that tarpits after the first recipient in a session would otherwise make every
control look rejected, which reads as recipient validation when it is only
throttling. When the first control is accepted and a later one is refused, the
sidecar reports `degraded=1` and the refusals are not treated as evidence.

A rejected target ends the probe: the remaining controls would tell us nothing
more and would only cost the destination extra connections.

The sidecar collapses the outcomes into one SMTP reply whose text carries
`key=value` diagnostics for the backend risk model:

```
252 2.1.5 accept-all upstream_code=250 mx=mx1.example.net controls_total=3 \
controls_accepted=3 controls_rejected=0 target_ms=18 control_ms=17 \
degraded=0 reputation=0 enhanced=2.1.5
```

`reputation=1` means the destination reacted to the probing host rather than to
the recipient, so none of the answers describe the mailbox.

## 5. Multi-frame `Relay` chunking

A serialized `Frame::Relay` larger than `MAX_PLAINTEXT_FRAME_BYTES`
(60 KiB) is split by the **sender** into one or more `Frame::RelayChunk`
messages and reassembled by the **receiver**. Only `Frame::Relay` is
eligible for chunking — every other frame is bounded by design and MUST
fit in a single Noise transport message.

### Chunk payload

```rust
struct RelayChunkPayload {
    request_id: u64,    // matches the eventual Frame::Relay.request_id
    seq: u32,           // 0-based chunk index
    total: u32,         // total chunks for this request_id
    data: Vec<u8>,      // raw bytes of the underlying serialized Frame::Relay
}
```

### Sender rules

1. Serialize the `Frame::Relay` to a postcard byte vector.
2. If it fits in `MAX_PLAINTEXT_FRAME_BYTES`, send it as one transport
   message. Otherwise:
3. Pick `total = ceil(len / MAX_PLAINTEXT_FRAME_BYTES)`.
4. For `seq` in `0..total`, emit a `Frame::RelayChunk` containing the
   matching slice. The serialized `RelayChunk` message MUST itself fit
   inside one Noise transport message — implementations rely on the fact
   that postcard's varint headers add only a few bytes per chunk.
5. Send chunks in order. Do **not** interleave chunks for different
   `request_id`s on the same connection (the receiver currently does not
   support interleaving — see "Versioning" below).

### Receiver rules

1. Maintain a per-`request_id` reassembly buffer.
2. Reject `seq != expected_seq` with `ErrorCode::ProtocolViolation`.
3. Reject `total != first_chunk.total` with `ErrorCode::ProtocolViolation`.
4. Cap the total reassembled byte count at the configured maximum
   (default ~4 MiB headroom over `max_message_size_bytes`). Overflow
   is `ErrorCode::MessageTooLarge`.
5. When `received == total`, decode the assembled bytes as a
   `Frame::Relay` and dispatch.

## 6. Connection lifecycle

```
sidecar                                    edge
   |                                         |
   |  TCP SYN → established                  |
   |---------------------------------------->|
   |                                         |
   |  Noise IK msg1 (carries sidecar's       |
   |  static pubkey, encrypted to edge)      |
   |---------------------------------------->|
   |                                         |
   |       Noise IK msg2 (transport ready)   |
   |<----------------------------------------|
   |                                         |
   |   * edge looks up sidecar pubkey in     |
   |     authorized_clients. Miss → send      |
   |     Frame::Error{Unauthorized}, close.   |
   |                                         |
   |  Frame::Hello{ proto_version, ... }     |
   |---------------------------------------->|
   |                                         |
   |    Frame::HelloAck{ proto_version, .. } |
   |<----------------------------------------|
   |                                         |
   |  Frame::Relay{ request_id, ... }        |
   |  (or chunked: RelayChunk * N)           |
   |---------------------------------------->|
   |                                         |
   |        ... edge resolves MX, delivers   |
   |                                         |
   |  Frame::RelayResult{ request_id, ... }  |
   |<----------------------------------------|
   |                                         |
   |  Frame::Ping{ts, nonce}      (optional) |
   |---------------------------------------->|
   |  Frame::Pong{ts, nonce}                 |
   |<----------------------------------------|
   |                                         |
   |  TCP FIN                                |
```

### Hello / HelloAck contract

The sidecar MUST send `Frame::Hello` as the **first** transport-mode
frame. The edge MUST respond with `Frame::HelloAck` before processing
any other frame. Both MUST contain `proto_version == PROTO_VERSION`.
A mismatch in either direction is `ErrorCode::ProtocolViolation` and
terminates the connection.

### Authorization

Authorization happens immediately after the Noise handshake completes
and **before** any application frame is processed. Sequence:

1. Edge calls `snow::HandshakeState::get_remote_static()` to get the
   initiator's 32-byte X25519 public key.
2. Edge looks the key up in its `authorized_clients` table (loaded from
   `/etc/mailcue-edge/authorized_clients` — see
   [`crates/proto/src/authorized.rs`](../crates/proto/src/authorized.rs)).
3. If absent: edge sends `Frame::Error{ code: Unauthorized,
   message: "..." }` and closes the TCP connection. The error is sent
   as a transport-mode message to ensure the initiator can decrypt it.
4. If present: edge proceeds to wait for `Frame::Hello`.

### Idle / keepalive

Either side MAY send `Frame::Ping` at any time post-`HelloAck`. The peer
MUST reply with `Frame::Pong` echoing the same `nonce`.

The reference sidecar pings every 30 seconds while a tunnel is otherwise
idle, and treats a missing `Pong` after `2 × keepalive_interval` as a
failed connection (close + reconnect with backoff). The edge does not
send unsolicited pings.

### Error semantics

`Frame::Error` is **fatal**. After sending or receiving it, both sides
MUST close the TCP connection. There is no in-band recovery — the
sidecar reconnects.

A graceful shutdown (e.g. SIGTERM on the edge during a deployment) is
signalled by the edge sending `Frame::Error { code: Internal,
message: "shutdown" }` and closing.

## 7. Versioning policy

- **Adding a new variant at the end of `Frame`** is a non-breaking change
  that does NOT require bumping `PROTO_VERSION`. Older peers will
  postcard-decode-fail and respond with `Frame::Error{ProtocolViolation}` —
  this is the documented forward-compat behaviour. Implementations MUST
  be prepared to receive `Error{ProtocolViolation}` after sending an
  unknown frame to an older peer and MUST NOT crash.
- **Adding optional fields to an existing variant** is a breaking change
  for postcard's positional encoding; this DOES require a
  `PROTO_VERSION` bump.
- **Renaming or reordering variants** is a breaking change requiring a
  `PROTO_VERSION` bump.
- **Removing a variant** is a breaking change requiring a `PROTO_VERSION`
  bump.
- A bumped `PROTO_VERSION` is enforced at the `Hello`/`HelloAck`
  exchange — peers refuse mismatched versions with
  `ErrorCode::ProtocolViolation`.

## 8. Reference implementation pointers

| Concept                | Source                                                                                       |
|------------------------|----------------------------------------------------------------------------------------------|
| Frame definitions      | [`crates/proto/src/frame.rs`](../crates/proto/src/frame.rs)                                  |
| Channel / chunking     | [`crates/proto/src/channel.rs`](../crates/proto/src/channel.rs)                              |
| Handshake driver       | [`crates/proto/src/handshake.rs`](../crates/proto/src/handshake.rs)                          |
| Static keypair format  | [`crates/proto/src/keypair.rs`](../crates/proto/src/keypair.rs)                              |
| Allow-list format      | [`crates/proto/src/authorized.rs`](../crates/proto/src/authorized.rs)                        |
