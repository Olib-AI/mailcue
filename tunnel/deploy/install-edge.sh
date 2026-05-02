#!/bin/sh
# install-edge.sh — install or uninstall the MailCue tunnel edge daemon.
#
# Idempotent. Re-running refreshes the binary and unit file but never
# touches the long-term key material in /var/lib/mailcue-edge.
#
# Flags:
#   --listen-port <port>    Override the default TCP listen port (7843).
#   --uninstall             Stop + disable the service, remove the binary
#                           and the systemd unit. KEY MATERIAL IS LEFT
#                           IN PLACE — re-run install-edge.sh to redeploy
#                           against the same identity.
#
# Environment:
#   EDGE_RELEASE_URL        Base URL of the release. Default:
#                           https://github.com/Olib-AI/mailcue/releases/download/tunnel-latest

set -euo pipefail

PROG="$(basename "$0")"

log() { printf '[%s] %s\n' "${PROG}" "$*" >&2; }
die() { log "error: $*"; exit 1; }

# ----------------------------------------------------------------------
# Parse arguments.
# ----------------------------------------------------------------------
ACTION="install"
LISTEN_PORT="7843"

while [ "$#" -gt 0 ]; do
    case "$1" in
        --uninstall)
            ACTION="uninstall"
            shift
            ;;
        --listen-port)
            [ "$#" -ge 2 ] || die "--listen-port requires a value"
            LISTEN_PORT="$2"
            case "${LISTEN_PORT}" in
                ''|*[!0-9]*) die "invalid --listen-port: ${LISTEN_PORT}" ;;
            esac
            [ "${LISTEN_PORT}" -ge 1 ] && [ "${LISTEN_PORT}" -le 65535 ] \
                || die "--listen-port out of range: ${LISTEN_PORT}"
            shift 2
            ;;
        --listen-port=*)
            LISTEN_PORT="${1#--listen-port=}"
            shift
            ;;
        --help|-h)
            sed -n '2,30p' "$0"
            exit 0
            ;;
        *)
            die "unknown argument: $1 (try --help)"
            ;;
    esac
done

# ----------------------------------------------------------------------
# Pre-flight.
# ----------------------------------------------------------------------
[ "$(id -u)" -eq 0 ] || die "must be run as root"

USER_NAME="mailcue-edge"
GROUP_NAME="mailcue-edge"
BIN_PATH="/usr/local/bin/mailcue-relay-edge"
STATE_DIR="/var/lib/mailcue-edge"
CONFIG_DIR="/etc/mailcue-edge"
UNIT_PATH="/etc/systemd/system/mailcue-relay-edge.service"
RELEASE_URL="${EDGE_RELEASE_URL:-https://github.com/Olib-AI/mailcue/releases/download/tunnel-latest}"

# ----------------------------------------------------------------------
# Uninstall path.
# ----------------------------------------------------------------------
if [ "${ACTION}" = "uninstall" ]; then
    log "stopping mailcue-relay-edge..."
    if command -v systemctl >/dev/null 2>&1; then
        systemctl stop mailcue-relay-edge.service 2>/dev/null || true
        systemctl disable mailcue-relay-edge.service 2>/dev/null || true
    fi
    if [ -f "${UNIT_PATH}" ]; then
        rm -f "${UNIT_PATH}"
        log "removed ${UNIT_PATH}"
    fi
    if command -v systemctl >/dev/null 2>&1; then
        systemctl daemon-reload
    fi
    if [ -f "${BIN_PATH}" ]; then
        rm -f "${BIN_PATH}"
        log "removed ${BIN_PATH}"
    fi
    log "uninstall complete."
    log "note: ${STATE_DIR} and ${CONFIG_DIR} were preserved."
    log "      remove them by hand if you really want to discard the identity."
    exit 0
fi

# ----------------------------------------------------------------------
# Detect arch.
# ----------------------------------------------------------------------
UNAME_M="$(uname -m)"
case "${UNAME_M}" in
    x86_64|amd64)   ARCH="x86_64"  ;;
    aarch64|arm64)  ARCH="aarch64" ;;
    *) die "unsupported architecture: ${UNAME_M}" ;;
esac
log "host arch: ${ARCH}"

# ----------------------------------------------------------------------
# Pick a downloader.
# ----------------------------------------------------------------------
if command -v curl >/dev/null 2>&1; then
    DL='curl -fsSL --retry 3 --retry-delay 2 -o'
elif command -v wget >/dev/null 2>&1; then
    DL='wget -q -O'
else
    die "neither curl nor wget is available; install one and re-run"
fi

# ----------------------------------------------------------------------
# Download binary.
# ----------------------------------------------------------------------
ASSET="mailcue-relay-edge-${ARCH}-unknown-linux-musl"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

log "downloading ${RELEASE_URL}/${ASSET}..."
${DL} "${TMP}/edge" "${RELEASE_URL}/${ASSET}" \
    || die "failed to download binary from ${RELEASE_URL}/${ASSET}"

# Best-effort SHA256 verification.
if ${DL} "${TMP}/SHA256SUMS" "${RELEASE_URL}/SHA256SUMS" 2>/dev/null; then
    if command -v sha256sum >/dev/null 2>&1; then
        EXPECTED="$(grep "${ASSET}" "${TMP}/SHA256SUMS" | awk '{print $1}' | head -n1 || true)"
        if [ -n "${EXPECTED}" ]; then
            ACTUAL="$(sha256sum "${TMP}/edge" | awk '{print $1}')"
            if [ "${EXPECTED}" = "${ACTUAL}" ]; then
                log "sha256 verified."
            else
                die "sha256 mismatch: expected ${EXPECTED}, got ${ACTUAL}"
            fi
        else
            log "warning: SHA256SUMS does not list ${ASSET}; skipping verification."
        fi
    else
        log "warning: sha256sum not installed; skipping verification."
    fi
else
    log "warning: SHA256SUMS not published yet; skipping verification."
fi

chmod 0755 "${TMP}/edge"

# ----------------------------------------------------------------------
# User + dirs.
# ----------------------------------------------------------------------
if ! getent group "${GROUP_NAME}" >/dev/null 2>&1; then
    groupadd --system "${GROUP_NAME}"
    log "created group ${GROUP_NAME}"
fi

if ! id -u "${USER_NAME}" >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin \
        --gid "${GROUP_NAME}" "${USER_NAME}"
    log "created user ${USER_NAME}"
fi

mkdir -p "${STATE_DIR}" "${CONFIG_DIR}"
chown "${USER_NAME}:${GROUP_NAME}" "${STATE_DIR}" "${CONFIG_DIR}"
chmod 0700 "${STATE_DIR}"
chmod 0750 "${CONFIG_DIR}"

# ----------------------------------------------------------------------
# Install binary.
# ----------------------------------------------------------------------
install -m 0755 -o root -g root "${TMP}/edge" "${BIN_PATH}"
log "installed ${BIN_PATH}"

# ----------------------------------------------------------------------
# Install systemd unit.
# ----------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" >/dev/null 2>&1 && pwd)"
UNIT_SRC="${SCRIPT_DIR}/systemd/mailcue-relay-edge.service"

if [ -f "${UNIT_SRC}" ]; then
    install -m 0644 -o root -g root "${UNIT_SRC}" "${UNIT_PATH}"
else
    # Fall back to fetching the unit from the release URL — useful when
    # the install script was piped from curl without the rest of the
    # repo on disk.
    log "unit not found locally; downloading from ${RELEASE_URL}/mailcue-relay-edge.service"
    ${DL} "${UNIT_PATH}" "${RELEASE_URL}/mailcue-relay-edge.service" \
        || die "failed to download systemd unit"
    chmod 0644 "${UNIT_PATH}"
    chown root:root "${UNIT_PATH}"
fi

# Apply --listen-port if non-default. We overwrite the ExecStart line
# rather than relying on env files so the change survives systemctl
# daemon-reload without operator action.
if [ "${LISTEN_PORT}" != "7843" ]; then
    log "patching unit to listen on port ${LISTEN_PORT}"
    # Use a `Environment=MAILCUE_EDGE_LISTEN_ADDR=...` directive so the
    # daemon picks it up via its standard env-var precedence chain.
    if grep -q '^Environment=MAILCUE_EDGE_LISTEN_ADDR=' "${UNIT_PATH}"; then
        sed -i.bak "s|^Environment=MAILCUE_EDGE_LISTEN_ADDR=.*|Environment=MAILCUE_EDGE_LISTEN_ADDR=0.0.0.0:${LISTEN_PORT}|" "${UNIT_PATH}"
    else
        # Insert the env var just before ExecStart.
        sed -i.bak "/^ExecStart=/i Environment=MAILCUE_EDGE_LISTEN_ADDR=0.0.0.0:${LISTEN_PORT}" "${UNIT_PATH}"
    fi
    rm -f "${UNIT_PATH}.bak"
fi

# ----------------------------------------------------------------------
# Generate keypair if missing.
# ----------------------------------------------------------------------
if [ ! -f "${STATE_DIR}/server.key" ]; then
    log "generating long-term keypair..."
    su -s /bin/sh -c "${BIN_PATH} keygen --state-dir ${STATE_DIR}" "${USER_NAME}" \
        || die "keygen failed"
else
    log "existing keypair detected at ${STATE_DIR}/server.key — keeping it."
fi

# ----------------------------------------------------------------------
# Reload systemd, enable, start.
# ----------------------------------------------------------------------
systemctl daemon-reload
systemctl enable mailcue-relay-edge.service
systemctl restart mailcue-relay-edge.service
log "service restarted."

# ----------------------------------------------------------------------
# Print summary.
# ----------------------------------------------------------------------
PUB_PATH="${STATE_DIR}/server.pub"
if [ -f "${PUB_PATH}" ]; then
    PUBKEY="$(cat "${PUB_PATH}")"
    printf '\n=========================================================\n' >&2
    printf 'mailcue-relay-edge installed.\n' >&2
    printf 'server pubkey (paste this into Mailcue when adding tunnel):\n' >&2
    printf '  %s\n' "${PUBKEY}" >&2
    printf '\n' >&2
    printf 'open the firewall:\n' >&2
    printf '  ufw allow %s/tcp\n' "${LISTEN_PORT}" >&2
    printf '\n' >&2
    printf 'check status:\n' >&2
    printf '  systemctl status mailcue-relay-edge\n' >&2
    printf '  journalctl -u mailcue-relay-edge -f\n' >&2
    printf '=========================================================\n' >&2
fi

exit 0
