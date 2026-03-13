#!/usr/bin/env bash
# =============================================================================
# MailCue — Sandbox Management API E2E Tests
# Validates: Provider CRUD, Simulate Inbound, Conversations, Messages,
#            Webhooks, Webhook Deliveries
#
# Usage:   ./tests/e2e-sandbox-management.sh [BASE_URL]
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

section "Login"
http POST "${API}/auth/login" -d "{\"username\":\"${ADMIN_USER}\",\"password\":\"${ADMIN_PASS}\"}"
TOKEN=$(echo "$BODY" | jq -r '.access_token')
if [ -n "$TOKEN" ] && [ "$TOKEN" != "null" ]; then
  pass "Admin login successful"
else
  fail "Admin login failed" "$BODY"
  summary
fi

PROVIDER_NAME="e2e-mgmt-${RUN_ID}"

# =============================================================================
# 1. PROVIDER CRUD
# =============================================================================
section "Provider CRUD"

# Create provider
http POST "${API}/sandbox/providers" \
  -d "{\"provider_type\":\"telegram\",\"name\":\"${PROVIDER_NAME}\",\"credentials\":{\"bot_token\":\"mgmt-token-${RUN_ID}\"}}"
if [ "$CODE" = "201" ]; then
  pass "Create provider → 201"
else
  fail "Create provider → expected 201, got ${CODE}" "$BODY"
fi

PROVIDER_ID=$(echo "$BODY" | jq -r '.id')
PROVIDER_TYPE=$(echo "$BODY" | jq -r '.provider_type')
PROVIDER_IS_ACTIVE=$(echo "$BODY" | jq -r '.is_active')

if [ "$PROVIDER_TYPE" = "telegram" ]; then
  pass "Provider type = telegram"
else
  fail "Provider type expected telegram, got ${PROVIDER_TYPE}"
fi

if [ "$PROVIDER_IS_ACTIVE" = "true" ]; then
  pass "Provider is_active = true"
else
  fail "Provider is_active expected true, got ${PROVIDER_IS_ACTIVE}"
fi

# List providers
http GET "${API}/sandbox/providers"
if [ "$CODE" = "200" ]; then
  pass "List providers → 200"
else
  fail "List providers → expected 200, got ${CODE}" "$BODY"
fi

FOUND=$(echo "$BODY" | jq -r "[.[] | select(.id == \"${PROVIDER_ID}\")] | length")
if [ "$FOUND" = "1" ]; then
  pass "Provider found in list"
else
  fail "Provider not found in list"
fi

# Get provider by id
http GET "${API}/sandbox/providers/${PROVIDER_ID}"
if [ "$CODE" = "200" ]; then
  pass "Get provider by id → 200"
else
  fail "Get provider by id → expected 200, got ${CODE}" "$BODY"
fi

SANDBOX_URL=$(echo "$BODY" | jq -r '.sandbox_url')
if [ -n "$SANDBOX_URL" ] && [ "$SANDBOX_URL" != "null" ]; then
  pass "sandbox_url present: ${SANDBOX_URL}"
else
  fail "sandbox_url missing"
fi

# Update provider (rename + deactivate)
NEW_NAME="e2e-mgmt-renamed-${RUN_ID}"
http PUT "${API}/sandbox/providers/${PROVIDER_ID}" \
  -d "{\"name\":\"${NEW_NAME}\",\"is_active\":false}"
if [ "$CODE" = "200" ]; then
  pass "Update provider → 200"
else
  fail "Update provider → expected 200, got ${CODE}" "$BODY"
fi

UPDATED_NAME=$(echo "$BODY" | jq -r '.name')
UPDATED_ACTIVE=$(echo "$BODY" | jq -r '.is_active')
if [ "$UPDATED_NAME" = "$NEW_NAME" ]; then
  pass "Provider renamed to ${NEW_NAME}"
else
  fail "Provider rename failed, got ${UPDATED_NAME}"
fi
if [ "$UPDATED_ACTIVE" = "false" ]; then
  pass "Provider deactivated"
else
  fail "Provider deactivation failed, got ${UPDATED_ACTIVE}"
fi

# Re-activate for further tests
http PUT "${API}/sandbox/providers/${PROVIDER_ID}" -d '{"is_active":true}'

# =============================================================================
# 2. SIMULATE INBOUND
# =============================================================================
section "Simulate Inbound"

http POST "${API}/sandbox/providers/${PROVIDER_ID}/simulate" \
  -d "{\"sender\":\"user-${RUN_ID}\",\"content\":\"Hello from e2e test ${RUN_ID}\",\"content_type\":\"text\"}"
if [ "$CODE" = "201" ]; then
  pass "Simulate inbound → 201"
else
  fail "Simulate inbound → expected 201, got ${CODE}" "$BODY"
fi

MSG_DIRECTION=$(echo "$BODY" | jq -r '.direction')
if [ "$MSG_DIRECTION" = "inbound" ]; then
  pass "Message direction = inbound"
else
  fail "Message direction expected inbound, got ${MSG_DIRECTION}"
fi

MSG_CONV_ID=$(echo "$BODY" | jq -r '.conversation_id')

# --- Send outbound (user message, triggers webhooks) ---
http POST "${API}/sandbox/providers/${PROVIDER_ID}/send" \
  -d "{\"sender\":\"e2e-user-${RUN_ID}\",\"content\":\"Outbound from e2e ${RUN_ID}\",\"content_type\":\"text\",\"conversation_id\":\"${MSG_CONV_ID}\"}"
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

SEND_CONV=$(echo "$BODY" | jq -r '.conversation_id')
if [ "$SEND_CONV" = "$MSG_CONV_ID" ]; then
  pass "Send uses same conversation"
else
  fail "Send conversation mismatch: expected ${MSG_CONV_ID}, got ${SEND_CONV}"
fi

# =============================================================================
# 3. CONVERSATIONS
# =============================================================================
section "Conversations"

http GET "${API}/sandbox/providers/${PROVIDER_ID}/conversations"
if [ "$CODE" = "200" ]; then
  pass "List conversations → 200"
else
  fail "List conversations → expected 200, got ${CODE}" "$BODY"
fi

CONV_COUNT=$(echo "$BODY" | jq 'length')
if [ "$CONV_COUNT" -gt 0 ]; then
  pass "Conversation created (count: ${CONV_COUNT})"
else
  fail "No conversations found"
fi

# =============================================================================
# 4. MESSAGES
# =============================================================================
section "Messages"

http GET "${API}/sandbox/messages?provider_id=${PROVIDER_ID}"
if [ "$CODE" = "200" ]; then
  pass "List messages → 200"
else
  fail "List messages → expected 200, got ${CODE}" "$BODY"
fi

MSG_COUNT=$(echo "$BODY" | jq '.messages | length')
if [ "$MSG_COUNT" -gt 0 ]; then
  pass "Message present (count: ${MSG_COUNT})"
else
  fail "No messages found"
fi

# =============================================================================
# 5. WEBHOOKS
# =============================================================================
section "Webhooks"

WEBHOOK_URL="https://example.com/webhook-${RUN_ID}"
http POST "${API}/sandbox/providers/${PROVIDER_ID}/webhooks" \
  -d "{\"url\":\"${WEBHOOK_URL}\",\"event_types\":[\"message\"]}"
if [ "$CODE" = "201" ]; then
  pass "Create webhook → 201"
else
  fail "Create webhook → expected 201, got ${CODE}" "$BODY"
fi

WEBHOOK_ID=$(echo "$BODY" | jq -r '.id')
WH_URL=$(echo "$BODY" | jq -r '.url')
if [ "$WH_URL" = "$WEBHOOK_URL" ]; then
  pass "Webhook url matches"
else
  fail "Webhook url mismatch: ${WH_URL}"
fi

# List webhooks
http GET "${API}/sandbox/providers/${PROVIDER_ID}/webhooks"
if [ "$CODE" = "200" ]; then
  pass "List webhooks → 200"
else
  fail "List webhooks → expected 200, got ${CODE}" "$BODY"
fi

WH_FOUND=$(echo "$BODY" | jq -r "[.[] | select(.id == \"${WEBHOOK_ID}\")] | length")
if [ "$WH_FOUND" = "1" ]; then
  pass "Webhook found in list"
else
  fail "Webhook not found in list"
fi

# Delete webhook
http DELETE "${API}/sandbox/webhooks/${WEBHOOK_ID}"
if [ "$CODE" = "204" ]; then
  pass "Delete webhook → 204"
else
  fail "Delete webhook → expected 204, got ${CODE}" "$BODY"
fi

# =============================================================================
# 6. WEBHOOK DELIVERIES
# =============================================================================
section "Webhook Deliveries"

http GET "${API}/sandbox/providers/${PROVIDER_ID}/webhook-deliveries"
if [ "$CODE" = "200" ]; then
  pass "List webhook deliveries → 200"
else
  fail "List webhook deliveries → expected 200, got ${CODE}" "$BODY"
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

# Verify deleted
http GET "${API}/sandbox/providers/${PROVIDER_ID}"
if [ "$CODE" = "404" ]; then
  pass "Get deleted provider → 404"
else
  fail "Get deleted provider → expected 404, got ${CODE}" "$BODY"
fi

# =============================================================================
summary
