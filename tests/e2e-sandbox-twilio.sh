#!/usr/bin/env bash
# =============================================================================
# MailCue — Sandbox Twilio E2E Tests
# Validates: Twilio REST API sandbox endpoints (send SMS, list messages,
#            get message, auth errors)
#
# Usage:   ./tests/e2e-sandbox-twilio.sh [BASE_URL]
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

# Twilio sandbox helper — uses HTTP Basic auth (account_sid:auth_token)
twilio() {
  local method="$1" url="$2"
  shift 2
  CODE=$(curl -s -o "$_HTTP_TMP" -w "%{http_code}" -X "$method" "$url" \
    -u "${ACCOUNT_SID}:${AUTH_TOKEN}" \
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

ACCOUNT_SID="AC${RUN_ID}e2etest00000000000000"
AUTH_TOKEN="authtoken-${RUN_ID}"
PROVIDER_NAME="e2e-twilio-${RUN_ID}"
TWILIO_BASE="${BASE_URL}/sandbox/twilio/2010-04-01/Accounts/${ACCOUNT_SID}"

http POST "${API}/sandbox/providers" \
  -d "{\"provider_type\":\"twilio\",\"name\":\"${PROVIDER_NAME}\",\"credentials\":{\"account_sid\":\"${ACCOUNT_SID}\",\"auth_token\":\"${AUTH_TOKEN}\"}}"
if [ "$CODE" = "201" ]; then
  pass "Create twilio provider → 201"
else
  fail "Create twilio provider → expected 201, got ${CODE}" "$BODY"
  summary
fi
PROVIDER_ID=$(echo "$BODY" | jq -r '.id')

# =============================================================================
# 1. Send SMS
# =============================================================================
section "Send SMS"

twilio POST "${TWILIO_BASE}/Messages.json" \
  -d "{\"From\":\"+15551234567\",\"To\":\"+15559876543\",\"Body\":\"Hello twilio e2e ${RUN_ID}\"}"
if [ "$CODE" = "200" ]; then
  pass "Send SMS → 200"
else
  fail "Send SMS → expected 200, got ${CODE}" "$BODY"
fi

SID=$(echo "$BODY" | jq -r '.sid')
SMS_BODY=$(echo "$BODY" | jq -r '.body')
SMS_STATUS=$(echo "$BODY" | jq -r '.status')
SMS_TO=$(echo "$BODY" | jq -r '.to')
if echo "$SID" | grep -q "^SM"; then
  pass "Send SMS → sid starts with SM: ${SID}"
else
  fail "Send SMS → sid does not start with SM: ${SID}"
fi
if [ "$SMS_BODY" = "Hello twilio e2e ${RUN_ID}" ]; then
  pass "Send SMS → body matches"
else
  fail "Send SMS → body mismatch: ${SMS_BODY}"
fi
if [ "$SMS_STATUS" = "queued" ] || [ "$SMS_STATUS" = "sent" ]; then
  pass "Send SMS → status=${SMS_STATUS}"
else
  fail "Send SMS → status expected queued or sent, got ${SMS_STATUS}"
fi
if [ "$SMS_TO" = "+15559876543" ]; then
  pass "Send SMS → to matches"
else
  fail "Send SMS → to mismatch: ${SMS_TO}"
fi
FIRST_SID="$SID"

# Send SMS with StatusCallback
twilio POST "${TWILIO_BASE}/Messages.json" \
  -d "{\"From\":\"+15551234567\",\"To\":\"+15559876543\",\"Body\":\"callback test ${RUN_ID}\",\"StatusCallback\":\"https://example.com/status\"}"
if [ "$CODE" = "200" ]; then
  pass "Send SMS with StatusCallback → 200"
else
  fail "Send SMS with StatusCallback → expected 200, got ${CODE}" "$BODY"
fi
CB_SID=$(echo "$BODY" | jq -r '.sid')
if echo "$CB_SID" | grep -q "^SM"; then
  pass "Send SMS with StatusCallback → sid starts with SM"
else
  fail "Send SMS with StatusCallback → sid does not start with SM: ${CB_SID}"
fi

# =============================================================================
# 2. List Messages
# =============================================================================
section "List Messages"

twilio GET "${TWILIO_BASE}/Messages.json"
if [ "$CODE" = "200" ]; then
  pass "List messages → 200"
else
  fail "List messages → expected 200, got ${CODE}" "$BODY"
fi

MSGS=$(echo "$BODY" | jq '.messages')
URI=$(echo "$BODY" | jq -r '.uri')
PAGE=$(echo "$BODY" | jq -r '.page')
if [ "$MSGS" != "null" ]; then
  pass "List messages → messages array present"
else
  fail "List messages → messages array missing"
fi
if [ -n "$URI" ] && [ "$URI" != "null" ]; then
  pass "List messages → uri present"
else
  fail "List messages → uri missing"
fi
if [ "$PAGE" != "null" ]; then
  pass "List messages → page present"
else
  fail "List messages → page missing"
fi

# =============================================================================
# 3. Get Single Message
# =============================================================================
section "Get Single Message"

twilio GET "${TWILIO_BASE}/Messages/${FIRST_SID}.json"
if [ "$CODE" = "200" ]; then
  pass "Get message → 200"
else
  fail "Get message → expected 200, got ${CODE}" "$BODY"
fi

RET_SID=$(echo "$BODY" | jq -r '.sid')
RET_BODY=$(echo "$BODY" | jq -r '.body')
if [ "$RET_SID" = "$FIRST_SID" ]; then
  pass "Get message → sid matches"
else
  fail "Get message → sid mismatch: ${RET_SID}"
fi
if [ "$RET_BODY" = "Hello twilio e2e ${RUN_ID}" ]; then
  pass "Get message → body matches"
else
  fail "Get message → body mismatch: ${RET_BODY}"
fi

# Get nonexistent message
twilio GET "${TWILIO_BASE}/Messages/SM0000nonexistent${RUN_ID}.json"
if [ "$CODE" = "404" ]; then
  pass "Get nonexistent message → 404"
else
  fail "Get nonexistent message → expected 404, got ${CODE}" "$BODY"
fi
ERR_CODE=$(echo "$BODY" | jq -r '.code')
if [ "$ERR_CODE" = "20404" ]; then
  pass "Get nonexistent message → code:20404"
else
  fail "Get nonexistent message → code expected 20404, got ${ERR_CODE}"
fi

# =============================================================================
# 4. Auth Errors
# =============================================================================
section "Auth Errors"

# Invalid auth (wrong auth_token)
CODE=$(curl -s -o "$_HTTP_TMP" -w "%{http_code}" -X GET "${TWILIO_BASE}/Messages.json" \
  -u "${ACCOUNT_SID}:WRONG-TOKEN" \
  -H "Content-Type: application/json") || true
BODY=$(cat "$_HTTP_TMP")
if [ "$CODE" = "401" ]; then
  pass "Invalid auth → 401"
else
  fail "Invalid auth → expected 401, got ${CODE}" "$BODY"
fi
ERR_CODE=$(echo "$BODY" | jq -r '.code')
if [ "$ERR_CODE" = "20003" ]; then
  pass "Invalid auth → code:20003"
else
  fail "Invalid auth → code expected 20003, got ${ERR_CODE}"
fi

# Missing auth
CODE=$(curl -s -o "$_HTTP_TMP" -w "%{http_code}" -X GET "${TWILIO_BASE}/Messages.json" \
  -H "Content-Type: application/json") || true
BODY=$(cat "$_HTTP_TMP")
if [ "$CODE" = "401" ]; then
  pass "Missing auth → 401"
else
  fail "Missing auth → expected 401, got ${CODE}" "$BODY"
fi

# Mismatched SID in URL
WRONG_SID="ACwrong${RUN_ID}000000000000000000"
CODE=$(curl -s -o "$_HTTP_TMP" -w "%{http_code}" -X GET \
  "${BASE_URL}/sandbox/twilio/2010-04-01/Accounts/${WRONG_SID}/Messages.json" \
  -u "${WRONG_SID}:${AUTH_TOKEN}" \
  -H "Content-Type: application/json") || true
BODY=$(cat "$_HTTP_TMP")
if [ "$CODE" = "401" ]; then
  pass "Mismatched SID → 401"
else
  fail "Mismatched SID → expected 401, got ${CODE}" "$BODY"
fi

# =============================================================================
# 5. Management API Verification
# =============================================================================
section "Management API Verification"

# Verify conversation created
http GET "${API}/sandbox/providers/${PROVIDER_ID}/conversations"
if [ "$CODE" = "200" ]; then
  pass "Conversations endpoint → 200"
else
  fail "Conversations endpoint → expected 200, got ${CODE}" "$BODY"
fi
CONV_COUNT=$(echo "$BODY" | jq 'length')
if [ "$CONV_COUNT" -gt 0 ]; then
  pass "Conversation created (count: ${CONV_COUNT})"
else
  fail "No conversations found"
fi

# Verify message in management API
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
# 6. Send Outbound (User Message)
# =============================================================================
section "Send Outbound Message"

http POST "${API}/sandbox/providers/${PROVIDER_ID}/send" \
  -d "{\"sender\":\"twilio-user-${RUN_ID}\",\"content\":\"User reply ${RUN_ID}\",\"content_type\":\"text\"}"
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
# 7. CLEANUP
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
