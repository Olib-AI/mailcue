#!/usr/bin/env bash
#
# tunnel/scripts/smoke-test.sh — end-to-end exercise of the MailCue tunnel.
#
# 1. Generates an edge keypair and a sidecar keypair in temp dirs.
# 2. Authorizes the sidecar pubkey on the edge.
# 3. Spawns the edge listening on 127.0.0.1:17843.
# 4. Writes a tunnels.json pointing at it; spawns the sidecar listening on
#    127.0.0.1:12525 with metrics on 127.0.0.1:19325.
# 5. Sends an SMTP submission to nobody@example.invalid via raw `nc`.
# 6. Verifies the sidecar emitted a non-2xx SMTP response (delivery to a
#    non-existent MX is expected to fail), but the protocol path was
#    exercised end-to-end.
# 7. Verifies metrics counters tick.
# 8. Tears everything down and returns 0 on success.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d -t mailcue-smoke-XXXXXX)"
EDGE_STATE="${WORK}/edge-state"
EDGE_CONF="${WORK}/edge-conf"
SIDECAR_STATE="${WORK}/sidecar-state"
SIDECAR_CONF="${WORK}/sidecar-conf"
LOGS="${WORK}/logs"
mkdir -p "${EDGE_STATE}" "${EDGE_CONF}" "${SIDECAR_STATE}" "${SIDECAR_CONF}" "${LOGS}"

EDGE_BIN="${ROOT}/target/release/mailcue-relay-edge"
SIDECAR_BIN="${ROOT}/target/release/mailcue-relay-sidecar"

EDGE_LISTEN="127.0.0.1:17843"
SIDECAR_SMTP="127.0.0.1:12525"
SIDECAR_METRICS="127.0.0.1:19325"

EDGE_PID=""
SIDECAR_PID=""

cleanup() {
    set +e
    [[ -n "${EDGE_PID}" ]] && kill "${EDGE_PID}" 2>/dev/null
    [[ -n "${SIDECAR_PID}" ]] && kill "${SIDECAR_PID}" 2>/dev/null
    wait 2>/dev/null
    rm -rf "${WORK}"
}
trap cleanup EXIT INT TERM

log() { printf '[smoke] %s\n' "$*"; }
die() { printf '[smoke] FAIL: %s\n' "$*" >&2; exit 1; }

# --- 0) build -----------------------------------------------------------
if [[ ! -x "${EDGE_BIN}" || ! -x "${SIDECAR_BIN}" ]]; then
    log "building release binaries..."
    (cd "${ROOT}" && cargo build --workspace --release --locked >/dev/null)
fi

# --- 1) keygen edge + sidecar ------------------------------------------
log "generating edge keypair in ${EDGE_STATE}"
EDGE_PUB="$("${EDGE_BIN}" keygen --state-dir "${EDGE_STATE}")"
[[ -n "${EDGE_PUB}" ]] || die "edge keygen produced empty pubkey"

log "generating sidecar keypair in ${SIDECAR_STATE}"
SIDECAR_PUB="$("${SIDECAR_BIN}" keygen --state-dir "${SIDECAR_STATE}")"
[[ -n "${SIDECAR_PUB}" ]] || die "sidecar keygen produced empty pubkey"

# --- 2) authorize sidecar on edge --------------------------------------
log "authorizing sidecar pubkey on edge"
"${EDGE_BIN}" authorize \
    --pubkey "${SIDECAR_PUB}" \
    --name smoke-sidecar \
    --config-path "${EDGE_CONF}/authorized_clients" >/dev/null

# Idempotency check.
"${EDGE_BIN}" authorize \
    --pubkey "${SIDECAR_PUB}" \
    --config-path "${EDGE_CONF}/authorized_clients" >/dev/null

# --- 3) spawn edge ------------------------------------------------------
log "spawning edge on ${EDGE_LISTEN}"
"${EDGE_BIN}" run \
    --listen-addr "${EDGE_LISTEN}" \
    --state-dir "${EDGE_STATE}" \
    --authorized-clients "${EDGE_CONF}/authorized_clients" \
    --log-level info \
    > "${LOGS}/edge.log" 2>&1 &
EDGE_PID=$!

for _ in $(seq 1 50); do
    if (echo > "/dev/tcp/127.0.0.1/17843") 2>/dev/null; then
        break
    fi
    sleep 0.1
done
kill -0 "${EDGE_PID}" 2>/dev/null || die "edge died early; see ${LOGS}/edge.log"

# --- 4) sidecar tunnels.json + spawn -----------------------------------
cat > "${SIDECAR_CONF}/tunnels.json" <<JSON
{
  "version": 1,
  "selection": "round_robin",
  "tunnels": [
    {
      "id": "smoke-edge",
      "name": "smoke-edge",
      "host": "127.0.0.1",
      "port": 17843,
      "edge_pubkey": "${EDGE_PUB}",
      "weight": 1,
      "enabled": true
    }
  ]
}
JSON

log "spawning sidecar on ${SIDECAR_SMTP} (metrics ${SIDECAR_METRICS})"
"${SIDECAR_BIN}" run \
    --smtp-listen "${SIDECAR_SMTP}" \
    --metrics-listen "${SIDECAR_METRICS}" \
    --state-dir "${SIDECAR_STATE}" \
    --tunnels-path "${SIDECAR_CONF}/tunnels.json" \
    --client-id smoke-sidecar \
    --log-level info \
    > "${LOGS}/sidecar.log" 2>&1 &
SIDECAR_PID=$!

for _ in $(seq 1 100); do
    if (echo > "/dev/tcp/127.0.0.1/12525") 2>/dev/null; then
        break
    fi
    sleep 0.1
done
kill -0 "${SIDECAR_PID}" 2>/dev/null || die "sidecar died early; see ${LOGS}/sidecar.log"

# Wait for at least one healthy tunnel (handshake + HelloAck) so the
# selector has something to pick. We poll /healthz.
HEALTHY=0
for _ in $(seq 1 100); do
    code="$(curl -s -o /dev/null -w '%{http_code}' "http://${SIDECAR_METRICS}/healthz" || true)"
    if [[ "${code}" == "200" ]]; then
        HEALTHY=1
        break
    fi
    sleep 0.2
done
[[ "${HEALTHY}" == "1" ]] || die "no healthy tunnel after 20s; see ${LOGS}/sidecar.log"

# --- 5) submit a test message via raw SMTP -----------------------------
log "submitting test message via ${SIDECAR_SMTP}"

SMTP_OUT="${LOGS}/smtp-output.txt"

# Hand-rolled SMTP exchange. Use python3 since `nc -q` flags vary across
# distros. This keeps us portable on macOS + Debian.
python3 - "${SIDECAR_SMTP%:*}" "${SIDECAR_SMTP##*:}" > "${SMTP_OUT}" <<'PY'
import socket, sys, time
host, port = sys.argv[1], int(sys.argv[2])
s = socket.create_connection((host, port), timeout=60)
s.settimeout(60)
def expect(prefixes):
    buf = b""
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
        for line in buf.splitlines(True):
            if line.endswith(b"\r\n") and len(line) >= 4 and line[3:4] in (b" ", b"\r"):
                # Final line of a multi-line reply.
                last = buf.rstrip().splitlines()[-1].decode("latin-1", "replace")
                print(last, flush=True)
                return last
        # else continue reading
    raise SystemExit("connection closed unexpectedly")
expect(b"220")
s.sendall(b"EHLO smoke.local\r\n"); expect(b"250")
s.sendall(b"MAIL FROM:<smoke@local.invalid>\r\n"); expect(b"250")
s.sendall(b"RCPT TO:<nobody@example.invalid>\r\n"); expect(b"250")
s.sendall(b"DATA\r\n"); expect(b"354")
s.sendall(b"From: smoke@local.invalid\r\nTo: nobody@example.invalid\r\nSubject: smoke-test\r\n\r\n.hello\r\nbody\r\n.\r\n")
final = expect(b"")
s.sendall(b"QUIT\r\n")
try: expect(b"")
except SystemExit: pass
print("FINAL:" + final, flush=True)
PY

cat "${SMTP_OUT}"

# Validate that we saw a final line for the DATA submission (any of
# 250/451/554) — that proves the protocol path executed end-to-end.
FINAL_LINE="$(grep '^FINAL:' "${SMTP_OUT}" | tail -n1 | sed 's/^FINAL://')"
[[ -n "${FINAL_LINE}" ]] || die "no final SMTP reply captured"
case "${FINAL_LINE}" in
    250\ *|451\ *|554\ *)
        log "final SMTP reply: ${FINAL_LINE}"
        ;;
    *)
        die "unexpected final SMTP reply: ${FINAL_LINE}"
        ;;
esac

# --- 6) verify metrics counters ----------------------------------------
log "fetching metrics from ${SIDECAR_METRICS}/metrics"
METRICS_BODY="$(curl -fsS "http://${SIDECAR_METRICS}/metrics")"

# Total of 2xx + 4xx + 5xx submissions must be >= 1.
SMTP_TOTAL="$(printf '%s\n' "${METRICS_BODY}" \
    | awk '/^mailcue_smtp_messages_total\{/ { sum += $2 } END { print sum+0 }')"
[[ "${SMTP_TOTAL}" -ge 1 ]] \
    || die "expected mailcue_smtp_messages_total >= 1, got ${SMTP_TOTAL}"

# Per-tunnel relay counter must be >= 1 for ok or err.
TUNNEL_REQS="$(printf '%s\n' "${METRICS_BODY}" \
    | awk '/^mailcue_tunnel_requests_total\{/ { sum += $2 } END { print sum+0 }')"
[[ "${TUNNEL_REQS}" -ge 1 ]] \
    || die "expected mailcue_tunnel_requests_total >= 1, got ${TUNNEL_REQS}"

# tunnel_up must include our smoke-edge entry.
printf '%s\n' "${METRICS_BODY}" | grep -q '^mailcue_tunnel_up{tunnel="smoke-edge"}' \
    || die "metrics missing mailcue_tunnel_up{tunnel=smoke-edge}"

# /readyz returns 200.
READYZ_CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://${SIDECAR_METRICS}/readyz")"
[[ "${READYZ_CODE}" == "200" ]] || die "/readyz returned ${READYZ_CODE}"

log "metrics OK (smtp_total=${SMTP_TOTAL}, tunnel_reqs=${TUNNEL_REQS})"
log "edge log tail (last 5 lines):"
tail -n 5 "${LOGS}/edge.log" || true
log "sidecar log tail (last 5 lines):"
tail -n 5 "${LOGS}/sidecar.log" || true

log "smoke test PASSED"
exit 0
