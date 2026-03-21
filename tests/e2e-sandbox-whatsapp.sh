#!/usr/bin/env bash
# =============================================================================
# MailCue — Sandbox WhatsApp E2E Tests
# Validates: WhatsApp Cloud API sandbox endpoints (get phone number info,
#            send text message, send image message, mark as read)
#
# Usage:   ./tests/e2e-sandbox-whatsapp.sh [BASE_URL]
# Default: http://localhost:8088
#
# Prerequisites:
#   - Running MailCue container (docker compose up -d)
#   - curl, jq
# =============================================================================

set -euo pipefail

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

# WhatsApp sandbox helper — uses Bearer token auth in header
wa() {
  local method="$1" url="$2" wa_token="$3"
  shift 3
  CODE=$(curl -s -o "$_HTTP_TMP" -w "%{http_code}" -X "$method" "$url" \
    -H "Authorization: Bearer ${wa_token}" \
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

WA_TOKEN="test-wa-token-${RUN_ID}"
PHONE_NUMBER_ID="15551234567"
PROVIDER_NAME="e2e-whatsapp-${RUN_ID}"
WA_BASE="${BASE_URL}/sandbox/whatsapp/v1/${PHONE_NUMBER_ID}"

http POST "${API}/sandbox/providers" \
  -d "{\"provider_type\":\"whatsapp\",\"name\":\"${PROVIDER_NAME}\",\"credentials\":{\"access_token\":\"${WA_TOKEN}\",\"phone_number_id\":\"${PHONE_NUMBER_ID}\"}}"
if [ "$CODE" = "201" ]; then
  pass "Create whatsapp provider → 201"
else
  fail "Create whatsapp provider → expected 201, got ${CODE}" "$BODY"
  summary
fi
PROVIDER_ID=$(echo "$BODY" | jq -r '.id')

# =============================================================================
# 1. Get Phone Number Info
# =============================================================================
section "Get Phone Number Info"

wa GET "${WA_BASE}" "${WA_TOKEN}"
if [ "$CODE" = "200" ]; then
  pass "GET phone number info → 200"
else
  fail "GET phone number info → expected 200, got ${CODE}" "$BODY"
fi

# =============================================================================
# 2. Send Text Message
# =============================================================================
section "Send Text Message"

wa POST "${WA_BASE}/messages" "${WA_TOKEN}" \
  -d '{"messaging_product":"whatsapp","to":"15559876543","type":"text","text":{"body":"Hello from sandbox"}}'
if [ "$CODE" = "200" ]; then
  pass "Send text message → 200"
else
  fail "Send text message → expected 200, got ${CODE}" "$BODY"
fi

MSG_ARRAY=$(echo "$BODY" | jq '.messages')
if [ "$MSG_ARRAY" != "null" ] && [ "$(echo "$BODY" | jq '.messages | length')" -gt 0 ]; then
  pass "Send text message → response has messages array"
else
  fail "Send text message → response missing messages array" "$BODY"
fi

# =============================================================================
# 3. Send Image Message
# =============================================================================
section "Send Image Message"

wa POST "${WA_BASE}/messages" "${WA_TOKEN}" \
  -d '{"messaging_product":"whatsapp","to":"15559876543","type":"image","image":{"link":"https://example.com/photo.jpg"}}'
if [ "$CODE" = "200" ]; then
  pass "Send image message → 200"
else
  fail "Send image message → expected 200, got ${CODE}" "$BODY"
fi

# =============================================================================
# 4. Mark as Read
# =============================================================================
section "Mark as Read"

wa PUT "${WA_BASE}/messages/test-msg-id" "${WA_TOKEN}" \
  -d '{"messaging_product":"whatsapp","status":"read","message_id":"test-msg-id"}'
if [ "$CODE" = "200" ]; then
  pass "Mark as read → 200"
else
  fail "Mark as read → expected 200, got ${CODE}" "$BODY"
fi

# =============================================================================
# 5. Simulate Inbound
# =============================================================================
section "Simulate Inbound"

http POST "${API}/sandbox/providers/${PROVIDER_ID}/simulate" \
  -d "{\"sender\":\"wa-user-${RUN_ID}\",\"content\":\"inbound-msg-${RUN_ID}\",\"content_type\":\"text\"}"
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
# 6. Send Outbound
# =============================================================================
section "Send Outbound Message"

http POST "${API}/sandbox/providers/${PROVIDER_ID}/send" \
  -d "{\"sender\":\"wa-user-${RUN_ID}\",\"content\":\"User reply ${RUN_ID}\",\"content_type\":\"text\"}"
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
# 7. Management API Verification
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
# 8. Wrong Token Returns 401
# =============================================================================
section "Auth: Wrong Token"

wa POST "${WA_BASE}/messages" "INVALID-WA-TOKEN" \
  -d '{"messaging_product":"whatsapp","to":"15559876543","type":"text","text":{"body":"should fail"}}'
if [ "$CODE" = "401" ]; then
  pass "Wrong token → 401"
else
  fail "Wrong token → expected 401, got ${CODE}" "$BODY"
fi

# =============================================================================
# 9. Cleanup
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
