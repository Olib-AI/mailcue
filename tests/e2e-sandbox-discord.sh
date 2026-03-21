#!/usr/bin/env bash
# =============================================================================
# MailCue — Sandbox Discord E2E Tests
# Validates: Discord Bot API sandbox endpoints (users/@me, send message,
#            edit message, delete message, get channel, list channels,
#            simulate inbound, send outbound)
#
# Usage:   ./tests/e2e-sandbox-discord.sh [BASE_URL]
# Default: http://localhost:8088
#
# Prerequisites:
#   - Running MailCue container (docker compose up -d)
#   - curl, jq
# =============================================================================

set -eo pipefail

BASE_URL="${1:-http://localhost:8088}"
API="${BASE_URL}/api/v1"
ADMIN_USER="admin"
ADMIN_PASS="mailcue"
RUN_ID="$(date +%s)"

# --- Colors & helpers --------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

PASS=0
FAIL=0
TOTAL=0

pass() {
  PASS=$((PASS + 1))
  TOTAL=$((TOTAL + 1))
  echo -e "  ${GREEN}PASS${NC} $1"
}

fail() {
  FAIL=$((FAIL + 1))
  TOTAL=$((TOTAL + 1))
  echo -e "  ${RED}FAIL${NC} $1"
  [ "${2:-}" ] && echo -e "       ${RED}$2${NC}"
}

section() {
  echo ""
  echo -e "${CYAN}${BOLD}━━━ $1 ━━━${NC}"
}

summary() {
  echo ""
  echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${BOLD}  Results: ${GREEN}${PASS} passed${NC}, ${RED}${FAIL} failed${NC}, ${TOTAL} total${NC}"
  echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  [ "$FAIL" -gt 0 ] && exit 1
  exit 0
}

# HTTP helper — sets global BODY and CODE variables.
TOKEN=""
BODY=""
CODE=""
_HTTP_TMP=$(mktemp)
trap 'rm -f "$_HTTP_TMP"' EXIT

http() {
  local method="$1" url="$2"
  shift 2
  CODE=$(curl -s -o "$_HTTP_TMP" -w "%{http_code}" -X "$method" "$url" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    "$@") || true
  BODY=$(cat "$_HTTP_TMP")
}

# Discord sandbox helper — uses Bot token auth
BOT_TOKEN=""
dc() {
  local method="$1" url="$2"
  shift 2
  CODE=$(curl -s -o "$_HTTP_TMP" -w "%{http_code}" -X "$method" "$url" \
    -H "Authorization: Bot ${BOT_TOKEN}" \
    -H "Content-Type: application/json" \
    "$@") || true
  BODY=$(cat "$_HTTP_TMP")
}

# Wait for service to be ready
wait_ready() {
  echo -e "${YELLOW}Waiting for MailCue at ${BASE_URL}...${NC}"
  local tries=0
  while ! curl -sf "${API}/health" >/dev/null 2>&1; do
    tries=$((tries + 1))
    [ "$tries" -ge 60 ] && { echo -e "${RED}Timeout waiting for MailCue${NC}"; exit 1; }
    sleep 2
  done
  echo -e "${GREEN}MailCue is ready${NC}"
}

# =============================================================================
# 0. SETUP
# =============================================================================
wait_ready

section "Login & Create Provider"
http POST "${API}/auth/login" -d "{\"username\":\"${ADMIN_USER}\",\"password\":\"${ADMIN_PASS}\"}"
TOKEN=$(echo "$BODY" | jq -r '.access_token')
if [ -n "$TOKEN" ] && [ "$TOKEN" != "null" ]; then
  pass "Admin login successful"
else
  fail "Admin login failed" "$BODY"
  summary
fi

BOT_TOKEN="dc-bot-token-${RUN_ID}"
APP_ID="1234567890"
PROVIDER_NAME="e2e-discord-${RUN_ID}"
DC_BASE="${BASE_URL}/sandbox/discord/api/v10"
CHANNEL_ID="general"
GUILD_ID="test-guild"

http POST "${API}/sandbox/providers" \
  -d "{\"provider_type\":\"discord\",\"name\":\"${PROVIDER_NAME}\",\"credentials\":{\"bot_token\":\"${BOT_TOKEN}\",\"application_id\":\"${APP_ID}\"}}"
if [ "$CODE" = "201" ]; then
  pass "Create discord provider → 201"
else
  fail "Create discord provider → expected 201, got ${CODE}" "$BODY"
  summary
fi
PROVIDER_ID=$(echo "$BODY" | jq -r '.id')

# =============================================================================
# 1. Get Bot User (@me)
# =============================================================================
section "Get Bot User"

dc GET "${DC_BASE}/users/@me"
IS_BOT=$(echo "$BODY" | jq -r '.bot')
USERNAME=$(echo "$BODY" | jq -r '.username')
if [ "$CODE" = "200" ]; then
  pass "GET users/@me → 200"
else
  fail "GET users/@me → expected 200, got ${CODE}" "$BODY"
fi
if [ "$IS_BOT" = "true" ]; then
  pass "Bot user → bot:true"
else
  fail "Bot user → bot expected true, got ${IS_BOT}"
fi
if [ "$USERNAME" = "${PROVIDER_NAME}" ]; then
  pass "Bot user → username matches provider name"
else
  fail "Bot user → username expected ${PROVIDER_NAME}, got ${USERNAME}"
fi

# Invalid token
dc_invalid() {
  CODE=$(curl -s -o "$_HTTP_TMP" -w "%{http_code}" -X "$1" "$2" \
    -H "Authorization: Bot INVALID-TOKEN" \
    -H "Content-Type: application/json" \
    "${@:3}") || true
  BODY=$(cat "$_HTTP_TMP")
}

dc_invalid GET "${DC_BASE}/users/@me"
ERR_MSG=$(echo "$BODY" | jq -r '.detail.message // .message // empty')
if [ "$CODE" = "401" ]; then
  pass "Invalid token → 401"
else
  fail "Invalid token → expected 401, got ${CODE}" "$BODY"
fi

# =============================================================================
# 2. Send Message
# =============================================================================
section "Send Message"

dc POST "${DC_BASE}/channels/${CHANNEL_ID}/messages" \
  -d "{\"content\":\"Hello e2e ${RUN_ID}\"}"
MSG_CONTENT=$(echo "$BODY" | jq -r '.content')
MSG_ID=$(echo "$BODY" | jq -r '.id')
MSG_CHANNEL=$(echo "$BODY" | jq -r '.channel_id')
if [ "$CODE" = "200" ]; then
  pass "Send message → 200"
else
  fail "Send message → expected 200, got ${CODE}" "$BODY"
fi
if [ "$MSG_CONTENT" = "Hello e2e ${RUN_ID}" ]; then
  pass "Message content matches"
else
  fail "Message content mismatch: ${MSG_CONTENT}"
fi
if [ -n "$MSG_ID" ] && [ "$MSG_ID" != "null" ]; then
  pass "Message has ID: ${MSG_ID}"
else
  fail "Message ID missing"
fi
if [ -n "$MSG_CHANNEL" ] && [ "$MSG_CHANNEL" != "null" ]; then
  pass "Message has channel_id"
else
  fail "Message channel_id missing"
fi
SENT_CHANNEL_ID="$MSG_CHANNEL"

# =============================================================================
# 3. Send Message with Embeds
# =============================================================================
section "Send Message with Embeds"

dc POST "${DC_BASE}/channels/${CHANNEL_ID}/messages" \
  -d "{\"content\":\"Embed test ${RUN_ID}\",\"embeds\":[{\"title\":\"Test\",\"description\":\"embed body\"}]}"
EMBED_COUNT=$(echo "$BODY" | jq '.embeds | length')
if [ "$CODE" = "200" ]; then
  pass "Send embed message → 200"
else
  fail "Send embed message → expected 200, got ${CODE}" "$BODY"
fi
if [ "$EMBED_COUNT" = "1" ]; then
  pass "Embed present in response"
else
  fail "Embed count expected 1, got ${EMBED_COUNT}"
fi

# =============================================================================
# 4. Edit Message
# =============================================================================
section "Edit Message"

dc PATCH "${DC_BASE}/channels/${SENT_CHANNEL_ID}/messages/${MSG_ID}" \
  -d "{\"content\":\"Edited e2e ${RUN_ID}\"}"
EDITED=$(echo "$BODY" | jq -r '.content')
EDITED_AT=$(echo "$BODY" | jq -r '.edited_timestamp')
if [ "$CODE" = "200" ]; then
  pass "Edit message → 200"
else
  fail "Edit message → expected 200, got ${CODE}" "$BODY"
fi
if [ "$EDITED" = "Edited e2e ${RUN_ID}" ]; then
  pass "Edited content matches"
else
  fail "Edited content mismatch: ${EDITED}"
fi
if [ "$EDITED_AT" != "null" ] && [ -n "$EDITED_AT" ]; then
  pass "edited_timestamp present"
else
  fail "edited_timestamp missing"
fi

# =============================================================================
# 5. Delete Message
# =============================================================================
section "Delete Message"

# Send a new message to delete
dc POST "${DC_BASE}/channels/${CHANNEL_ID}/messages" \
  -d "{\"content\":\"to-delete-${RUN_ID}\"}"
DEL_MSG_ID=$(echo "$BODY" | jq -r '.id')
DEL_CH_ID=$(echo "$BODY" | jq -r '.channel_id')

dc DELETE "${DC_BASE}/channels/${DEL_CH_ID}/messages/${DEL_MSG_ID}"
if [ "$CODE" = "204" ]; then
  pass "Delete message → 204"
else
  fail "Delete message → expected 204, got ${CODE}" "$BODY"
fi

# =============================================================================
# 6. Get Channel
# =============================================================================
section "Get Channel"

dc GET "${DC_BASE}/channels/${SENT_CHANNEL_ID}"
CH_TYPE=$(echo "$BODY" | jq -r '.type')
if [ "$CODE" = "200" ]; then
  pass "Get channel → 200"
else
  fail "Get channel → expected 200, got ${CODE}" "$BODY"
fi
if [ "$CH_TYPE" = "0" ]; then
  pass "Channel type = 0 (text)"
else
  fail "Channel type expected 0, got ${CH_TYPE}"
fi

# =============================================================================
# 7. Get Channel Messages
# =============================================================================
section "Get Channel Messages"

dc GET "${DC_BASE}/channels/${SENT_CHANNEL_ID}/messages"
CH_MSG_COUNT=$(echo "$BODY" | jq 'length')
if [ "$CODE" = "200" ]; then
  pass "Get channel messages → 200"
else
  fail "Get channel messages → expected 200, got ${CODE}" "$BODY"
fi
if [ "$CH_MSG_COUNT" -gt 0 ]; then
  pass "Channel has messages (count: ${CH_MSG_COUNT})"
else
  fail "Channel has no messages"
fi

# =============================================================================
# 8. Simulate Inbound
# =============================================================================
section "Simulate Inbound"

http POST "${API}/sandbox/providers/${PROVIDER_ID}/simulate" \
  -d "{\"sender\":\"dc-user-${RUN_ID}\",\"content\":\"Inbound msg ${RUN_ID}\",\"content_type\":\"text\"}"
if [ "$CODE" = "201" ]; then
  pass "Simulate inbound → 201"
else
  fail "Simulate inbound → expected 201, got ${CODE}" "$BODY"
fi
SIM_DIR=$(echo "$BODY" | jq -r '.direction')
if [ "$SIM_DIR" = "inbound" ]; then
  pass "Simulate direction = inbound"
else
  fail "Simulate direction expected inbound, got ${SIM_DIR}"
fi

# =============================================================================
# 9. Send Outbound (User Message)
# =============================================================================
section "Send Outbound Message"

http POST "${API}/sandbox/providers/${PROVIDER_ID}/send" \
  -d "{\"sender\":\"dc-user-${RUN_ID}\",\"content\":\"User reply ${RUN_ID}\",\"content_type\":\"text\"}"
if [ "$CODE" = "201" ]; then
  pass "Send outbound → 201"
else
  fail "Send outbound → expected 201, got ${CODE}" "$BODY"
fi
SEND_DIR=$(echo "$BODY" | jq -r '.direction')
if [ "$SEND_DIR" = "outbound" ]; then
  pass "Send direction = outbound"
else
  fail "Send direction expected outbound, got ${SEND_DIR}"
fi

# =============================================================================
# 10. Management API Verification
# =============================================================================
section "Management API Verification"

http GET "${API}/sandbox/messages?provider_id=${PROVIDER_ID}"
if [ "$CODE" = "200" ]; then
  pass "Messages endpoint → 200"
else
  fail "Messages endpoint → expected 200, got ${CODE}" "$BODY"
fi

MSG_COUNT=$(echo "$BODY" | jq '.messages | length')
if [ "$MSG_COUNT" -gt 0 ]; then
  pass "Messages visible in management API (count: ${MSG_COUNT})"
else
  fail "No messages found in management API"
fi

# Verify raw_request and raw_response are populated on outbound messages
OUTBOUND_REQ=$(echo "$BODY" | jq '[.messages[] | select(.direction=="outbound")][0].raw_request')
OUTBOUND_RES=$(echo "$BODY" | jq '[.messages[] | select(.direction=="outbound")][0].raw_response')
if [ "$OUTBOUND_REQ" != "{}" ] && [ "$OUTBOUND_REQ" != "null" ] && [ "$OUTBOUND_REQ" != "" ]; then
  pass "raw_request is populated"
else
  fail "raw_request is empty or null" "$OUTBOUND_REQ"
fi
if [ "$OUTBOUND_RES" != "{}" ] && [ "$OUTBOUND_RES" != "null" ] && [ "$OUTBOUND_RES" != "" ]; then
  pass "raw_response is populated"
else
  fail "raw_response is empty or null" "$OUTBOUND_RES"
fi

# =============================================================================
# 11. Cleanup
# =============================================================================
section "Cleanup"

http DELETE "${API}/sandbox/providers/${PROVIDER_ID}"
if [ "$CODE" = "204" ]; then
  pass "Delete provider → 204"
else
  fail "Delete provider → expected 204, got ${CODE}" "$BODY"
fi

# =============================================================================
summary
