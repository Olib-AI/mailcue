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

## Docker Compose (production)

The easiest way to deploy is the standalone [`docker-compose.deploy.yml`](../../docker-compose.deploy.yml):

```bash
# 1. Download the deploy file to your server
curl -O https://raw.githubusercontent.com/Olib-AI/mailcue/main/docker-compose.deploy.yml

# 2. Replace the placeholder values
sed -i 's/CHANGE_ME_DOMAIN/yourdomain.com/g' docker-compose.deploy.yml
sed -i 's/CHANGE_ME_PASSWORD/your-strong-password/g' docker-compose.deploy.yml
sed -i 's/CHANGE_ME_EMAIL/you@example.com/g' docker-compose.deploy.yml

# 3. Deploy
docker compose -f docker-compose.deploy.yml up -d
```

Alternatively, use the override pattern with the base compose file:

```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d
```

## TLS Certificates

Production mode supports three approaches:

1. **Let's Encrypt (automatic)**: Set `MAILCUE_ACME_EMAIL=you@example.com` and ensure port 80 is reachable for HTTP-01 validation. Certbot runs automatically at startup.
2. **External certificates**: Set `MAILCUE_TLS_CERT_PATH` and `MAILCUE_TLS_KEY_PATH` to mount certs from a reverse proxy (Traefik, Caddy) or manual provisioning.
3. **Upload via API**: Use `PUT /api/v1/system/tls` to upload certificate and key through the admin UI or API.

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
| 9 | **TXT** | `_smtp._tls.example.com` | `v=TLSRPTv1; rua=mailto:tls-reports@example.com` | TLS-RPT, TLS failure reporting (optional) |
| 10 | **PTR** | `<server-ip>` | `mail.example.com` | Reverse DNS, set at your VPS provider. Critical for deliverability. |

**Getting the DKIM public key:** After starting MailCue, retrieve your DKIM key with:

```bash
docker exec mailcue cat /etc/opendkim/keys/<domain>/mail.txt
```

Extract the `p=...` value (concatenate if split across lines) and use it for record #5.

**Important notes:**
- Records 1-6 and 10 are **required** for production email delivery.
- The DKIM key is auto-generated at first startup and persists in the `dkim-data` volume. It will not change across restarts.
- If your VPS provider blocks outbound port 25 (common on GCP, AWS), you will need a smarthost relay or a provider that allows it (OVH, Hetzner, Vultr).
