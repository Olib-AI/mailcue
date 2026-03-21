# =============================================================================
# MailCue — Realistic Email Testing Server
# Single-container image: Postfix + Dovecot + OpenDKIM + FastAPI + Nginx
# Managed by s6-overlay v3
# =============================================================================

# ── Stage 1: Build frontend ─────────────────────────────────────
FROM node:25-slim AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# ── Stage 2: Runtime ────────────────────────────────────────────
FROM debian:bookworm-slim

LABEL org.opencontainers.image.source="https://github.com/Olib-AI/mailcue"
LABEL org.opencontainers.image.description="Realistic email testing server — Postfix, Dovecot, DKIM, API, Web UI in one container"
LABEL org.opencontainers.image.licenses="MIT"

ARG S6_OVERLAY_VERSION=3.2.0.2
ARG TARGETARCH

# Environment defaults (overridable at runtime)
ENV MAILCUE_DOMAIN=mailcue.local \
    MAILCUE_HOSTNAME=mail.mailcue.local \
    MAILCUE_ADMIN_USER=admin \
    MAILCUE_ADMIN_PASSWORD=mailcue \
    MAILCUE_SECRET_KEY="" \
    MAILCUE_DB_PATH=/var/lib/mailcue/mailcue.db \
    MAILCUE_DATABASE_ENCRYPTION_KEY="" \
    S6_BEHAVIOUR_IF_STAGE2_FAILS=2 \
    S6_CMD_WAIT_FOR_SERVICES_MAXTIME=30000

# System packages
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        postfix \
        dovecot-core \
        dovecot-imapd \
        dovecot-pop3d \
        dovecot-lmtpd \
        opendkim \
        opendkim-tools \
        openssl \
        ca-certificates \
        nginx \
        python3 \
        python3-pip \
        python3-venv \
        curl \
        netcat-openbsd \
        gettext-base \
        procps \
        xz-utils \
        gnupg \
        postfix-policyd-spf-python \
        spamassassin \
        spamc \
        spamd \
    && rm -rf /var/lib/apt/lists/*

# opendmarc postinst tries to restart the service which fails in Docker.
# Create the user manually, install deps, then unpack with postinst removed.
RUN adduser --system --group --no-create-home --home /run/opendmarc opendmarc \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        libopendmarc2 publicsuffix adduser dbconfig-no-thanks libmilter1.0.1 \
    && apt-get download opendmarc \
    && dpkg --unpack opendmarc_*.deb \
    ; rm -f /var/lib/dpkg/info/opendmarc.postinst \
    && dpkg --configure opendmarc \
    && rm -f opendmarc_*.deb \
    && rm -rf /var/lib/apt/lists/*

# Build SQLCipher from source — Debian Bookworm's packaged libsqlcipher omits
# symbols (e.g. sqlite3_create_window_function) that Python's _sqlite3 requires.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libssl-dev tcl \
    && curl -fsSL https://github.com/sqlcipher/sqlcipher/archive/refs/tags/v4.6.1.tar.gz \
        -o /tmp/sqlcipher.tar.gz \
    && tar -C /tmp -xzf /tmp/sqlcipher.tar.gz \
    && cd /tmp/sqlcipher-4.6.1 \
    && ./configure --enable-tempstore=yes --disable-tcl \
        CFLAGS="-DSQLITE_HAS_CODEC -DSQLCIPHER_CRYPTO_OPENSSL" \
        LDFLAGS="-lcrypto" \
    && make -j"$(nproc)" \
    && make install \
    && ldconfig \
    && cd / && rm -rf /tmp/sqlcipher* \
    && apt-get purge -y build-essential libssl-dev tcl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Replace libsqlite3 with SQLCipher (ABI-compatible drop-in for AES-256 encryption)
RUN case "${TARGETARCH}" in \
        amd64) LIBDIR="/usr/lib/x86_64-linux-gnu" ;; \
        arm64) LIBDIR="/usr/lib/aarch64-linux-gnu" ;; \
        *) echo "Unsupported arch: ${TARGETARCH}" && exit 1 ;; \
    esac \
    && ln -sf /usr/local/lib/libsqlcipher.so.0 "${LIBDIR}/libsqlite3.so.0"

# s6-overlay v3 installation (multi-arch)
ADD https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz /tmp/
RUN tar -C / -Jxpf /tmp/s6-overlay-noarch.tar.xz && rm -f /tmp/s6-overlay-noarch.tar.xz
# Map Docker TARGETARCH to s6-overlay arch names
RUN case "${TARGETARCH}" in \
        amd64) S6_ARCH="x86_64" ;; \
        arm64) S6_ARCH="aarch64" ;; \
        *) echo "Unsupported arch: ${TARGETARCH}" && exit 1 ;; \
    esac \
    && curl -fsSL "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-${S6_ARCH}.tar.xz" -o /tmp/s6-overlay-arch.tar.xz \
    && tar -C / -Jxpf /tmp/s6-overlay-arch.tar.xz \
    && rm -f /tmp/s6-overlay-arch.tar.xz

# Create vmail system user (UID/GID 5000) for Dovecot virtual mailboxes
RUN groupadd -g 5000 vmail \
    && useradd -u 5000 -g vmail -d /var/mail/vhosts -s /usr/sbin/nologin -r vmail \
    && mkdir -p /var/mail/vhosts \
    && chown -R vmail:vmail /var/mail/vhosts

# GPG keyring directory for PGP operations
RUN mkdir -p /var/lib/mailcue/gpg && chmod 700 /var/lib/mailcue/gpg

# Create directories for runtime state
RUN mkdir -p \
        /etc/ssl/mailcue \
        /etc/opendkim/keys \
        /var/lib/mailcue \
        /var/www/mailcue \
        /var/run/opendkim \
        /var/run/opendmarc \
        /var/spool/postfix/private \
    && chown opendkim:opendkim /var/run/opendkim /etc/opendkim/keys

# Python application — install into a virtualenv
RUN python3 -m venv /opt/mailcue/venv
ENV PATH="/opt/mailcue/venv/bin:${PATH}" \
    VIRTUAL_ENV="/opt/mailcue/venv"

# Install backend: copy everything and install in one step
COPY backend/ /opt/mailcue/
WORKDIR /opt/mailcue
RUN pip install --no-cache-dir .

# Copy rootfs overlay — s6 services, mail configs, nginx config
COPY rootfs/ /

# Ensure all s6 run scripts are executable
RUN find /etc/s6-overlay/s6-rc.d -name "run" -exec chmod +x {} + \
    && find /etc/s6-overlay/s6-rc.d -name "up" -exec chmod +x {} + \
    && find /etc/s6-overlay/scripts -name "*.sh" -exec chmod +x {} +

# Copy built frontend into Nginx serving directory
COPY --from=frontend-builder /build/dist/ /var/www/mailcue/

# Expose ports
EXPOSE 25 587 143 993 110 995 80 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -sf http://127.0.0.1:80/api/v1/health || exit 1

# Entrypoint — s6-overlay init
ENTRYPOINT ["/init"]
