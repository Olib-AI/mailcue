# Email clients and TLS trust

Connect any standard email client to MailCue and trust its self-signed CA so TLS handshakes succeed.

## Using with email clients

MailCue works with any standard email client. Configure your client with:

| Setting | Value |
|---|---|
| **IMAP Server** | `localhost` (port 143 or 993 for SSL) |
| **POP3 Server** | `localhost` (port 110 or 995 for SSL) |
| **SMTP Server** | `localhost` (port 587, STARTTLS) |
| **Username** | `admin@mailcue.local` (or any created mailbox) |
| **Password** | Your mailbox password |
| **Security** | Accept the self-signed certificate |

## TLS certificate

MailCue generates a self-signed TLS certificate at container startup for Postfix, Dovecot, and Nginx. Any application connecting to MailCue over TLS (mail clients, SMTP relays, CI pipelines) must trust this certificate. You can download it from the Admin UI (**Admin > TLS Certificate** tab) or via the API:

```bash
curl -o mailcue-ca.crt http://localhost:8088/api/v1/system/certificate/download
```

Then install it in your system trust store:

**macOS**

```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain mailcue-ca.crt
```

Or double-click the file to open Keychain Access and set it to "Always Trust".

**Linux (Debian/Ubuntu)**

```bash
sudo cp mailcue-ca.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
```

**Linux (RHEL/Fedora)**

```bash
sudo cp mailcue-ca.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust
```

**Windows**

```powershell
certutil -addstore -f "ROOT" mailcue-ca.crt
```

Or double-click the file and install to "Trusted Root Certification Authorities".

**Docker / CI Pipelines**

```dockerfile
RUN curl -o /usr/local/share/ca-certificates/mailcue-ca.crt \
      http://<mailcue-host>/api/v1/system/certificate/download \
    && update-ca-certificates
```
