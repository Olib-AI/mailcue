# =============================================================================
# MailCue - Realistic Email Testing Server
# Single-container image: Postfix + Dovecot + OpenDKIM + FastAPI + Nginx
# Managed by s6-overlay v3
# =============================================================================

# -- Stage 1: Build frontend -------------------------------------
FROM node:26-slim AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --legacy-peer-deps
COPY frontend/ .
RUN npm run build

# -- Stage 2: Build SQLCipher from source ------------------------
FROM debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad AS sqlcipher-builder
ADD https://github.com/sqlcipher/sqlcipher/archive/refs/tags/v4.6.1.tar.gz /tmp/sqlcipher.tar.gz
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libssl-dev \
        tcl \
        ca-certificates \
    && tar -C /tmp -xzf /tmp/sqlcipher.tar.gz \
    && cd /tmp/sqlcipher-4.6.1 \
    && ./configure --prefix=/usr/local --enable-tempstore=yes --disable-tcl \
        CFLAGS="-DSQLITE_HAS_CODEC -DSQLCIPHER_CRYPTO_OPENSSL" \
        LDFLAGS="-lcrypto" \
    && make -j"$(nproc)" \
    && make install DESTDIR=/install \
    && rm -rf /tmp/sqlcipher* /var/lib/apt/lists/*

# -- Stage 3: Runtime --------------------------------------------
FROM debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad

LABEL org.opencontainers.image.source="https://github.com/Olib-AI/mailcue"
LABEL org.opencontainers.image.description="Realistic email testing server - Postfix, Dovecot, DKIM, API, Web UI in one container"
LABEL org.opencontainers.image.licenses="MIT"

ARG S6_OVERLAY_VERSION=3.2.0.2
ARG S6_OVERLAY_NOARCH_SHA256=6dbcde158a3e78b9bb141d7bcb5ccb421e563523babbe2c64470e76f4fd02dae
ARG TARGETARCH

# Environment defaults (overridable at runtime)
ENV MAILCUE_MODE=test \
    MAILCUE_DOMAIN=mailcue.local \
    MAILCUE_HOSTNAME=mail.mailcue.local \
    MAILCUE_ADMIN_USER=admin \
    MAILCUE_DB_PATH=/var/lib/mailcue/mailcue.db \
    MAILCUE_ACME_EMAIL="" \
    MAILCUE_TLS_CERT_PATH="" \
    S6_BEHAVIOUR_IF_STAGE2_FAILS=2 \
    S6_CMD_WAIT_FOR_SERVICES_MAXTIME=300000

# Install Nginx mainline repo (nginx >= 1.31.7) and runtime packages without compilers
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        gnupg \
        ca-certificates \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://nginx.org/keys/nginx_signing.key | gpg --dearmor -o /etc/apt/keyrings/nginx.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nginx.gpg] http://nginx.org/packages/mainline/debian/ trixie nginx" > /etc/apt/sources.list.d/nginx.list \
    && apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        postfix \
        dovecot-core \
        dovecot-imapd \
        dovecot-pop3d \
        dovecot-lmtpd \
        dovecot-sieve \
        dovecot-managesieved \
        opendkim \
        opendkim-tools \
        openssl \
        nginx \
        python3 \
        python3-pip \
        python3-venv \
        netcat-openbsd \
        gettext-base \
        procps \
        xz-utils \
        postfix-policyd-spf-python \
        spamassassin \
        spamc \
        spamd \
        certbot \
        chromium \
        dbconfig-no-thanks \
        opendmarc \
    && rm -rf /var/lib/apt/lists/*

# Install pre-compiled SQLCipher from builder stage
COPY --from=sqlcipher-builder /install/usr/local/ /usr/local/

# Replace libsqlite3 with SQLCipher (ABI-compatible drop-in for AES-256 encryption)
RUN ldconfig \
    && ARCH="${TARGETARCH:-$(dpkg --print-architecture)}" \
    && case "${ARCH}" in \
        amd64) LIBDIR="/usr/lib/x86_64-linux-gnu" ;; \
        arm64) LIBDIR="/usr/lib/aarch64-linux-gnu" ;; \
        *) echo "Unsupported arch: ${ARCH}" && exit 1 ;; \
    esac \
    && ln -sf /usr/local/lib/libsqlcipher.so.0 "${LIBDIR}/libsqlite3.so.0"

# s6-overlay v3 installation (multi-arch)
ADD https://github.com/just-containers/s6-overlay/releases/download/v3.2.0.2/s6-overlay-noarch.tar.xz /tmp/s6-overlay-noarch.tar.xz
ADD https://github.com/just-containers/s6-overlay/releases/download/v3.2.0.2/s6-overlay-x86_64.tar.xz /tmp/s6-overlay-x86_64.tar.xz
ADD https://github.com/just-containers/s6-overlay/releases/download/v3.2.0.2/s6-overlay-aarch64.tar.xz /tmp/s6-overlay-aarch64.tar.xz

RUN echo "${S6_OVERLAY_NOARCH_SHA256}  /tmp/s6-overlay-noarch.tar.xz" | sha256sum -c - \
    && tar -C / -Jxpf /tmp/s6-overlay-noarch.tar.xz \
    && ARCH="${TARGETARCH:-$(dpkg --print-architecture)}" \
    && case "${ARCH}" in \
        amd64) S6_ARCH="x86_64"; S6_SHA256="59289456ab1761e277bd456a95e737c06b03ede99158beb24f12b165a904f478" ;; \
        arm64) S6_ARCH="aarch64"; S6_SHA256="8b22a2eaca4bf0b27a43d36e65c89d2701738f628d1abd0cea5569619f66f785" ;; \
        *) echo "Unsupported arch: ${ARCH}" && exit 1 ;; \
    esac \
    && echo "${S6_SHA256}  /tmp/s6-overlay-${S6_ARCH}.tar.xz" | sha256sum -c - \
    && tar -C / -Jxpf "/tmp/s6-overlay-${S6_ARCH}.tar.xz" \
    && rm -f /tmp/s6-overlay-*.tar.xz

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
        /var/www/acme-challenge \
        /var/run/opendkim \
        /var/run/opendmarc \
        /var/run/spamd \
        /var/spool/postfix/private \
        /var/lib/spamassassin \
        /var/lib/dovecot \
        /var/cache/nginx \
        /var/log/nginx \
    && chown -R opendkim:opendkim /var/run/opendkim /etc/opendkim/keys \
    && chown -R opendmarc:opendmarc /var/run/opendmarc \
    && chown -R debian-spamd:debian-spamd /var/run/spamd /var/lib/spamassassin \
    && chown -R dovecot:dovecot /var/lib/dovecot \
    && chown -R nginx:nginx /var/cache/nginx /var/log/nginx

# Python application - install into a virtualenv
RUN python3 -m venv /opt/mailcue/venv
ENV PATH="/opt/mailcue/venv/bin:${PATH}" \
    VIRTUAL_ENV="/opt/mailcue/venv"

# Install backend: copy everything and install in one step
COPY backend/ /opt/mailcue/
WORKDIR /opt/mailcue
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir .

# Copy built frontend into Nginx serving directory
COPY --from=frontend-builder /build/dist/ /var/www/mailcue/

# Copy rootfs overlay - s6 services, mail configs, nginx config
COPY rootfs/ /

# Ensure all s6 run scripts are executable
RUN find /etc/s6-overlay/s6-rc.d -name "run" -exec chmod +x {} + \
    && find /etc/s6-overlay/s6-rc.d -name "up" -exec chmod +x {} + \
    && find /etc/s6-overlay/scripts -name "*.sh" -exec chmod +x {} +

# Backup configuration templates for read-only rootfs tmpfs mounts
RUN mkdir -p /usr/share/mailcue/config \
    && cp -a /etc/postfix /usr/share/mailcue/config/postfix \
    && cp -a /etc/dovecot /usr/share/mailcue/config/dovecot \
    && cp -a /etc/opendkim /usr/share/mailcue/config/opendkim \
    && cp -a /etc/opendmarc /usr/share/mailcue/config/opendmarc \
    && cp -a /etc/nginx/conf.d /usr/share/mailcue/config/nginx-conf.d

# Expose ports
EXPOSE 25 587 143 993 110 995 80 443 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -sf http://127.0.0.1:80/api/v1/health || exit 1

# Entrypoint - s6-overlay init
ENTRYPOINT ["/init"]
