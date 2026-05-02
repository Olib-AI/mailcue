# MailCue tunnel — threat model and security ops

This document is the security charter for `mailcue-relay-edge` and
`mailcue-relay-sidecar`. It is required reading for anyone running the
edge on shared infrastructure, anyone authorized to add a new sidecar
to an existing edge, and anyone reviewing changes to
[`tunnel/crates/proto/`](../crates/proto/).

The protocol-level details are specified separately in
[`PROTOCOL.md`](PROTOCOL.md). This document focuses on **why** the
protocol looks the way it does and **how** to operate it safely.

## 1. Threat model

### In scope

The tunnel is designed to defend against:

- **Passive eavesdropping** anywhere on the path between sidecar and
  edge (transit ISPs, hostile WiFi, BGP-hijack on-path attackers). All
  application data — message bodies, envelope addresses, recipient
  lists — is encrypted under a fresh per-session key derived via Noise
  IK (forward secret).
- **Tunnel impersonation**, in either direction:
  - A man-in-the-middle posing as the edge to harvest mail. Defeated
    because the sidecar pins the edge's static X25519 public key
    out-of-band (provisioned via the Mailcue API). An attacker cannot
    complete the IK handshake without the edge's matching static
    private key.
  - A stranger posing as a legitimate sidecar to abuse a VPS for spam.
    Defeated because the edge enforces an explicit allow-list of
    sidecar pubkeys; a non-allowlisted pubkey is rejected with
    `Error{Unauthorized}` immediately after the handshake and before
    any `Relay` frame is processed.
- **Replay** of captured tunnel traffic. Defeated by Noise's per-session
  ephemeral keys and ratcheted nonces — replayed transport messages fail
  AEAD verification.
- **Key compromise impact (forward secrecy)**. If a sidecar or edge
  static private key is later stolen, prior session traffic recorded by
  a passive attacker remains undecryptable. This is the classical
  forward-secrecy property of IK; ephemerals are mixed into the chaining
  key during the handshake.
- **Key compromise impact (KCI resistance)**. If the edge's static key
  is compromised, the attacker still cannot impersonate **a specific
  sidecar** to the legitimate edge. Noise IK resists key-compromise
  impersonation because the initiator's static key is part of the
  authentication, not just the responder's. See
  [Noise spec §7.7](https://noiseprotocol.org/noise.html#payload-security-properties).
- **DoS-by-relay-abuse**. A legitimate-but-misbehaving sidecar (a
  hijacked Mailcue instance) cannot spray unlimited mail through the
  edge: per-client concurrency limit (`per_client_concurrency`),
  message-size cap (`max_message_size_bytes`), recipient cap
  (`max_recipients_per_request`), and SMTP I/O timeouts bound the
  blast radius.
- **Cleartext crypto downgrade**. The protocol does not negotiate cipher
  suites — `Noise_IK_25519_ChaChaPoly_BLAKE2s` is hardcoded. There is
  nothing to downgrade.

### Out of scope

The tunnel does **not** defend against:

- **Compromise of the VPS itself.** If an attacker has root on the OVH
  box, they can read live mail in transit (post-decryption, pre-MX). The
  systemd unit hardens against generic LPE / lateral movement (see §3),
  but a kernel exploit or VPS-host compromise is game over. Choose VPS
  providers accordingly.
- **Compromise of the destination MX.** Once the edge hands the message
  to the recipient's MX, the tunnel's job is done. End-to-end mail
  encryption (S/MIME, PGP, MTA-STS / DANE) is the operator's
  responsibility.
- **Traffic-flow analysis.** An on-path observer can see that a sidecar
  is talking to an edge, can see message timing, and can estimate
  message size from the AEAD ciphertext length (Noise does not pad).
  Volume / timing inference (e.g. "this customer just sent a 12 MB
  attachment") is not defended against. If you need padding, that's a
  protocol extension at a future `PROTO_VERSION`.
- **Compromise of the Mailcue API or its DB.** Whoever holds the
  Mailcue admin token can issue new sidecar keys and add tunnels;
  protect those credentials with the same care as any production
  database.
- **Spam content classification.** The edge enforces *rate* and *size*
  but does not parse or score messages. If a sidecar's owner uses it to
  send spam, the edge is the path of egress and its IPs are what gets
  blocklisted. See §4 for the abuse handling protocol.

## 2. Why Noise IK?

Noise IK gives us, in one round trip, every property we need:

- **Mutual authentication.** Both sides authenticate via static
  X25519 keys; no certificates, no PKI, no CRL plumbing.
- **Forward secrecy.** Ephemeral keys are mixed into the chaining key
  during the handshake; long-term key compromise does not retroactively
  decrypt past sessions.
- **KCI resistance.** Stealing one side's static key does not let an
  attacker impersonate the *other* side to it.
- **No identity exposure of the responder.** The initiator must already
  know the responder's static public key — the edge's pubkey is not
  exposed in cleartext.
- **Small, well-vetted implementation surface.** WireGuard uses the same
  cipher suite (`Noise_IK_25519_ChaChaPoly_BLAKE2s`) and has had years
  of public scrutiny. We use the [`snow`](https://crates.io/crates/snow)
  crate which is the canonical Rust Noise implementation.

We deliberately did **not** choose:

- **TLS 1.3.** Equivalent crypto, but: (a) X.509 + a private CA / Let's
  Encrypt for every VPS adds operational toil for what is fundamentally
  a 1:N peer-to-peer trust topology, not a name-based trust topology;
  (b) the standard server-auth + client-cert mode does not have the
  same KCI properties out of the box; (c) requires careful cipher-suite
  pinning to avoid downgrade.
- **WireGuard / IPSec.** Tunnels traffic at a layer below SMTP, which
  means leaks (e.g. an envoy mistakenly bypassing the tunnel) become
  silent failures. SMTP-aware framing lets the edge enforce
  per-recipient policy and report per-recipient outcomes.

References:
- Noise Protocol Framework rev 34: https://noiseprotocol.org/noise.html
- Noise Explorer IK formal analysis: https://noiseexplorer.com/patterns/IK/
- WireGuard whitepaper §3: https://www.wireguard.com/papers/wireguard.pdf

## 3. Edge runtime hardening

The systemd unit at
[`tunnel/deploy/systemd/mailcue-relay-edge.service`](../deploy/systemd/mailcue-relay-edge.service)
applies the following defence-in-depth layers. Do not relax any of these
without a documented reason.

| Directive                     | Effect |
|-------------------------------|--------|
| `User=mailcue-edge`           | Dedicated unprivileged user, no shell, no home. |
| `CapabilityBoundingSet=`, `AmbientCapabilities=` | All Linux capabilities dropped — daemon cannot bind to <1024, modify routing, etc. |
| `NoNewPrivileges=yes`         | `setuid` / `file caps` cannot regain privilege. |
| `ProtectSystem=strict`        | `/usr`, `/boot`, `/etc` are read-only. |
| `ReadWritePaths=...`          | Only `/var/lib/mailcue-edge` and `/etc/mailcue-edge` are writable. |
| `ProtectHome=yes`             | Home dirs invisible to the daemon. |
| `PrivateTmp=yes`              | Per-unit `/tmp`, wiped on stop. |
| `PrivateDevices=yes`          | No device nodes besides `/dev/null`, `/dev/zero`, etc. |
| `ProtectKernelTunables=yes`   | `/proc/sys`, `/sys` read-only. |
| `ProtectKernelModules=yes`    | Daemon cannot load modules. |
| `ProtectKernelLogs=yes`       | No `dmesg`. |
| `RestrictAddressFamilies=AF_INET AF_INET6` | No `AF_UNIX`, `AF_NETLINK`, `AF_PACKET`. |
| `RestrictNamespaces=yes`      | No clone-namespace tricks. |
| `MemoryDenyWriteExecute=yes`  | W^X — no JIT codegen surface (we have none anyway). |
| `SystemCallFilter=@system-service ~@privileged ~@resources` | Seccomp filter denying ptrace, mount, set_mempolicy, swapon, ... |

The Rust code at the application layer adds:

- `#![deny(unsafe_code)]` at the proto crate root — there is no `unsafe`
  in the protocol implementation. The edge crate has no unsafe blocks.
- Explicit bounds checking on every length field read off the wire,
  before allocation. `MAX_HANDSHAKE_MSG = 1024`,
  `MAX_CIPHERTEXT_FRAME_BYTES = 65535`,
  `MAX_PLAINTEXT_FRAME_BYTES = 60 KiB`,
  reassembly cap configurable.
- Static keys held in `Zeroize`d buffers; the buffer is wiped from
  memory on drop.

## 4. Logging and what gets recorded

The edge logs, per relay request:

- Authenticated client pubkey (truncated hex prefix) and friendly name
  from `authorized_clients`.
- `request_id`.
- `envelope_from` (envelope sender).
- Recipient **count** (the recipient list itself is logged at debug
  level only).
- Message size in bytes.
- MX hostname the message was delivered to.
- Final SMTP reply code.
- Per-recipient `Delivered | TempFail | PermFail` outcome class.

The edge **never** logs:

- Message bodies.
- Message headers other than envelope addresses.
- Recipient addresses at info level (count only).

This is deliberate. The VPS operator is part of the trust boundary by
necessity (they can read traffic if they're root), but the daemon's own
logs are commonly shipped to centralised log aggregators (journald
forwarding, Loki, Datadog) where they widen the trust boundary
unnecessarily. Keeping the recipient list and the body out of `info`
logs limits exposure to operators with `journalctl` access on the VPS
and to anyone who later compromises the log pipeline.

If you're investigating an abuse incident and need recipients, raise
the daemon's log level to `debug` for the duration of the
investigation, then drop it back to `info`:

```sh
systemctl set-environment MAILCUE_EDGE_LOG_LEVEL=debug
systemctl restart mailcue-relay-edge
# ...
systemctl unset-environment MAILCUE_EDGE_LOG_LEVEL
systemctl restart mailcue-relay-edge
```

## 5. Key rotation

### Edge static key

Rotate at least annually, immediately on suspected compromise, and
whenever a system administrator with `sudo` access on the VPS leaves
the team.

```sh
# On the VPS, as root.
systemctl stop mailcue-relay-edge
mv /var/lib/mailcue-edge/server.key /var/lib/mailcue-edge/server.key.old
mv /var/lib/mailcue-edge/server.pub /var/lib/mailcue-edge/server.pub.old
sudo -u mailcue-edge mailcue-relay-edge keygen --state-dir /var/lib/mailcue-edge
systemctl start mailcue-relay-edge
cat /var/lib/mailcue-edge/server.pub
```

Distribute the new pubkey to every Mailcue tenant relaying through this
edge. They update their tunnel record (`PATCH /api/v1/tunnels/{id}`
with the new `edge_pubkey`); the sidecar reloads
`tunnels.json` via inotify and reconnects with the new pin. Once every
consumer is on the new key — confirmed by `journalctl -u
mailcue-relay-edge | grep handshake` showing zero handshake failures
for ~24h — `shred -u /var/lib/mailcue-edge/server.key.old`.

### Sidecar client key

Rotate annually, on suspected compromise, or before
decommissioning a Mailcue install.

```sh
docker exec mailcue-sidecar mailcue-relay-sidecar keygen --rotate
docker exec mailcue-sidecar cat /var/lib/mailcue-sidecar/client.pub
```

`--rotate` writes the new key to `client.key.new`, swaps it in
atomically, and keeps `client.key.old` for one tunnel-reload cycle so
in-flight relays can drain. The sidecar's main loop re-handshakes every
existing tunnel using the new key.

Then, on every edge that authorized this sidecar:

```sh
mailcue-relay-edge authorize --pubkey <new-base64> --name <same-as-before>
mailcue-relay-edge revoke   --pubkey <old-base64>
```

The order matters — `authorize` first, then `revoke` — so there is no
window where the sidecar is rejected.

## 6. Abuse handling for VPS operators

You are running a tunnel that lets one or more Mailcue installs send
mail through your IP. Your IP's reputation is at stake. The edge is
designed to support the standard abuse-response toolkit.

### Per-client metrics

The edge logs `client_id` (free-form, supplied in `Frame::Hello`) and a
hex prefix of the authenticated pubkey on every relay. Filter by client:

```sh
journalctl -u mailcue-relay-edge | grep 'client=mailcue-prod-de'
```

If one client is producing the bulk of the volume, that's where to
focus.

### Rate and concurrency limits

Adjust in `/etc/mailcue-edge/config.toml`:

```toml
per_client_concurrency = 8       # max parallel Relay frames per tunnel
max_message_size_bytes = 52428800 # 50 MiB
max_recipients_per_request = 100
```

Restart with `systemctl restart mailcue-relay-edge`. Lowering
`per_client_concurrency` to `1` is the fastest way to throttle a noisy
client without revoking it.

### Revoking a client

```sh
mailcue-relay-edge revoke --pubkey <base64>
```

This rewrites `/etc/mailcue-edge/authorized_clients` with the line
removed. Any in-flight tunnels for that pubkey continue until they
disconnect; subsequent reconnect attempts will be rejected with
`Frame::Error{Unauthorized}` and closed. To kick existing connections
immediately, follow up with `systemctl restart mailcue-relay-edge`.

### What to do if a Mailcue install is sending spam

1. **Identify the offender.** Cross-reference the abuse complaint's
   spam-sample headers (`Received:` chain) with edge logs to find the
   `client_id` / pubkey. The MX-side rejection (`Delivered` with a
   high SMTP code, or a `PermFail` from a blocklist response) is also
   logged.
2. **Throttle first.** Drop `per_client_concurrency` to `1` for an
   immediate impact while you investigate.
3. **Revoke if confirmed.** Run `mailcue-relay-edge revoke` and
   `systemctl restart mailcue-relay-edge`. Notify the Mailcue admin —
   their pubkey is in your logs but it's their install you're dealing
   with.
4. **Preserve evidence.** Save the relevant `journalctl` window
   (`journalctl -u mailcue-relay-edge --since '...' --until '...' >
   abuse-{timestamp}.log`) before your retention policy purges it.
5. **Repair IP reputation.** If your VPS IP got listed
   (Spamhaus / SORBS / etc.), file delisting requests. Consider
   rotating to a fresh IP via your provider's console — the edge
   re-binds on restart, no key change needed.
