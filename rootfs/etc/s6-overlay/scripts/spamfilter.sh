#!/bin/sh
# SpamAssassin content filter for Postfix.
# Scans via spamc, re-injects on 10025 (no content_filter = no loop).
set -eu

# EX_TEMPFAIL = 75 (sysexits.h) tells Postfix to defer mail on failure
EX_TEMPFAIL=75

SENDER="$1"
shift

TMPFILE=$(mktemp)
trap 'rm -f "$TMPFILE"' EXIT

# Scan with spamc
if ! /usr/bin/spamc -f > "$TMPFILE"; then
    echo "[spamfilter] ERROR: spamc scan failed" >&2
    exit $EX_TEMPFAIL
fi

# Re-inject message into Postfix on port 10025 using Python smtplib.
# This ensures we wait for the 220 banner before EHLO, verify 250 responses,
# and exit with EX_TEMPFAIL (75) on any failure so Postfix defers the message.
if ! python3 - "$TMPFILE" "$SENDER" "$@" << 'EOF'
import sys
import smtplib

mail_path = sys.argv[1]
sender = sys.argv[2]
recipients = sys.argv[3:]

with open(mail_path, "rb") as f:
    content = f.read()

try:
    with smtplib.SMTP("127.0.0.1", 10025, timeout=30) as client:
        client.sendmail(sender, recipients, content)
except Exception as exc:
    sys.stderr.write(f"[spamfilter] Re-injection failed: {exc}\n")
    sys.exit(75)
EOF
then
    exit $EX_TEMPFAIL
fi

exit 0
