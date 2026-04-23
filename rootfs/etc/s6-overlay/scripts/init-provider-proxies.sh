#!/bin/sh
# =============================================================================
#  Init — phone-provider TLS interception proxies
#
#  Runs AFTER init-mailcue (which owns the CA at /etc/ssl/mailcue) and
#  BEFORE Nginx.  Generates leaf certs for every hostname the sandbox
#  impersonates and writes the corresponding Nginx conf.d include.
#
#  Both Python entrypoints are idempotent and safe on every boot.
# =============================================================================
set -eu

if [ "${MAILCUE_PROVIDER_PROXIES_ENABLED:-true}" = "false" ] \
   || [ "${MAILCUE_PROVIDER_PROXIES_ENABLED:-true}" = "0" ] \
   || [ "${MAILCUE_PROVIDER_PROXIES_ENABLED:-true}" = "no" ]; then
    echo "[init-provider-proxies] Disabled (MAILCUE_PROVIDER_PROXIES_ENABLED=false)."
    # Still emit the (empty) config so any prior file is replaced.
    /opt/mailcue/venv/bin/python -m app.sandbox.scripts.generate_provider_nginx \
        || echo "[init-provider-proxies] conf emission failed — continuing."
    exit 0
fi

echo "[init-provider-proxies] Generating provider leaf certs..."
/opt/mailcue/venv/bin/python -m app.sandbox.scripts.generate_provider_certs

echo "[init-provider-proxies] Writing Nginx conf.d/provider_proxies.conf..."
/opt/mailcue/venv/bin/python -m app.sandbox.scripts.generate_provider_nginx

echo "[init-provider-proxies] Done."
