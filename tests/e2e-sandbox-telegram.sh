#!/usr/bin/env bash
# =============================================================================
# MailCue — Sandbox Telegram E2E Tests
# Validates: Telegram Bot API sandbox endpoints (getMe, sendMessage,
#            sendPhoto, sendDocument, editMessageText, deleteMessage,
#            setWebhook, getWebhookInfo, deleteWebhook, getUpdates)
#
# Usage:   ./tests/e2e-sandbox-telegram.sh [BASE_URL]
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

# Telegram sandbox helper — no Authorization header, token is in the URL
tg() {
  local method="$1" url="$2"
  shift 2
  CODE=$(curl -s -o "$_HTTP_TMP" -w "%{http_code}" -X "$method" "$url" \
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

BOT_TOKEN="tg-bot-token-${RUN_ID}"
PROVIDER_NAME="e2e-telegram-${RUN_ID}"
TG_BASE="${BASE_URL}/sandbox/telegram/bot${BOT_TOKEN}"
CHAT_ID=12345

http POST "${API}/sandbox/providers" \
  -d "{\"provider_type\":\"telegram\",\"name\":\"${PROVIDER_NAME}\",\"credentials\":{\"bot_token\":\"${BOT_TOKEN}\"}}"
if [ "$CODE" = "201" ]; then
  pass "Create telegram provider → 201"
else
  fail "Create telegram provider → expected 201, got ${CODE}" "$BODY"
  summary
fi
PROVIDER_ID=$(echo "$BODY" | jq -r '.id')

# =============================================================================
# 1. getMe
# =============================================================================
section "getMe"

tg POST "${TG_BASE}/getMe"
OK=$(echo "$BODY" | jq -r '.ok')
IS_BOT=$(echo "$BODY" | jq -r '.result.is_bot')
if [ "$OK" = "true" ]; then
  pass "getMe → ok:true"
else
  fail "getMe → ok expected true, got ${OK}" "$BODY"
fi
if [ "$IS_BOT" = "true" ]; then
  pass "getMe → is_bot:true"
else
  fail "getMe → is_bot expected true, got ${IS_BOT}"
fi

# getMe with invalid token
tg POST "${BASE_URL}/sandbox/telegram/botINVALID-TOKEN/getMe"
OK=$(echo "$BODY" | jq -r '.ok')
ERR_CODE=$(echo "$BODY" | jq -r '.error_code')
if [ "$OK" = "false" ]; then
  pass "getMe invalid token → ok:false"
else
  fail "getMe invalid token → ok expected false, got ${OK}"
fi
if [ "$ERR_CODE" = "401" ]; then
  pass "getMe invalid token → error_code:401"
else
  fail "getMe invalid token → error_code expected 401, got ${ERR_CODE}"
fi

# =============================================================================
# 2. sendMessage
# =============================================================================
section "sendMessage"

tg POST "${TG_BASE}/sendMessage" \
  -d "{\"chat_id\":${CHAT_ID},\"text\":\"Hello e2e ${RUN_ID}\"}"
OK=$(echo "$BODY" | jq -r '.ok')
MSG_TEXT=$(echo "$BODY" | jq -r '.result.text')
MSG_ID=$(echo "$BODY" | jq -r '.result.message_id')
if [ "$OK" = "true" ]; then
  pass "sendMessage → ok:true"
else
  fail "sendMessage → ok expected true, got ${OK}" "$BODY"
fi
if [ "$MSG_TEXT" = "Hello e2e ${RUN_ID}" ]; then
  pass "sendMessage → text matches"
else
  fail "sendMessage → text mismatch: ${MSG_TEXT}"
fi
if [ -n "$MSG_ID" ] && [ "$MSG_ID" != "null" ]; then
  pass "sendMessage → message_id present: ${MSG_ID}"
else
  fail "sendMessage → message_id missing"
fi
SENT_MSG_ID="$MSG_ID"

# =============================================================================
# 3. sendPhoto
# =============================================================================
section "sendPhoto"

CODE=$(curl -s -o "$_HTTP_TMP" -w "%{http_code}" -X POST "${TG_BASE}/sendPhoto" \
  -d "chat_id=${CHAT_ID}" -d "caption=photo-test-${RUN_ID}") || true
BODY=$(cat "$_HTTP_TMP")
OK=$(echo "$BODY" | jq -r '.ok')
if [ "$OK" = "true" ]; then
  pass "sendPhoto → ok:true"
else
  fail "sendPhoto → ok expected true, got ${OK}" "$BODY"
fi

# =============================================================================
# 4. sendDocument
# =============================================================================
section "sendDocument"

CODE=$(curl -s -o "$_HTTP_TMP" -w "%{http_code}" -X POST "${TG_BASE}/sendDocument" \
  -d "chat_id=${CHAT_ID}" -d "caption=doc-test-${RUN_ID}") || true
BODY=$(cat "$_HTTP_TMP")
OK=$(echo "$BODY" | jq -r '.ok')
if [ "$OK" = "true" ]; then
  pass "sendDocument → ok:true"
else
  fail "sendDocument → ok expected true, got ${OK}" "$BODY"
fi

# =============================================================================
# 5. editMessageText
# =============================================================================
section "editMessageText"

# Send a message first, then edit it
tg POST "${TG_BASE}/sendMessage" \
  -d "{\"chat_id\":${CHAT_ID},\"text\":\"original-${RUN_ID}\"}"
EDIT_MSG_ID=$(echo "$BODY" | jq -r '.result.message_id')

tg POST "${TG_BASE}/editMessageText" \
  -d "{\"chat_id\":${CHAT_ID},\"message_id\":${EDIT_MSG_ID},\"text\":\"edited-${RUN_ID}\"}"
OK=$(echo "$BODY" | jq -r '.ok')
EDITED_TEXT=$(echo "$BODY" | jq -r '.result.text')
if [ "$OK" = "true" ]; then
  pass "editMessageText → ok:true"
else
  fail "editMessageText → ok expected true, got ${OK}" "$BODY"
fi
if [ "$EDITED_TEXT" = "edited-${RUN_ID}" ]; then
  pass "editMessageText → text = edited-${RUN_ID}"
else
  fail "editMessageText → text mismatch: ${EDITED_TEXT}"
fi

# =============================================================================
# 6. deleteMessage
# =============================================================================
section "deleteMessage"

# Send a message first, then delete it
tg POST "${TG_BASE}/sendMessage" \
  -d "{\"chat_id\":${CHAT_ID},\"text\":\"to-delete-${RUN_ID}\"}"
DEL_MSG_ID=$(echo "$BODY" | jq -r '.result.message_id')

tg POST "${TG_BASE}/deleteMessage" \
  -d "{\"chat_id\":${CHAT_ID},\"message_id\":${DEL_MSG_ID}}"
OK=$(echo "$BODY" | jq -r '.ok')
RESULT=$(echo "$BODY" | jq -r '.result')
if [ "$OK" = "true" ]; then
  pass "deleteMessage → ok:true"
else
  fail "deleteMessage → ok expected true, got ${OK}" "$BODY"
fi
if [ "$RESULT" = "true" ]; then
  pass "deleteMessage → result:true"
else
  fail "deleteMessage → result expected true, got ${RESULT}"
fi

# =============================================================================
# 7. Webhook Management
# =============================================================================
section "Webhook Management"

WEBHOOK_URL="https://example.com/tg-webhook-${RUN_ID}"

# setWebhook
tg POST "${TG_BASE}/setWebhook" \
  -d "{\"url\":\"${WEBHOOK_URL}\"}"
OK=$(echo "$BODY" | jq -r '.ok')
DESC=$(echo "$BODY" | jq -r '.description')
if [ "$OK" = "true" ]; then
  pass "setWebhook → ok:true"
else
  fail "setWebhook → ok expected true, got ${OK}" "$BODY"
fi
if echo "$DESC" | grep -qi "Webhook was set"; then
  pass "setWebhook → description contains 'Webhook was set'"
else
  fail "setWebhook → description mismatch: ${DESC}"
fi

# getWebhookInfo
tg POST "${TG_BASE}/getWebhookInfo"
OK=$(echo "$BODY" | jq -r '.ok')
WH_URL=$(echo "$BODY" | jq -r '.result.url')
if [ "$OK" = "true" ]; then
  pass "getWebhookInfo → ok:true"
else
  fail "getWebhookInfo → ok expected true, got ${OK}" "$BODY"
fi
if [ "$WH_URL" = "$WEBHOOK_URL" ]; then
  pass "getWebhookInfo → url matches"
else
  fail "getWebhookInfo → url mismatch: ${WH_URL}"
fi

# deleteWebhook
tg POST "${TG_BASE}/deleteWebhook"
OK=$(echo "$BODY" | jq -r '.ok')
if [ "$OK" = "true" ]; then
  pass "deleteWebhook → ok:true"
else
  fail "deleteWebhook → ok expected true, got ${OK}" "$BODY"
fi

# getWebhookInfo after delete
tg POST "${TG_BASE}/getWebhookInfo"
WH_URL=$(echo "$BODY" | jq -r '.result.url')
if [ "$WH_URL" = "" ]; then
  pass "getWebhookInfo after delete → url is empty"
else
  fail "getWebhookInfo after delete → url expected empty, got ${WH_URL}"
fi

# =============================================================================
# 8. getUpdates (simulate inbound first)
# =============================================================================
section "getUpdates"

# Simulate inbound via management API
http POST "${API}/sandbox/providers/${PROVIDER_ID}/simulate" \
  -d "{\"sender\":\"tg-user-${RUN_ID}\",\"content\":\"inbound-msg-${RUN_ID}\",\"content_type\":\"text\"}"
if [ "$CODE" = "201" ]; then
  pass "Simulate inbound → 201"
else
  fail "Simulate inbound → expected 201, got ${CODE}" "$BODY"
fi

# getUpdates
tg POST "${TG_BASE}/getUpdates" -d '{}'
OK=$(echo "$BODY" | jq -r '.ok')
UPDATE_COUNT=$(echo "$BODY" | jq '.result | length')
if [ "$OK" = "true" ]; then
  pass "getUpdates → ok:true"
else
  fail "getUpdates → ok expected true, got ${OK}" "$BODY"
fi
if [ "$UPDATE_COUNT" -gt 0 ]; then
  pass "getUpdates → result array has ${UPDATE_COUNT} update(s)"
else
  fail "getUpdates → result array is empty"
fi

# =============================================================================
# 9. Send Outbound (User Message)
# =============================================================================
section "Send Outbound Message"

http POST "${API}/sandbox/providers/${PROVIDER_ID}/send" \
  -d "{\"sender\":\"tg-user-${RUN_ID}\",\"content\":\"User reply ${RUN_ID}\",\"content_type\":\"text\"}"
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
# 10. Verify via Management API
# =============================================================================
section "Management API Verification"

# Verify message visible
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
# 10. CLEANUP
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
