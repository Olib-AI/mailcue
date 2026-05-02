# MailCue out-of-band SMTP tunnel

Most cloud and PaaS providers (Hetzner, AWS, Google Cloud, fly.io, Render,
Railway, Vercel, ...) block outbound TCP/25, which is the only port public
MX servers accept mail on. The MailCue tunnel works around that by relaying
SMTP egress through a small VPS that **does** have port-25 access — an OVH
Eco / Kimsufi / Public Cloud instance is the canonical choice — and by
making it trivial to add more such VPSes for IP rotation and per-tenant
egress isolation.

This crate ships **two** binaries:

| Binary                    | Where it runs                       | Job |
|---------------------------|-------------------------------------|-----|
| `mailcue-relay-edge`      | The OVH (or equivalent) VPS         | Listens on a single TCP port (default `7843`), accepts authenticated tunnels from sidecars, and delivers their messages to public MX servers on port 25. |
| `mailcue-relay-sidecar`   | Next to the MailCue mail container  | Exposes a loopback SMTP submission endpoint (default `127.0.0.1:2525`) that Postfix relays through. Multiplexes outbound mail across one or more configured edges. |

Wire format and threat model are specified in [`docs/PROTOCOL.md`](docs/PROTOCOL.md)
and [`docs/SECURITY.md`](docs/SECURITY.md).

---

## Edge install (on the VPS)

The edge is a single static binary with no runtime dependencies beyond a
working DNS resolver. It's designed to drop into a fresh OVH Eco instance
running Debian 12 / Ubuntu 22.04+.

### 1. Run the installer

As `root` on the VPS:

```sh
curl -fsSL https://raw.githubusercontent.com/Olib-AI/mailcue/main/tunnel/deploy/install-edge.sh -o install-edge.sh
chmod +x install-edge.sh
./install-edge.sh
```

The installer is **idempotent** — re-running it will detect an existing
install and only refresh the binary + unit file. It:

- Detects the host architecture (`x86_64` or `aarch64`).
- Downloads the matching `mailcue-relay-edge` binary from the
  `tunnel-latest` GitHub release (override the source with
  `EDGE_RELEASE_URL=https://...`).
- Installs to `/usr/local/bin/mailcue-relay-edge` mode `0755`.
- Creates a dedicated system user `mailcue-edge` with no shell, no home.
- Creates `/var/lib/mailcue-edge` (mode `0700`, key + state) and
  `/etc/mailcue-edge` (mode `0750`, config + allow-list).
- Drops the hardened systemd unit at
  `/etc/systemd/system/mailcue-relay-edge.service`.
- Generates a fresh long-term keypair via `mailcue-relay-edge keygen`.
- Enables and starts the service.
- Prints the **server public key** — copy this. The Mailcue API needs it
  to bootstrap a sidecar.

Useful flags:

- `--listen-port <port>` — change the default `7843` listen port (the unit
  file is rewritten with the new port).
- `--uninstall` — stop the service, remove the binary and the unit file.
  **Leaves keys and config in place** so accidental re-runs cannot lose
  the long-term identity.

### 2. Open the firewall

The edge listens on TCP `7843` by default. Open it on UFW (or your
provider's firewall):

```sh
ufw allow 7843/tcp
```

OVH Public Cloud users: also add an inbound rule in the OVH dashboard if
you've enabled the platform-level network firewall.

### 3. Authorize a Mailcue sidecar

When a Mailcue admin asks to add this VPS as an egress, they generate a
**client key** on the Mailcue side (the `POST /api/v1/tunnels` endpoint
does this; see the API docs). Hand the resulting base64 public key to the
VPS operator. They then run:

```sh
sudo mailcue-relay-edge authorize --pubkey <base64-pubkey> --name mailcue-prod-de
```

This appends a line to `/etc/mailcue-edge/authorized_clients`. The edge
re-reads the file on every handshake — no restart required.

> **Heads-up (pre-`tunnel-v0.1.1` only):** older edge binaries wrote the
> allow-list as `root:root 0640`, which the unprivileged daemon
> (`mailcue-edge`) couldn't read, leading to `Unauthorized: pubkey not in
> allow-list` on every connection. From `tunnel-v0.1.1` onward the writer
> chowns the file to match its parent directory's owner automatically.
> If you're stuck on an older build, fix it manually:
>
> ```sh
> sudo chown root:mailcue-edge /etc/mailcue-edge/authorized_clients
> sudo chmod 0640 /etc/mailcue-edge/authorized_clients
> sudo systemctl restart mailcue-relay-edge
> ```

### 4. Verify it's running

```sh
systemctl status mailcue-relay-edge
journalctl -u mailcue-relay-edge -f
```

You should see one log line per accepted handshake and one per relay,
including the envelope sender, recipient count, and delivery outcome
(MX hostname + final SMTP code). **Message bodies are never logged** —
see [`docs/SECURITY.md`](docs/SECURITY.md) for why.

### 5. Set the EHLO hostname (required for outbound)

The edge presents a HELO/EHLO name on every outbound SMTP connection it
opens to a destination MX. If that name doesn't match the source IP's
forward-confirmed reverse DNS (FCrDNS), Gmail / Microsoft 365 / Yahoo
will reject with `550 5.7.26 unauthenticated`. By default the edge
uses `gethostname()`, which on a fresh OVH VPS is something like
`vps-ad9f0b95` — almost never what you want.

Set it via env var on the systemd unit:

```sh
sudo systemctl edit mailcue-relay-edge
```

Append (replace with the FQDN you set as rDNS for **this** VPS — see
"DNS prerequisites" below):

```ini
[Service]
Environment=MAILCUE_EDGE_HELO_HOSTNAME=relay-us.olib.email
```

Then `sudo systemctl restart mailcue-relay-edge`.

You can also set it in `/etc/mailcue-edge/config.toml`:

```toml
helo_hostname = "relay-us.olib.email"
```

---

## DNS prerequisites for outbound delivery

Outbound SMTP delivery — the whole point of this tunnel — is a DNS
problem first. To get past Gmail / M365 / Yahoo, every VPS that you
relay through needs **all five** of the following set up before it can
deliver mail. Skipping any one of them produces a 5xx rejection that
looks like a tunnel bug but isn't.

For each VPS hostname (e.g. `relay-us.olib.email`):

| # | Direction | What | Where set | Verify |
|---|---|---|---|---|
| 1 | **Forward (A)**: hostname → IPv4 | Your DNS provider | `dig +short A relay-us.olib.email` |
| 2 | **Forward (AAAA)**: hostname → IPv6 (if the VPS has IPv6 — most do) | Your DNS provider | `dig +short AAAA relay-us.olib.email` |
| 3 | **Reverse (PTR) v4**: IPv4 → hostname | OVH (or other VPS provider) manager | `dig +short -x 51.81.202.4` |
| 4 | **Reverse (PTR) v6**: IPv6 → hostname | OVH manager (separate row from v4!) | `dig +short -x 2604:2dc0:202:300::24de` |
| 5 | **SPF** for the apex domain (`olib.email`) covering both IP families of every relay | Your DNS provider | `dig +short TXT olib.email` |

Two recurring traps:

- **IPv4 PTR is set, IPv6 PTR is not.** OVH's manager has separate rows
  for the two address families. Most cloud images come with the IPv6
  rDNS unset or pointing at a generic `vps-…` domain. Gmail will use
  whichever family the VPS picks for the outbound connection (often v6
  if available) and reject if PTR doesn't match.
- **SPF is set on the relay hostname (`relay-us.olib.email`) but not
  on the apex (`olib.email`).** Gmail's SPF check runs against the
  envelope `MAIL FROM` domain. Real Mailcue traffic will use
  `From: user@olib.email`, so the apex must authorize *every* relay
  IP. Use the `a:` mechanism — it covers both A and AAAA records:

  ```text
  olib.email.   IN  TXT  "v=spf1 mx a:relay-us.olib.email a:relay-de.olib.email -all"
  ```

  This automatically authorizes all IPs of all named relay hosts; you
  don't need to enumerate `ip4:`/`ip6:` per address.

Once published, validate end-to-end against
[port25 verifier](http://www.port25.com/authentication-checker/) by
sending a message via the tunnel to `check-auth@verifier.port25.com` —
its auto-reply grades SPF, DKIM, DMARC, and FCrDNS as seen from your
relay's IP.

---

## Sidecar install (next to the Mailcue container)

The sidecar runs on the same Docker host as the MailCue container and
exposes a plain SMTP submission endpoint on the internal network. Postfix
inside the MailCue container is configured to relay through it via the
existing `MAILCUE_RELAY_HOST` / `MAILCUE_RELAY_PORT` env vars.

### 1. Bring it up

The repository ships a Compose overlay at
[`tunnel/deploy/docker/docker-compose.tunnel.yml`](deploy/docker/docker-compose.tunnel.yml).
Run:

```sh
docker compose \
  -f docker-compose.yml \
  -f tunnel/deploy/docker/docker-compose.tunnel.yml \
  up -d
```

This adds a `mailcue-sidecar` service to the same `mailcue-net` network as
the main MailCue container, and rewires Postfix's `relayhost` to
`mailcue-sidecar:2525`.

### 2. Provision tunnels

The sidecar reads its tunnel list from `/etc/mailcue-sidecar/tunnels.json`
inside the container (mounted as the `mailcue-sidecar-config` volume).
**You do not edit this file by hand** — the Mailcue API
(`/api/v1/tunnels`) writes it whenever an admin adds, removes, or rotates
an egress. Each entry contains:

- the edge host + port,
- the edge's expected static public key (provided by the VPS operator),
- the path to the local sidecar's private key (auto-generated on first
  boot if missing).

### 3. One-time bootstrap

On a fresh install, the sidecar will start with an empty `tunnels.json`
and refuse to relay (Postfix will queue locally — that's the safe default).
The bootstrap flow is:

1. `docker compose ... up -d` — sidecar generates `client.key` /
   `client.pub` in `/var/lib/mailcue-sidecar/`.
2. Mailcue admin reads `client.pub` (the API exposes it at
   `GET /api/v1/tunnels/client-pubkey`) and sends it to a VPS operator.
3. VPS operator runs `mailcue-relay-edge authorize --pubkey <base64>`.
4. Mailcue admin POSTs the edge's host + pubkey to `/api/v1/tunnels`. The
   API rewrites `tunnels.json`; the sidecar reloads it via inotify and
   the next outbound mail goes through.

Postfix's queue will drain automatically once a tunnel is up — there is
no need to restart the MailCue container.

---

## Key rotation

### Edge static key

Roll once a year, or immediately on suspected compromise:

```sh
# On the VPS, as root:
systemctl stop mailcue-relay-edge
mv /var/lib/mailcue-edge/server.key /var/lib/mailcue-edge/server.key.old
mv /var/lib/mailcue-edge/server.pub /var/lib/mailcue-edge/server.pub.old
mailcue-relay-edge keygen --state-dir /var/lib/mailcue-edge
systemctl start mailcue-relay-edge
cat /var/lib/mailcue-edge/server.pub
```

Hand the new pubkey to every Mailcue admin who relays through this VPS.
They update their tunnel record (`PATCH /api/v1/tunnels/{id}` with the new
`edge_pubkey`) — the sidecar will switch over on the next reconnect. Once
every consumer has switched, delete `server.key.old`.

### Sidecar client key

```sh
docker exec mailcue-sidecar mailcue-relay-sidecar keygen --rotate
docker exec mailcue-sidecar cat /var/lib/mailcue-sidecar/client.pub
```

Send the new pubkey to the VPS operator. They run
`mailcue-relay-edge authorize --pubkey <new-base64>` to add it, and
optionally `mailcue-relay-edge revoke --pubkey <old-base64>` once the
sidecar has finished switching over.

---

## Log locations

| Component | Path                                                    |
|-----------|---------------------------------------------------------|
| Edge      | journald (`journalctl -u mailcue-relay-edge`)           |
| Sidecar   | container stdout (`docker logs mailcue-sidecar`)        |
| Postfix   | inside the MailCue container at `/var/log/mail.log`     |

What's logged: handshake outcomes, per-relay envelope sender, recipient
count, message size, MX delivered to, final SMTP reply code, and
per-tunnel rate-limit / concurrency events.

What's **never** logged: message bodies, headers other than envelope
addresses, recipient addresses in error logs (only the count is logged
on rejection).

---

## Troubleshooting

### Handshake fails with `Unauthorized`

The sidecar's pubkey isn't in the edge's allow-list. On the VPS:

```sh
sudo cat /etc/mailcue-edge/authorized_clients
```

If the line is missing, run `mailcue-relay-edge authorize --pubkey ...`
with the pubkey from `GET /api/v1/tunnels/client-pubkey`.

### Sidecar reports `connection refused` to the edge

- Verify UFW: `sudo ufw status | grep 7843`.
- Verify the edge is listening: on the VPS, `ss -tnlp | grep 7843`.
- Verify your provider's network firewall (OVH dashboard, security groups,
  etc.) allows inbound TCP/7843.
- DNS for the edge host resolves to the right IP from the Mailcue host.

### MX delivery failed (`SMTP_DELIVERY_FAILED`)

The edge couldn't deliver to the recipient's MX. From `tunnel-v0.1.1`
onward each per-recipient outcome is logged at info level — you'll see
a line like:

```text
{"level":"INFO","fields":{"recipient":"user@gmail.com","smtp_code":"Some(550)","reason":"5.7.26 unauthenticated email...","message":"delivery perm-fail"}}
```

If you're on `tunnel-v0.1.0` you'll need to flip on debug logging:

```sh
sudo systemctl edit mailcue-relay-edge
# add:
# [Service]
# Environment=RUST_LOG=mailcue_relay_edge=debug
sudo systemctl restart mailcue-relay-edge
```

Common causes (read these in order):

- **`550 5.7.26 unauthenticated email ... SPF [...] = did not pass`**
  Your apex SPF doesn't authorize the IP that actually carried the
  outbound connection. Re-check that the SPF record covers *both*
  IPv4 and IPv6 of the relay (use the `a:` mechanism, see "DNS
  prerequisites" above). Then verify with `dig +short TXT olib.email`.
- **`550 5.7.1 ... does not meet IPv6 sending guidelines regarding
  PTR records`** — the IPv6 PTR for the source IP is missing or wrong.
  Set it in OVH manager (separate row from the IPv4 PTR), then re-test.
- **`550 5.7.26 ... DKIM = did not pass`** with SPF passing — the
  message has no DKIM signature. MailCue signs with OpenDKIM by default;
  if the message is going through the tunnel without being signed first,
  check that the upstream `mailcue` container has `mail._domainkey.<domain>`
  published in DNS.
- **HELO mismatch** (`550 5.7.0 EHLO host doesn't match ...`)
  The edge's EHLO hostname must match the source IP's FCrDNS. Set
  `MAILCUE_EDGE_HELO_HOSTNAME` per "Set the EHLO hostname" above.
- **Timeout**: the destination MX is dropping connections from your VPS
  IP (port-25 reputation / greylist). Try a different relay, or rotate
  the VPS IP if your provider allows it, or fall back to an established
  submission service for that recipient.
- **TLS handshake failed**: the destination MX has a broken cert chain.
  Set `require_tls = false` on that tunnel (default) — the edge will
  fall back to plaintext, matching standard MX policy.

To validate the path independently of the tunnel, run `swaks` *directly
from the VPS* to the destination MX. If swaks succeeds and the tunnel
fails, it's an EHLO / MAIL-FROM mismatch in the daemon config; if both
fail with the same error, it's a DNS / SPF / DKIM / blocklist issue.

```sh
swaks --to test@gmail.com \
      --from postmaster@<your-apex-domain> \
      --server gmail-smtp-in.l.google.com:25 \
      --helo <your-relay-hostname> \
      -tls-optional
```

### Postfix queue stuck

```sh
docker exec mailcue postqueue -p
```

If everything is `(deferred: connect to mailcue-sidecar[...]:2525: ...)`,
the sidecar isn't reachable — `docker compose ps` to confirm it's up.

If everything is `(deferred: relay temporarily unavailable)`, the sidecar
is up but has no working tunnel — check `docker logs mailcue-sidecar` for
handshake errors and confirm `tunnels.json` has at least one valid entry.

To force a flush after fixing the underlying issue:

```sh
docker exec mailcue postqueue -f
```

### Sidecar logs `no tunnels configured`

The Mailcue API hasn't written `tunnels.json` yet. Bootstrap a tunnel via
`POST /api/v1/tunnels` (see step 3 of the sidecar install above).

### `systemctl restart` hangs / SIGKILLs the daemon

```text
mailcue-relay-edge.service: State 'stop-sigterm' timed out. Killing.
```

Older builds (pre-`tunnel-v0.1.2`) used `idle_timeout_secs` (default
120s) as the SIGTERM drain budget. Sidecars hold long-lived tunnel
connections that don't close themselves on SIGTERM, so the drain always
ran the clock out and systemd escalated to SIGKILL. From `tunnel-v0.1.2`
the drain uses a separate, shorter `shutdown_drain_secs` (default 10s)
and `TimeoutStopSec` is back to 30s. Upgrade the VPS to pick up the new
unit file:

```sh
sudo EDGE_RELEASE_URL=https://github.com/Olib-AI/mailcue/releases/download/tunnel-latest \
  bash -c 'curl -fsSL https://raw.githubusercontent.com/Olib-AI/mailcue/main/tunnel/deploy/install-edge.sh | bash'
sudo systemctl daemon-reload
sudo systemctl restart mailcue-relay-edge
```

Override the drain via env if you need a longer/shorter window:

```ini
[Service]
Environment=MAILCUE_EDGE_SHUTDOWN_DRAIN_SECS=30
```

---

## Upgrading

The install script is idempotent — re-running it replaces the binary
and the systemd unit, preserving state (`/var/lib/mailcue-edge/server.key`,
`/etc/mailcue-edge/authorized_clients`, env-var drop-ins).

```sh
sudo EDGE_RELEASE_URL=https://github.com/Olib-AI/mailcue/releases/download/tunnel-v0.1.2 \
  bash -c 'curl -fsSL https://raw.githubusercontent.com/Olib-AI/mailcue/main/tunnel/deploy/install-edge.sh | bash'
sudo systemctl daemon-reload
sudo systemctl restart mailcue-relay-edge
sudo systemctl is-active mailcue-relay-edge
```

Pin to a tag (`tunnel-v0.1.2`, `tunnel-v0.1.1`, …) for reproducible
upgrades, or omit `EDGE_RELEASE_URL` to track `tunnel-latest`. Releases
attach a `SHA256SUMS` file you can verify before installing.

For the Docker sidecar, just bump the image tag in
`docker-compose.tunnel.yml` (`ghcr.io/olib-ai/mailcue-relay-sidecar:0.1.2`,
multi-arch) and `docker compose up -d`.
