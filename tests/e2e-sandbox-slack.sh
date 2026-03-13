#!/usr/bin/env bash
# =============================================================================
# MailCue — Sandbox Slack E2E Tests
# Validates: Slack Web API sandbox endpoints (chat.postMessage, chat.update,
#            chat.delete, conversations.list/info/history, users.list/info)
#
# Usage:   ./tests/e2e-sandbox-slack.sh [BASE_URL]
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

# HTTP helper — sets global BODY and CODE variables (uses JWT auth).
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

# Slack sandbox helper — uses bot_token as Bearer auth
slack() {
  local method="$1" url="$2"
  shift 2
  CODE=$(curl -s -o "$_HTTP_TMP" -w "%{http_code}" -X "$method" "$url" \
    -H "Authorization: Bearer ${SLACK_BOT_TOKEN}" \
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

SLACK_BOT_TOKEN="xoxb-slack-token-${RUN_ID}"
PROVIDER_NAME="e2e-slack-${RUN_ID}"
SLACK_BASE="${BASE_URL}/sandbox/slack/api"
CHANNEL="C-e2e-${RUN_ID}"

http POST "${API}/sandbox/providers" \
  -d "{\"provider_type\":\"slack\",\"name\":\"${PROVIDER_NAME}\",\"credentials\":{\"bot_token\":\"${SLACK_BOT_TOKEN}\"}}"
if [ "$CODE" = "201" ]; then
  pass "Create slack provider → 201"
else
  fail "Create slack provider → expected 201, got ${CODE}" "$BODY"
  summary
fi
PROVIDER_ID=$(echo "$BODY" | jq -r '.id')

# =============================================================================
# 1. chat.postMessage
# =============================================================================
section "chat.postMessage"

slack POST "${SLACK_BASE}/chat.postMessage" \
  -d "{\"channel\":\"${CHANNEL}\",\"text\":\"Hello slack e2e ${RUN_ID}\"}"
OK=$(echo "$BODY" | jq -r '.ok')
CH=$(echo "$BODY" | jq -r '.channel')
TS=$(echo "$BODY" | jq -r '.ts')
MSG_TEXT=$(echo "$BODY" | jq -r '.message.text')
if [ "$OK" = "true" ]; then
  pass "chat.postMessage → ok:true"
else
  fail "chat.postMessage → ok expected true, got ${OK}" "$BODY"
fi
if [ "$CH" = "$CHANNEL" ]; then
  pass "chat.postMessage → channel matches"
else
  fail "chat.postMessage → channel mismatch: ${CH}"
fi
if [ -n "$TS" ] && [ "$TS" != "null" ]; then
  pass "chat.postMessage → ts present: ${TS}"
else
  fail "chat.postMessage → ts missing"
fi
if [ "$MSG_TEXT" = "Hello slack e2e ${RUN_ID}" ]; then
  pass "chat.postMessage → message.text matches"
else
  fail "chat.postMessage → message.text mismatch: ${MSG_TEXT}"
fi
FIRST_TS="$TS"

# chat.postMessage with thread_ts
slack POST "${SLACK_BASE}/chat.postMessage" \
  -d "{\"channel\":\"${CHANNEL}\",\"text\":\"thread reply ${RUN_ID}\",\"thread_ts\":\"${FIRST_TS}\"}"
OK=$(echo "$BODY" | jq -r '.ok')
if [ "$OK" = "true" ]; then
  pass "chat.postMessage with thread_ts → ok:true"
else
  fail "chat.postMessage with thread_ts → ok expected true, got ${OK}" "$BODY"
fi

# =============================================================================
# 2. chat.update
# =============================================================================
section "chat.update"

# Post a message, then update it
slack POST "${SLACK_BASE}/chat.postMessage" \
  -d "{\"channel\":\"${CHANNEL}\",\"text\":\"original-${RUN_ID}\"}"
UPDATE_TS=$(echo "$BODY" | jq -r '.ts')

slack POST "${SLACK_BASE}/chat.update" \
  -d "{\"channel\":\"${CHANNEL}\",\"ts\":\"${UPDATE_TS}\",\"text\":\"updated-${RUN_ID}\"}"
OK=$(echo "$BODY" | jq -r '.ok')
UPDATED_TEXT=$(echo "$BODY" | jq -r '.message.text')
if [ "$OK" = "true" ]; then
  pass "chat.update → ok:true"
else
  fail "chat.update → ok expected true, got ${OK}" "$BODY"
fi
if [ "$UPDATED_TEXT" = "updated-${RUN_ID}" ]; then
  pass "chat.update → message.text = updated-${RUN_ID}"
else
  fail "chat.update → message.text mismatch: ${UPDATED_TEXT}"
fi

# =============================================================================
# 3. chat.delete
# =============================================================================
section "chat.delete"

# Post a message, then delete it
slack POST "${SLACK_BASE}/chat.postMessage" \
  -d "{\"channel\":\"${CHANNEL}\",\"text\":\"to-delete-${RUN_ID}\"}"
DEL_TS=$(echo "$BODY" | jq -r '.ts')

slack POST "${SLACK_BASE}/chat.delete" \
  -d "{\"channel\":\"${CHANNEL}\",\"ts\":\"${DEL_TS}\"}"
OK=$(echo "$BODY" | jq -r '.ok')
RET_TS=$(echo "$BODY" | jq -r '.ts')
if [ "$OK" = "true" ]; then
  pass "chat.delete → ok:true"
else
  fail "chat.delete → ok expected true, got ${OK}" "$BODY"
fi
if [ "$RET_TS" = "$DEL_TS" ]; then
  pass "chat.delete → ts matches"
else
  fail "chat.delete → ts mismatch: ${RET_TS}"
fi

# =============================================================================
# 4. conversations.list
# =============================================================================
section "conversations.list"

slack GET "${SLACK_BASE}/conversations.list"
OK=$(echo "$BODY" | jq -r '.ok')
CH_COUNT=$(echo "$BODY" | jq '.channels | length')
if [ "$OK" = "true" ]; then
  pass "conversations.list → ok:true"
else
  fail "conversations.list → ok expected true, got ${OK}" "$BODY"
fi
if [ "$CH_COUNT" -gt 0 ]; then
  pass "conversations.list → channels array not empty (count: ${CH_COUNT})"
else
  fail "conversations.list → channels array is empty"
fi

# =============================================================================
# 5. conversations.info
# =============================================================================
section "conversations.info"

slack GET "${SLACK_BASE}/conversations.info?channel=${CHANNEL}"
OK=$(echo "$BODY" | jq -r '.ok')
CH_OBJ=$(echo "$BODY" | jq -r '.channel')
if [ "$OK" = "true" ]; then
  pass "conversations.info → ok:true"
else
  fail "conversations.info → ok expected true, got ${OK}" "$BODY"
fi
if [ "$CH_OBJ" != "null" ]; then
  pass "conversations.info → channel object present"
else
  fail "conversations.info → channel object missing"
fi

# conversations.info with nonexistent channel
slack GET "${SLACK_BASE}/conversations.info?channel=C-nonexistent-${RUN_ID}"
OK=$(echo "$BODY" | jq -r '.ok')
ERR=$(echo "$BODY" | jq -r '.error')
if [ "$OK" = "false" ]; then
  pass "conversations.info nonexistent → ok:false"
else
  fail "conversations.info nonexistent → ok expected false, got ${OK}"
fi
if [ "$ERR" = "channel_not_found" ]; then
  pass "conversations.info nonexistent → error=channel_not_found"
else
  fail "conversations.info nonexistent → error expected channel_not_found, got ${ERR}"
fi

# =============================================================================
# 6. conversations.history
# =============================================================================
section "conversations.history"

slack GET "${SLACK_BASE}/conversations.history?channel=${CHANNEL}"
OK=$(echo "$BODY" | jq -r '.ok')
MSGS=$(echo "$BODY" | jq '.messages')
if [ "$OK" = "true" ]; then
  pass "conversations.history → ok:true"
else
  fail "conversations.history → ok expected true, got ${OK}" "$BODY"
fi
if [ "$MSGS" != "null" ]; then
  pass "conversations.history → messages array present"
else
  fail "conversations.history → messages array missing"
fi

# =============================================================================
# 7. users.list
# =============================================================================
section "users.list"

slack GET "${SLACK_BASE}/users.list"
OK=$(echo "$BODY" | jq -r '.ok')
HAS_BOT=$(echo "$BODY" | jq '[.members[] | select(.is_bot == true)] | length')
if [ "$OK" = "true" ]; then
  pass "users.list → ok:true"
else
  fail "users.list → ok expected true, got ${OK}" "$BODY"
fi
if [ "$HAS_BOT" -gt 0 ]; then
  pass "users.list → members array has bot user"
else
  fail "users.list → no bot user in members"
fi

USER_ID=$(echo "$BODY" | jq -r '.members[0].id')

# =============================================================================
# 8. users.info
# =============================================================================
section "users.info"

slack GET "${SLACK_BASE}/users.info?user=${USER_ID}"
OK=$(echo "$BODY" | jq -r '.ok')
RET_USER_ID=$(echo "$BODY" | jq -r '.user.id')
if [ "$OK" = "true" ]; then
  pass "users.info → ok:true"
else
  fail "users.info → ok expected true, got ${OK}" "$BODY"
fi
if [ "$RET_USER_ID" = "$USER_ID" ]; then
  pass "users.info → user.id matches: ${USER_ID}"
else
  fail "users.info → user.id mismatch: ${RET_USER_ID}"
fi

# users.info with nonexistent user
slack GET "${SLACK_BASE}/users.info?user=U-nonexistent-${RUN_ID}"
OK=$(echo "$BODY" | jq -r '.ok')
ERR=$(echo "$BODY" | jq -r '.error')
if [ "$OK" = "false" ]; then
  pass "users.info nonexistent → ok:false"
else
  fail "users.info nonexistent → ok expected false, got ${OK}"
fi
if [ "$ERR" = "user_not_found" ]; then
  pass "users.info nonexistent → error=user_not_found"
else
  fail "users.info nonexistent → error expected user_not_found, got ${ERR}"
fi

# =============================================================================
# 9. Auth errors
# =============================================================================
section "Auth Errors"

# Invalid auth
CODE=$(curl -s -o "$_HTTP_TMP" -w "%{http_code}" -X POST "${SLACK_BASE}/chat.postMessage" \
  -H "Authorization: Bearer INVALID-TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"channel\":\"${CHANNEL}\",\"text\":\"should fail\"}") || true
BODY=$(cat "$_HTTP_TMP")
OK=$(echo "$BODY" | jq -r '.ok')
ERR=$(echo "$BODY" | jq -r '.error')
if [ "$OK" = "false" ]; then
  pass "Invalid auth → ok:false"
else
  fail "Invalid auth → ok expected false, got ${OK}"
fi
if [ "$ERR" = "invalid_auth" ]; then
  pass "Invalid auth → error=invalid_auth"
else
  fail "Invalid auth → error expected invalid_auth, got ${ERR}"
fi

# Missing auth
CODE=$(curl -s -o "$_HTTP_TMP" -w "%{http_code}" -X POST "${SLACK_BASE}/chat.postMessage" \
  -H "Content-Type: application/json" \
  -d "{\"channel\":\"${CHANNEL}\",\"text\":\"should fail\"}") || true
BODY=$(cat "$_HTTP_TMP")
OK=$(echo "$BODY" | jq -r '.ok')
ERR=$(echo "$BODY" | jq -r '.error')
if [ "$OK" = "false" ]; then
  pass "Missing auth → ok:false"
else
  fail "Missing auth → ok expected false, got ${OK}"
fi
if [ "$ERR" = "invalid_auth" ]; then
  pass "Missing auth → error=invalid_auth"
else
  fail "Missing auth → error expected invalid_auth, got ${ERR}"
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
# 11. Send Outbound (User Message)
# =============================================================================
section "Send Outbound Message"

http POST "${API}/sandbox/providers/${PROVIDER_ID}/send" \
  -d "{\"sender\":\"slack-user-${RUN_ID}\",\"content\":\"User reply ${RUN_ID}\",\"content_type\":\"text\"}"
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
# 12. CLEANUP
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
