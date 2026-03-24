#!/bin/sh
# =============================================================================
# MailCue — ACME / Let's Encrypt Certificate Renewal (long-running)
# Checks for renewal every 12 hours. Reloads services if renewed.
# =============================================================================
set -eu

MAILCUE_MODE="${MAILCUE_MODE:-test}"
MAILCUE_ACME_EMAIL="${MAILCUE_ACME_EMAIL:-}"
HOSTNAME="${MAILCUE_HOSTNAME:-mail.${MAILCUE_DOMAIN:-mailcue.local}}"
SSL_DIR="/etc/ssl/mailcue"

# Only run in production mode with ACME email set
if [ "$MAILCUE_MODE" != "production" ] || [ -z "${MAILCUE_ACME_EMAIL}" ]; then
    echo "[acme-renew] Not in production mode or no ACME email set. Sleeping forever."
    exec sleep infinity
fi

echo "[acme-renew] Certificate renewal service started. Checking every 12 hours."

while true; do
    sleep 43200  # 12 hours

    echo "[acme-renew] Checking certificate renewal..."

    if certbot renew --quiet --webroot -w /var/www/acme-challenge 2>&1; then
        # Check if the cert was actually renewed by comparing timestamps
        if [ -f "/etc/letsencrypt/live/${HOSTNAME}/fullchain.pem" ]; then
            # Update symlinks and copies
            ln -sf "/etc/letsencrypt/live/${HOSTNAME}/fullchain.pem" "${SSL_DIR}/fullchain.pem"
            ln -sf "/etc/letsencrypt/live/${HOSTNAME}/privkey.pem" "${SSL_DIR}/privkey.pem"
            cp "/etc/letsencrypt/live/${HOSTNAME}/fullchain.pem" "${SSL_DIR}/server.crt"
            cp "/etc/letsencrypt/live/${HOSTNAME}/privkey.pem" "${SSL_DIR}/server.key"
            chmod 600 "${SSL_DIR}/server.key"

            # Reload services to pick up new cert
            postfix reload 2>/dev/null || true
            doveadm reload 2>/dev/null || true
            nginx -s reload 2>/dev/null || true

            echo "[acme-renew] Certificate renewed and services reloaded."
        fi
    else
        echo "[acme-renew] Renewal check complete (no renewal needed or renewal failed)."
    fi
done
