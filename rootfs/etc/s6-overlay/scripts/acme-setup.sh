#!/bin/sh
# =============================================================================
# MailCue — ACME / Let's Encrypt Certificate Setup (oneshot)
# Runs AFTER Nginx is up so certbot can use HTTP-01 challenge on port 80.
# =============================================================================
set -eu

MAILCUE_MODE="${MAILCUE_MODE:-test}"
MAILCUE_ACME_EMAIL="${MAILCUE_ACME_EMAIL:-}"
DOMAIN="${MAILCUE_DOMAIN:-mailcue.local}"
HOSTNAME="${MAILCUE_HOSTNAME:-mail.${DOMAIN}}"
MTA_STS_HOSTNAME="mta-sts.${DOMAIN}"
SSL_DIR="/etc/ssl/mailcue"
ACME_CERT_DIR="/etc/letsencrypt/live/${HOSTNAME}"

# Only run in production mode with ACME configured.
if [ "$MAILCUE_MODE" != "production" ]; then
    exit 0
fi

if [ -z "${MAILCUE_ACME_EMAIL}" ]; then
    exit 0
fi

# Custom certificates are operator-managed. Never replace one with ACME.
if [ -f "${SSL_DIR}/fullchain.pem" ] && [ ! -f "${ACME_CERT_DIR}/fullchain.pem" ]; then
    if openssl x509 -in "${SSL_DIR}/fullchain.pem" -noout -checkhost "${MTA_STS_HOSTNAME}" >/dev/null 2>&1; then
        echo "[acme-setup] Custom TLS certificate already covers ${MTA_STS_HOSTNAME}."
    else
        echo "[acme-setup] WARNING: custom TLS certificate must include ${MTA_STS_HOSTNAME}."
    fi
    exit 0
fi

# A persisted mail-host certificate may predate MTA-STS support. Keep it live
# until the policy hostname resolves, then expand the same ACME lineage.
MTA_STS_RESOLVES=false
if getent ahosts "${MTA_STS_HOSTNAME}" >/dev/null 2>&1 || getent hosts "${MTA_STS_HOSTNAME}" >/dev/null 2>&1; then
    MTA_STS_RESOLVES=true
fi

EXPAND_CERTIFICATE=false
if [ -f "${ACME_CERT_DIR}/fullchain.pem" ]; then
    if openssl x509 -in "${ACME_CERT_DIR}/fullchain.pem" -noout -checkhost "${MTA_STS_HOSTNAME}" >/dev/null 2>&1; then
        echo "[acme-setup] TLS certificate already covers ${HOSTNAME} and ${MTA_STS_HOSTNAME}."
        exit 0
    fi
    if [ "${MTA_STS_RESOLVES}" != "true" ]; then
        echo "[acme-setup] Existing certificate covers ${HOSTNAME}; waiting for DNS for ${MTA_STS_HOSTNAME} before expanding it."
        exit 0
    fi
    echo "[acme-setup] Expanding the existing certificate to include ${MTA_STS_HOSTNAME}..."
    EXPAND_CERTIFICATE=true
else
    echo "[acme-setup] Requesting Let's Encrypt certificate for ${HOSTNAME}..."
fi
echo "[acme-setup] ACME email: ${MAILCUE_ACME_EMAIL}"

mkdir -p /var/www/acme-challenge

# Wait briefly for Nginx to be ready
sleep 2

set -- certonly --webroot \
    -w /var/www/acme-challenge \
    --cert-name "${HOSTNAME}" \
    -d "${HOSTNAME}"
if [ "${MTA_STS_RESOLVES}" = "true" ]; then
    set -- "$@" -d "${MTA_STS_HOSTNAME}"
fi
set -- "$@" \
    --email "${MAILCUE_ACME_EMAIL}" \
    --agree-tos --non-interactive
if [ "${EXPAND_CERTIFICATE}" = "true" ]; then
    set -- "$@" --expand
fi

if certbot "$@"; then

    echo "[acme-setup] Certificate obtained successfully."

    # Symlink to MailCue SSL directory
    ln -sf "${ACME_CERT_DIR}/fullchain.pem" "${SSL_DIR}/fullchain.pem"
    ln -sf "${ACME_CERT_DIR}/privkey.pem" "${SSL_DIR}/privkey.pem"

    # Also update Postfix and Dovecot certs
    cp "${ACME_CERT_DIR}/fullchain.pem" "${SSL_DIR}/server.crt"
    cp "${ACME_CERT_DIR}/privkey.pem" "${SSL_DIR}/server.key"
    chmod 600 "${SSL_DIR}/server.key" "${SSL_DIR}/privkey.pem"

    # Reload Postfix and Dovecot with new certs
    postfix reload 2>/dev/null || true
    doveadm reload 2>/dev/null || true

    # Generate Nginx HTTPS config
    mkdir -p /etc/nginx/conf.d
    sed -i 's/listen 80 default_server;/listen 127.0.0.1:8081;/' /etc/nginx/nginx.conf
    cat > /etc/nginx/conf.d/https.conf << 'NGINXHTTPS'
server {
    listen 80 default_server;
    server_name _;
    location /.well-known/acme-challenge/ {
        root /var/www/acme-challenge;
        try_files $uri =404;
    }
    location / {
        return 301 https://$host$request_uri;
    }
}
server {
    listen 443 ssl http2;
    server_name _;
    ssl_certificate     /etc/ssl/mailcue/fullchain.pem;
    ssl_certificate_key /etc/ssl/mailcue/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;
    ssl_prefer_server_ciphers on;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
    include /etc/nginx/security_headers.conf;

    root /var/www/mailcue;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_connect_timeout 10s;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }
    location /sandbox/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_connect_timeout 10s;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }
    location /httpbin/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_connect_timeout 10s;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }
    location /api/v1/events/stream {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding off;
        proxy_read_timeout 3600s;
        add_header X-Accel-Buffering no;
        include /etc/nginx/security_headers.conf;
    }
    location /.well-known/acme-challenge/ {
        root /var/www/acme-challenge;
        try_files $uri =404;
    }
    location /.well-known/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    location = /email-frame.html {
        include /etc/nginx/email_frame_headers.conf;
        try_files $uri =404;
    }
    location / {
        try_files $uri $uri/ /index.html;
    }
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        expires 7d;
        add_header Cache-Control "public, immutable";
        include /etc/nginx/security_headers.conf;
        try_files $uri =404;
    }
}
NGINXHTTPS

    # Reload Nginx with HTTPS config
    nginx -t && nginx -s reload
    echo "[acme-setup] HTTPS configured and Nginx reloaded."
else
    echo "[acme-setup] WARNING: certbot failed. Check that port 80 is reachable and DNS points to this server."
    echo "[acme-setup] Retry after DNS is correct: certbot certonly --webroot -w /var/www/acme-challenge --cert-name ${HOSTNAME} -d ${HOSTNAME} -d ${MTA_STS_HOSTNAME} --expand --email ${MAILCUE_ACME_EMAIL}"
fi
