# Production deployment

MailCue can run as a hardened production email server. Set `MAILCUE_MODE=production` to switch from the default catch-all test mode to production mode.

## What changes in production mode

- **Postfix**: Strict virtual domain/mailbox maps (no catch-all), `mynetworks` restricted to loopback, SPF policy enforcement, SMTPS on port 465
- **Dovecot**: Password-less catch-all auth disabled, `ssl = required`, `disable_plaintext_auth = yes`, quota enforcement enabled
- **OpenDMARC**: `RejectFailures` set to `true`, so DMARC policy `p=reject` is honored
- **Nginx**: HTTPS server block generated when TLS certs are available, HTTP-to-HTTPS redirect
- **MTA-STS**: Policy switches from `mode: testing` to `mode: enforce`
- **Cookies**: Secure flag enabled, SameSite set to `strict`
- **Mailboxes**: Domain validation enforced, so mailboxes can only be created for registered domains
- **Tenant isolation**: Forwarding, event streams, API keys, and GPG keys are restricted to their owning user
- **Sessions**: Refresh tokens rotate once, logout and password changes revoke existing tokens
- **Startup validation**: Known passwords, missing TLS, wildcard CORS, and weak secrets stop startup

## Required security settings

Production startup fails until all of these are configured:

```env
MAILCUE_MODE=production
MAILCUE_DOMAIN=example.com
MAILCUE_HOSTNAME=mail.example.com
MAILCUE_ADMIN_PASSWORD=a-unique-password-of-at-least-12-characters
MAILCUE_SECRET_KEY=generate-with-openssl-rand-hex-32
MAILCUE_IMAP_MASTER_PASSWORD=generate-a-different-secret-with-openssl-rand-hex-32
MAILCUE_ACME_EMAIL=postmaster@example.com
MAILCUE_CORS_ORIGINS=[]
```

Generate the application and Dovecot secrets separately. Do not reuse either
secret as the admin password or database password.

## Docker Compose (production)

The easiest way to deploy is the standalone [`docker-compose.deploy.yml`](../../docker-compose.deploy.yml):

```bash
# 1. Download the deploy file to your server
curl -O https://raw.githubusercontent.com/Olib-AI/mailcue/main/docker-compose.deploy.yml

# 2. Replace every placeholder value. Generate the two secrets separately.
sed -i 's/CHANGE_ME_DOMAIN/yourdomain.com/g' docker-compose.deploy.yml
sed -i 's/CHANGE_ME_PASSWORD/your-strong-password/g' docker-compose.deploy.yml
sed -i 's/CHANGE_ME_EMAIL/you@example.com/g' docker-compose.deploy.yml
openssl rand -hex 32
openssl rand -hex 32

# 3. Deploy
docker compose -f docker-compose.deploy.yml up -d
```

Alternatively, use the override pattern with the base compose file:

```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d
```

## PostgreSQL for production

SQLite remains suitable for small and single-user installations. For sustained
concurrent API, sandbox, HTTP-bin, or warmup traffic, configure an external
PostgreSQL 14+ database:

```env
MAILCUE_DATABASE_BACKEND=postgresql
MAILCUE_DATABASE_HOST=db.example.com
MAILCUE_DATABASE_PORT=5432
MAILCUE_DATABASE_USER=mailcue
MAILCUE_DATABASE_PASSWORD=replace-me
MAILCUE_DATABASE_NAME=mailcue
MAILCUE_DATABASE_SSLMODE=verify-full
```

Use a migration role that can create and alter tables and indexes. The runtime
role only needs data access. Configure the two roles separately:

```env
MAILCUE_MIGRATION_DATABASE_URL=postgresql+psycopg://mailcue_migrator:password@db.example.com/mailcue?sslmode=verify-full
MAILCUE_DATABASE_URL=postgresql+psycopg://mailcue_app:password@db.example.com/mailcue?sslmode=verify-full
```

Migrations run under a PostgreSQL advisory lock, so concurrent container starts
cannot change the schema simultaneously.

### Run PostgreSQL as its own container

The following Compose override adds PostgreSQL 17 on the same private Docker
network as MailCue. PostgreSQL is not published on a host port. Store both
password values in `.env`, use a unique strong password, and keep the database
volume in your backup plan.

```yaml
# docker-compose.postgres.yml
services:
  postgres:
    image: postgres:17
    restart: unless-stopped
    environment:
      POSTGRES_USER: mailcue
      POSTGRES_PASSWORD: ${MAILCUE_POSTGRES_PASSWORD:?set in .env}
      POSTGRES_DB: mailcue
    volumes:
      - mailcue-postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U mailcue -d mailcue"]
      interval: 5s
      timeout: 5s
      retries: 12

  mailcue:
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      MAILCUE_DATABASE_BACKEND: postgresql
      MAILCUE_DATABASE_HOST: postgres
      MAILCUE_DATABASE_PORT: 5432
      MAILCUE_DATABASE_USER: mailcue
      MAILCUE_DATABASE_PASSWORD: ${MAILCUE_POSTGRES_PASSWORD:?set in .env}
      MAILCUE_DATABASE_NAME: mailcue
      MAILCUE_DATABASE_SSLMODE: disable
      MAILCUE_DATABASE_ALLOW_INSECURE_PRIVATE_NETWORK: "true"

volumes:
  mailcue-postgres:
```

Start the production files together:

```bash
docker compose \
  -f docker-compose.deploy.yml \
  -f docker-compose.postgres.yml \
  up -d
```

Do not publish port 5432 unless administrators genuinely need remote database
access. If it must be published, restrict it with a firewall and configure
PostgreSQL TLS and host-based authentication.

### Migrate from SQLite or SQLCipher

The transfer is deliberately offline. It never modifies or deletes the SQLite
source, creates a timestamped backup beside it, refuses a non-empty PostgreSQL
target, and validates row counts and primary-key hashes before committing.

```bash
# 1. Pull the new image and start once with the existing SQLite settings.
#    This upgrades SQLite to the current schema.
docker compose pull mailcue
docker compose up -d mailcue

# 2. Stop every MailCue replica to prevent writes during the copy.
docker compose stop mailcue

# 3. Add the PostgreSQL settings above to .env, then run the one-time copier.
docker compose run --rm --no-deps --entrypoint mailcue-db mailcue \
  sqlite-to-postgres \
  --source /var/lib/mailcue/mailcue.db \
  --yes-i-have-stopped-mailcue

# 4. Start MailCue against PostgreSQL and inspect health/logs.
docker compose up -d mailcue
docker compose logs --tail=100 mailcue
```

The PostgreSQL target must be empty. The command creates the current schema,
copies tables in foreign-key order, resets PostgreSQL sequences, and compares
the row count and primary-key hash for every copied table. It exits without
committing the target data if validation fails.

For SQLCipher, leave `MAILCUE_DATABASE_ENCRYPTION_KEY` set during step 3 so the
copier can read the encrypted source. After successful cutover, PostgreSQL does
not use that key. To roll back, stop MailCue, restore the SQLite database
settings, and restart; the original SQLite file remains untouched.

This migration covers application metadata and captured sandbox data. Maildir
email content remains in `/var/mail/vhosts` and is not moved into PostgreSQL.
Keep the SQLite backup until the PostgreSQL deployment has passed application,
login, mailbox, and sandbox checks and has been included in a successful
database backup.

## TLS Certificates

Production mode supports three approaches:

1. **Let's Encrypt (automatic)**: Set `MAILCUE_ACME_EMAIL=you@example.com` and ensure port 80 is reachable for HTTP-01 validation. Certbot runs automatically at startup. After `mta-sts.example.com` resolves, MailCue expands the certificate to cover both the mail and MTA-STS hostnames on the next container start.
2. **External certificates**: Set `MAILCUE_TLS_CERT_PATH` and `MAILCUE_TLS_KEY_PATH` to mount certs from a reverse proxy (Traefik, Caddy) or manual provisioning. The certificate must include both `mail.example.com` and `mta-sts.example.com`.
3. **Upload via API**: Use `PUT /api/v1/system/tls` to rotate a certificate after production has started with ACME or externally mounted certificates.

## DNS Requirements

For each domain, configure the following DNS records. The domain management UI (`/api/v1/domains/:name`) provides the exact values for your setup. Replace `example.com` with your domain and `mail.example.com` with your mail server hostname.

| # | Type | Name | Value | Purpose |
|---|------|------|-------|---------|
| 1 | **A** | `mail.example.com` | `<server-ip>` | Points mail hostname to your server |
| 2 | **MX** | `example.com` | `10 mail.example.com.` | Routes inbound email to your server |
| 3 | **TXT** | `example.com` | `v=spf1 mx a:mail.example.com ~all` | SPF, authorizes your server to send email |
| 4 | **TXT** | `mail.example.com` | `v=spf1 a -all` | HELO SPF, validates the SMTP EHLO hostname |
| 5 | **TXT** | `mail._domainkey.example.com` | `v=DKIM1; h=rsa-sha256; k=rsa; p=<key>` | DKIM, email signature verification |
| 6 | **TXT** | `_dmarc.example.com` | `v=DMARC1; p=reject; rua=mailto:postmaster@example.com` | DMARC, reject policy for auth failures (required for BIMI) |
| 7 | **TXT** | `default._bimi.example.com` | `v=BIMI1; l=https://mail.example.com/brand/logo.svg` | BIMI, brand logo displayed by supporting mailbox providers (optional) |
| 8 | **TXT** | `_mta-sts.example.com` | `v=STSv1; id=<timestamp>` | MTA-STS, strict TLS for inbound (optional) |
| 9 | **A / AAAA** | `mta-sts.example.com` | `<server-ip>` | Makes the MTA-STS HTTPS policy reachable; either address family is sufficient |
| 10 | **TXT** | `_smtp._tls.example.com` | `v=TLSRPTv1; rua=mailto:tls-reports@example.com` | TLS-RPT, TLS failure reporting (optional) |
| 11 | **PTR** | `<server-ip>` | `mail.example.com` | Reverse DNS, set at your VPS provider. Critical for deliverability. |

**Getting the DKIM public key:** After starting MailCue, retrieve your DKIM key with:

```bash
docker exec mailcue cat /etc/opendkim/keys/<domain>/mail.txt
```

Extract the `p=...` value (concatenate if split across lines) and use it for record #5.

**Important notes:**
- Records 1-6 and 11 are **required** for production email delivery.
- Records 8 and 9, plus a valid HTTPS certificate for `mta-sts.example.com`, are required when enabling MTA-STS.
- The DKIM key is auto-generated at first startup and persists in the `dkim-data` volume. It will not change across restarts.
- If your VPS provider blocks outbound port 25 (common on GCP, AWS), you will need a smarthost relay or a provider that allows it (OVH, Hetzner, Vultr).
