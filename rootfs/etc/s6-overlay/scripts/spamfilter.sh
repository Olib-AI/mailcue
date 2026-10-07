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
  # RFC 5321 4.5.2: dot-stuff the body. Postfix removed the client's stuffing before
  # handing the message over, so a line that starts with "." must be doubled again or
  # the re-injection loses that dot (and a lone "." line would end DATA early).
  sed 's/^\./../' "$TMPFILE"
  printf "\r\n.\r\n"
  sleep 0.1
  printf "QUIT\r\n"
} | nc -w 5 127.0.0.1 10025 > /dev/null 2>&1

exit $?
