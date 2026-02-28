#!/bin/sh
# =============================================================================
# MailCue — Container Initialisation (oneshot)
# Runs once before any long-running services start.
# =============================================================================
set -eu

DOMAIN="${MAILCUE_DOMAIN:-mailcue.local}"
HOSTNAME="${MAILCUE_HOSTNAME:-mail.${DOMAIN}}"
ADMIN_USER="${MAILCUE_ADMIN_USER:-admin}"
ADMIN_PASSWORD="${MAILCUE_ADMIN_PASSWORD:-mailcue}"
SECRET_KEY="${MAILCUE_SECRET_KEY:-}"
DB_PATH="${MAILCUE_DB_PATH:-/var/lib/mailcue/mailcue.db}"
SSL_DIR="/etc/ssl/mailcue"
DKIM_DIR="/etc/opendkim/keys/${DOMAIN}"
VMAIL_BASE="/var/mail/vhosts"
DOVECOT_USERS="/etc/dovecot/users"

echo "[init-mailcue] Starting initialisation for domain=${DOMAIN}"

# -------------------------------------------------------------------------
# 1. Generate self-signed TLS certificates (if not already present)
# -------------------------------------------------------------------------
if [ ! -f "${SSL_DIR}/server.crt" ] || [ ! -f "${SSL_DIR}/server.key" ]; then
    echo "[init-mailcue] Generating self-signed TLS certificate..."
    mkdir -p "${SSL_DIR}"

    cat > /tmp/mailcue-ssl.cnf << SSLCNF
[req]
default_bits       = 2048
prompt             = no
default_md         = sha256
distinguished_name = dn
x509_extensions    = v3_req

[dn]
C  = US
ST = Testing
L  = Local
O  = MailCue
CN = ${HOSTNAME}

[v3_req]
subjectAltName = @alt_names
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth

[alt_names]
DNS.1 = ${HOSTNAME}
DNS.2 = smtp.${DOMAIN}
DNS.3 = imap.${DOMAIN}
DNS.4 = pop3.${DOMAIN}
DNS.5 = localhost
DNS.6 = ${DOMAIN}
IP.1  = 127.0.0.1
SSLCNF

    openssl req -x509 -newkey rsa:2048 -nodes \
        -keyout "${SSL_DIR}/server.key" \
        -out "${SSL_DIR}/server.crt" \
        -days 3650 \
        -config /tmp/mailcue-ssl.cnf 2>/dev/null

    chmod 600 "${SSL_DIR}/server.key"
    chmod 644 "${SSL_DIR}/server.crt"
    rm -f /tmp/mailcue-ssl.cnf
    echo "[init-mailcue] TLS certificate generated."
else
    echo "[init-mailcue] TLS certificate already exists, skipping generation."
fi

# -------------------------------------------------------------------------
# 2. Generate DKIM keys (if not already present)
# -------------------------------------------------------------------------
if [ ! -f "${DKIM_DIR}/mail.private" ]; then
    echo "[init-mailcue] Generating DKIM keys for ${DOMAIN}..."
    mkdir -p "${DKIM_DIR}"

    opendkim-genkey -b 2048 -h rsa-sha256 \
        -d "${DOMAIN}" -s mail \
        -D "${DKIM_DIR}/"

    chown -R opendkim:opendkim /etc/opendkim/keys/
    chmod 600 "${DKIM_DIR}/mail.private"
    echo "[init-mailcue] DKIM keys generated."
else
    echo "[init-mailcue] DKIM keys already exist, skipping generation."
fi

# -------------------------------------------------------------------------
# 3. Template mail server configuration files with runtime values
# -------------------------------------------------------------------------
echo "[init-mailcue] Templating configuration files..."

# --- Postfix main.cf ---
sed -i \
    -e "s/\${MAILCUE_DOMAIN}/${DOMAIN}/g" \
    -e "s/\${MAILCUE_HOSTNAME}/${HOSTNAME}/g" \
    /etc/postfix/main.cf

# --- Dovecot postmaster address ---
sed -i \
    -e "s/postmaster@mailcue\.local/postmaster@${DOMAIN}/g" \
    /etc/dovecot/dovecot.conf

# --- Postfix catch-all domain table ---
# Regexp table: match any domain.  Does NOT need postmap.
printf '/^.+$/    OK\n' > /etc/postfix/virtual_domains_catchall

# Keep legacy hash files for backward compat but they are no longer
# referenced by the main delivery path (catch-all replaces them).
touch /etc/postfix/virtual_mailboxes
touch /etc/postfix/virtual_aliases
touch /etc/postfix/virtual_domains

# --- OpenDKIM tables ---
echo "mail._domainkey.${DOMAIN}    ${DOMAIN}:mail:${DKIM_DIR}/mail.private" \
    > /etc/opendkim/KeyTable
echo "*@${DOMAIN}    mail._domainkey.${DOMAIN}" \
    > /etc/opendkim/SigningTable
cat > /etc/opendkim/TrustedHosts << TRUSTED
127.0.0.1
::1
localhost
${HOSTNAME}
*.${DOMAIN}
TRUSTED

chown -R opendkim:opendkim /etc/opendkim/

# -------------------------------------------------------------------------
# 4. Generate a secret key if none provided
# -------------------------------------------------------------------------
if [ -z "${SECRET_KEY}" ]; then
    SECRET_KEY=$(openssl rand -hex 32)
    echo "[init-mailcue] Auto-generated MAILCUE_SECRET_KEY."
fi
# Persist for use by other s6 services
echo "${SECRET_KEY}" > /var/lib/mailcue/.secret_key
chmod 600 /var/lib/mailcue/.secret_key

# -------------------------------------------------------------------------
# 5. Create the default admin user
# -------------------------------------------------------------------------
echo "[init-mailcue] Creating admin user: ${ADMIN_USER}@${DOMAIN}"

ADMIN_EMAIL="${ADMIN_USER}@${DOMAIN}"
ADMIN_MAILDIR="${VMAIL_BASE}/${DOMAIN}/${ADMIN_USER}"

# Generate password hash via doveadm (SHA512-CRYPT)
ADMIN_HASH=$(doveadm pw -s SHA512-CRYPT -p "${ADMIN_PASSWORD}" 2>/dev/null || true)
if [ -z "${ADMIN_HASH}" ]; then
    # Fallback: use PLAIN scheme (acceptable for a testing tool)
    ADMIN_HASH="{PLAIN}${ADMIN_PASSWORD}"
fi

# Initialise Dovecot users file (overwrite on fresh start, preserve on restart)
if [ ! -f "${DOVECOT_USERS}" ] || ! grep -q "^${ADMIN_EMAIL}:" "${DOVECOT_USERS}" 2>/dev/null; then
    touch "${DOVECOT_USERS}"
    echo "${ADMIN_EMAIL}:${ADMIN_HASH}:5000:5000::/var/mail/vhosts/${DOMAIN}/${ADMIN_USER}::" \
        >> "${DOVECOT_USERS}"
fi

# Also add a postmaster alias
if [ ! -f /etc/postfix/virtual_aliases ] || ! grep -q "postmaster@${DOMAIN}" /etc/postfix/virtual_aliases 2>/dev/null; then
    echo "postmaster@${DOMAIN}    ${ADMIN_EMAIL}" >> /etc/postfix/virtual_aliases
fi

# Keep legacy virtual_mailboxes entry for backward compat (not required for catch-all)
if ! grep -q "^${ADMIN_EMAIL}" /etc/postfix/virtual_mailboxes 2>/dev/null; then
    echo "${ADMIN_EMAIL}    ${DOMAIN}/${ADMIN_USER}/" \
        >> /etc/postfix/virtual_mailboxes
fi

# postmap the legacy tables (best-effort; catch-all does not depend on them)
postmap /etc/postfix/virtual_mailboxes 2>/dev/null || true
postmap /etc/postfix/virtual_aliases 2>/dev/null || true

# -------------------------------------------------------------------------
# 5b. Create Dovecot master-users file (for API impersonation)
# -------------------------------------------------------------------------
MASTER_USERS="/etc/dovecot/master-users"
MASTER_USER_NAME="${MAILCUE_IMAP_MASTER_USER:-mailcue-master}"
MASTER_USER_PASS="${MAILCUE_IMAP_MASTER_PASSWORD:-master-secret}"

# Hash the master user password
MASTER_HASH=$(doveadm pw -s SHA512-CRYPT -p "${MASTER_USER_PASS}" 2>/dev/null || true)
if [ -z "${MASTER_HASH}" ]; then
    MASTER_HASH="{PLAIN}${MASTER_USER_PASS}"
fi

if [ ! -f "${MASTER_USERS}" ] || ! grep -q "^${MASTER_USER_NAME}:" "${MASTER_USERS}" 2>/dev/null; then
    touch "${MASTER_USERS}"
    echo "${MASTER_USER_NAME}:${MASTER_HASH}" >> "${MASTER_USERS}"
fi
chmod 640 "${MASTER_USERS}"
chown root:dovecot "${MASTER_USERS}" 2>/dev/null || chown root:root "${MASTER_USERS}"

# -------------------------------------------------------------------------
# 6. Create Maildir structure for admin user
# -------------------------------------------------------------------------
for subdir in cur new tmp; do
    mkdir -p "${ADMIN_MAILDIR}/${subdir}"
done

for folder in .Sent .Drafts .Trash .Junk; do
    for subdir in cur new tmp; do
        mkdir -p "${ADMIN_MAILDIR}/${folder}/${subdir}"
    done
done

# Write Dovecot subscriptions file
cat > "${ADMIN_MAILDIR}/subscriptions" << SUBS
Sent
Drafts
Trash
Junk
SUBS

chown -R vmail:vmail "${VMAIL_BASE}"

# -------------------------------------------------------------------------
# 7. Set correct permissions on all relevant directories
# -------------------------------------------------------------------------
chmod 640 "${DOVECOT_USERS}"
chown root:dovecot "${DOVECOT_USERS}" 2>/dev/null || chown root:root "${DOVECOT_USERS}"

# Postfix chroot needs the Dovecot auth and LMTP sockets directory
mkdir -p /var/spool/postfix/private
chown postfix:postfix /var/spool/postfix/private

# Ensure Postfix data directory exists
mkdir -p /var/lib/postfix
chown postfix:postfix /var/lib/postfix

# Ensure the SQLite database directory exists
mkdir -p "$(dirname "${DB_PATH}")"
chown root:root /var/lib/mailcue

# Nginx directories
mkdir -p /var/www/mailcue
mkdir -p /var/log/nginx
mkdir -p /run

# -------------------------------------------------------------------------
# 8. Run Alembic migrations (if the application is installed)
# -------------------------------------------------------------------------
if command -v alembic >/dev/null 2>&1 && [ -f /opt/mailcue/alembic.ini ]; then
    echo "[init-mailcue] Running database migrations..."
    cd /opt/mailcue && alembic upgrade head 2>/dev/null || true
fi

# -------------------------------------------------------------------------
# 9. GPG keyring directory
# -------------------------------------------------------------------------
echo "[init-mailcue] Step 9: Setting up GPG keyring directory..."
mkdir -p /var/lib/mailcue/gpg
chmod 700 /var/lib/mailcue/gpg
echo "[init-mailcue] GPG keyring directory ready"

echo "[init-mailcue] Initialisation complete."
