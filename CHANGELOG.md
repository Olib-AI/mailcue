# Changelog

## [2.4.0] - 2026-10-23

### Security Updates & Fixed CVEs
- Rebuilt base image on Debian trixie (`debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad`).
- Nginx upgraded from 1.22.1 to 1.31.8 (upstream mainline) fixing CVE-2026-97205, CVE-2026-93479, and CVE-2026-15176.
- OpenSSL updated to 3.5.7-1~deb13u3 carrying fixes for CCCS AV26-980 (CVE-2026-84782, CVE-2026-35189, CVE-2026-35191, CVE-2026-54872, CVE-2026-54875, CVE-2026-72897, CVE-2026-75804, CVE-2026-75805, CVE-2026-75806, CVE-2026-77696, and CVE-2026-84784).
- Runtime packages updated: Python 3.13, Postfix 3.10.1, Dovecot 2.4.1.
- Updated npm dependencies fixing brace-expansion vulnerability (CVE-2026-14257, GHSA-rgw5-rvv9-x895) and @humanfs/node. Python dependencies verified clean via pip-audit.
- Added middleware enforcing identity Content-Encoding on HTTP requests, rejecting non-identity encodings with HTTP 415.
- Sanitized IMAP folder names against carriage return, line feed, and null byte injection in emails service.
- Prevented path traversal in Dovecot user Maildir path resolution.
- Sanitized Content-Disposition attachment filenames to prevent HTTP response header injection.

### Container Hardening
- Implemented read-only root filesystem support (`read_only: true`).
- Configured tmpfs mounts for `/tmp`, `/run`, `/var/run`, `/var/log`, `/var/spool/postfix`, `/var/lib/postfix`, `/var/lib/spamassassin`, and configuration directories.
- Bundled configuration templates into `/usr/share/mailcue/config/` to seed tmpfs configuration mounts at boot time.
- Dropped all capabilities by default (`cap_drop: [ALL]`), retaining only the minimal necessary capabilities (`NET_BIND_SERVICE`, `CHOWN`, `DAC_OVERRIDE`, `SETUID`, `SETGID`, `FOWNER`, `SYS_CHROOT`).
- Enabled `no-new-privileges:true`.
- Multi-stage build for SQLCipher 4.6.1, completely omitting build-essential, gcc, make, and compilers from the runtime image.
- Services drop privileges after initialization: Postfix and Dovecot drop root privileges to unprivileged worker accounts; OpenDKIM runs as `opendkim`; OpenDMARC runs as `opendmarc`; SpamAssassin runs as `debian-spamd`; Nginx workers run as `nginx`.
- Added container HEALTHCHECK via `/api/v1/health`.

### Bug Fixes
- Fixed catch-all mailbox reassignment bug: mailboxes reassigned to another login retain their `is_catchall` flag. Added regression test coverage.
