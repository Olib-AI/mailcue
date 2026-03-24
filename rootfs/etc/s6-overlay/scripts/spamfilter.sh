#!/bin/sh
# =============================================================================
# MailCue — SpamAssassin Filter Script
# Called by Postfix as a content_filter pipe transport.
# Scans the message with spamc and re-injects via Postfix sendmail
# to the 10025 listener (which has content_filter= empty to avoid loops).
# =============================================================================
SENDMAIL="/usr/sbin/sendmail -G -i -o 'receive_override_options=no_address_mappings'"

# Pipe stdin through spamc, then re-inject
/usr/bin/spamc -f | ${SENDMAIL} "$@"
exit $?
