#!/bin/sh
# SpamAssassin content filter for Postfix.
# Scans via spamc, re-injects on 10025 (no content_filter = no loop).
SENDER="$1"
shift

# Scan with spamc
TMPFILE=$(mktemp)
trap "rm -f $TMPFILE" EXIT
/usr/bin/spamc -f > "$TMPFILE"

# Build SMTP conversation for re-injection on 10025
{
  printf "EHLO localhost\r\n"
  sleep 0.1
  printf "MAIL FROM:<%s>\r\n" "$SENDER"
  sleep 0.1
  for R in "$@"; do
    printf "RCPT TO:<%s>\r\n" "$R"
    sleep 0.1
  done
  printf "DATA\r\n"
  sleep 0.1
  cat "$TMPFILE"
  printf "\r\n.\r\n"
  sleep 0.1
  printf "QUIT\r\n"
} | nc -w 5 127.0.0.1 10025 > /dev/null 2>&1

exit $?
