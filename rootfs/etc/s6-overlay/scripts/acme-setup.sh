#!/bin/sh
# =============================================================================
# MailCue — ACME / Let's Encrypt Certificate Setup (oneshot)
# Runs AFTER Nginx is up so certbot can use HTTP-01 challenge on port 80.
# =============================================================================
set -eu

MAILCUE_MODE="${MAILCUE_MODE:-test}"
MAILCUE_ACME_EMAIL="${MAILCUE_ACME_EMAIL:-}"
HOSTNAME="${MAILCUE_HOSTNAME:-mail.${MAILCUE_DOMAIN:-mailcue.local}}"
SSL_DIR="/etc/ssl/mailcue"

# Only run in production mode with ACME email set and no cert yet
if [ "$MAILCUE_MODE" != "production" ]; then
    exit 0
fi

if [ -z "${MAILCUE_ACME_EMAIL}" ]; then
    exit 0
fi

# If cert already exists (custom mount, previous certbot run, etc.), skip
if [ -f "${SSL_DIR}/fullchain.pem" ]; then
    echo "[acme-setup] TLS cert already exists, skipping certbot."
    exit 0
fi

echo "[acme-setup] Requesting Let's Encrypt certificate for ${HOSTNAME}..."
echo "[acme-setup] ACME email: ${MAILCUE_ACME_EMAIL}"

mkdir -p /var/www/acme-challenge

# Wait briefly for Nginx to be ready
sleep 2

if certbot certonly --webroot \
    -w /var/www/acme-challenge \
    -d "${HOSTNAME}" \
    --email "${MAILCUE_ACME_EMAIL}" \
    --agree-tos --non-interactive; then

    echo "[acme-setup] Certificate obtained successfully."

    # Symlink to MailCue SSL directory
    ln -sf "/etc/letsencrypt/live/${HOSTNAME}/fullchain.pem" "${SSL_DIR}/fullchain.pem"
    ln -sf "/etc/letsencrypt/live/${HOSTNAME}/privkey.pem" "${SSL_DIR}/privkey.pem"

    # Also update Postfix and Dovecot certs
    cp "/etc/letsencrypt/live/${HOSTNAME}/fullchain.pem" "${SSL_DIR}/server.crt"
    cp "/etc/letsencrypt/live/${HOSTNAME}/privkey.pem" "${SSL_DIR}/server.key"
    chmod 600 "${SSL_DIR}/server.key" "${SSL_DIR}/privkey.pem"

    # Reload Postfix and Dovecot with new certs
    postfix reload 2>/dev/null || true
    doveadm reload 2>/dev/null || true

    # Generate Nginx HTTPS config
    mkdir -p /etc/nginx/conf.d
    cat > /etc/nginx/conf.d/https.conf << 'NGINXHTTPS'
server {
    listen 80;
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
    location / {
        try_files $uri $uri/ /index.html;
    }
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        expires 7d;
        add_header Cache-Control "public, immutable";
        try_files $uri =404;
    }
}
NGINXHTTPS

    # Reload Nginx with HTTPS config
    nginx -t && nginx -s reload
    echo "[acme-setup] HTTPS configured and Nginx reloaded."
else
    echo "[acme-setup] WARNING: certbot failed. Check that port 80 is reachable and DNS points to this server."
    echo "[acme-setup] You can retry manually: certbot certonly --webroot -w /var/www/acme-challenge -d ${HOSTNAME} --email ${MAILCUE_ACME_EMAIL}"
fi
