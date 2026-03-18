#!/usr/bin/env bash
# =============================================================================
# MailCue — Forwarding Rules E2E Tests
# Validates: CRUD, dry-run test, webhook rule firing via HTTP Bin,
#            SMTP forward rule, disabled rule skip, non-matching skip,
#            regex pattern matching, edge cases
#
# Usage:   ./tests/e2e-forwarding-rules.sh [BASE_URL]
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
DOMAIN="mailcue.local"
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

# =============================================================================
# 1. CREATE MAILBOX
# =============================================================================
section "Create Mailbox"

MAILBOX_USER="fwd-e2e-${RUN_ID}"
MAILBOX_ADDR="${MAILBOX_USER}@${DOMAIN}"

http POST "${API}/mailboxes" \
  -d "{\"username\":\"${MAILBOX_USER}\",\"password\":\"testpass1234\"}"
if [ "$CODE" = "201" ]; then
  pass "Create mailbox → 201"
else
  fail "Create mailbox → expected 201, got ${CODE}" "$BODY"
fi

# =============================================================================
# 2. CREATE HTTP BIN
# =============================================================================
section "Create HTTP Bin"

http POST "${API}/httpbin/bins" \
  -d "{\"name\":\"fwd-e2e-bin-${RUN_ID}\",\"response_status_code\":200,\"response_body\":\"{\\\"ok\\\":true}\",\"response_content_type\":\"application/json\"}"
if [ "$CODE" = "201" ]; then
  pass "Create HTTP Bin → 201"
else
  fail "Create HTTP Bin → expected 201, got ${CODE}" "$BODY"
fi

BIN_ID=$(echo "$BODY" | jq -r '.id')
if [ -n "$BIN_ID" ] && [ "$BIN_ID" != "null" ]; then
  pass "HTTP Bin created (id: ${BIN_ID})"
else
  fail "HTTP Bin id missing"
fi

# The webhook URL that the forwarding rule will POST to.
# The backend runs inside a Docker container where nginx listens on port 80,
# so use the internal URL (localhost:80) instead of the host-mapped port.
WEBHOOK_URL="http://localhost:80/httpbin/${BIN_ID}"

# =============================================================================
# 3. FORWARDING RULE CRUD
# =============================================================================
section "Forwarding Rule — Create"

RULE_NAME="webhook-e2e-${RUN_ID}"
MATCH_SUBJECT="E2E-FWD-${RUN_ID}"

http POST "${API}/forwarding-rules" \
  -d "{
    \"name\": \"${RULE_NAME}\",
    \"enabled\": true,
    \"match_subject\": \"${MATCH_SUBJECT}\",
    \"match_mailbox\": \"${MAILBOX_ADDR}\",
    \"action_type\": \"webhook\",
    \"action_config\": {
      \"url\": \"${WEBHOOK_URL}\",
      \"method\": \"POST\",
      \"headers\": {\"X-Test\": \"forwarding-e2e\"}
    }
  }"
if [ "$CODE" = "201" ]; then
  pass "Create forwarding rule → 201"
else
  fail "Create forwarding rule → expected 201, got ${CODE}" "$BODY"
fi

RULE_ID=$(echo "$BODY" | jq -r '.id')
RULE_ENABLED=$(echo "$BODY" | jq -r '.enabled')
RULE_ACTION=$(echo "$BODY" | jq -r '.action_type')
RULE_MATCH_SUBJ=$(echo "$BODY" | jq -r '.match_subject')

if [ -n "$RULE_ID" ] && [ "$RULE_ID" != "null" ]; then
  pass "Rule id present: ${RULE_ID}"
else
  fail "Rule id missing"
fi
if [ "$RULE_ENABLED" = "true" ]; then
  pass "Rule enabled = true"
else
  fail "Rule enabled expected true, got ${RULE_ENABLED}"
fi
if [ "$RULE_ACTION" = "webhook" ]; then
  pass "Rule action_type = webhook"
else
  fail "Rule action_type expected webhook, got ${RULE_ACTION}"
fi
if [ "$RULE_MATCH_SUBJ" = "${MATCH_SUBJECT}" ]; then
  pass "Rule match_subject = ${MATCH_SUBJECT}"
else
  fail "Rule match_subject expected ${MATCH_SUBJECT}, got ${RULE_MATCH_SUBJ}"
fi

# --- Get rule by ID ---
section "Forwarding Rule — Get"

http GET "${API}/forwarding-rules/${RULE_ID}"
if [ "$CODE" = "200" ]; then
  pass "Get rule by id → 200"
else
  fail "Get rule by id → expected 200, got ${CODE}" "$BODY"
fi

GOT_NAME=$(echo "$BODY" | jq -r '.name')
if [ "$GOT_NAME" = "$RULE_NAME" ]; then
  pass "Get rule name matches"
else
  fail "Get rule name expected ${RULE_NAME}, got ${GOT_NAME}"
fi

# --- List rules ---
section "Forwarding Rule — List"

http GET "${API}/forwarding-rules"
if [ "$CODE" = "200" ]; then
  pass "List rules → 200"
else
  fail "List rules → expected 200, got ${CODE}" "$BODY"
fi

LIST_TOTAL=$(echo "$BODY" | jq -r '.total')
if [ "$LIST_TOTAL" -ge 1 ]; then
  pass "Rules found (total: ${LIST_TOTAL})"
else
  fail "Expected ≥1 rules, got ${LIST_TOTAL}"
fi

FOUND_IN_LIST=$(echo "$BODY" | jq -r "[.rules[] | select(.id == \"${RULE_ID}\")] | length")
if [ "$FOUND_IN_LIST" = "1" ]; then
  pass "Rule found in list by id"
else
  fail "Rule not found in list"
fi

# --- Update rule ---
section "Forwarding Rule — Update"

UPDATED_NAME="webhook-e2e-renamed-${RUN_ID}"
http PUT "${API}/forwarding-rules/${RULE_ID}" \
  -d "{\"name\": \"${UPDATED_NAME}\"}"
if [ "$CODE" = "200" ]; then
  pass "Update rule → 200"
else
  fail "Update rule → expected 200, got ${CODE}" "$BODY"
fi

UPD_NAME=$(echo "$BODY" | jq -r '.name')
if [ "$UPD_NAME" = "$UPDATED_NAME" ]; then
  pass "Rule renamed to ${UPDATED_NAME}"
else
  fail "Rule rename failed, got ${UPD_NAME}"
fi

# Verify other fields unchanged
UPD_ACTION=$(echo "$BODY" | jq -r '.action_type')
UPD_ENABLED=$(echo "$BODY" | jq -r '.enabled')
if [ "$UPD_ACTION" = "webhook" ]; then
  pass "Action type unchanged after update"
else
  fail "Action type changed after update: ${UPD_ACTION}"
fi
if [ "$UPD_ENABLED" = "true" ]; then
  pass "Enabled unchanged after update"
else
  fail "Enabled changed after update: ${UPD_ENABLED}"
fi

UPD_UPDATED_AT=$(echo "$BODY" | jq -r '.updated_at')
if [ -n "$UPD_UPDATED_AT" ] && [ "$UPD_UPDATED_AT" != "null" ]; then
  pass "updated_at is set after update"
else
  fail "updated_at not set after update"
fi

# Rename back for clarity in subsequent tests
http PUT "${API}/forwarding-rules/${RULE_ID}" \
  -d "{\"name\": \"${RULE_NAME}\"}"

# =============================================================================
# 4. DRY-RUN TEST ENDPOINT
# =============================================================================
section "Forwarding Rule — Dry-Run Test"

# Test with matching data
http POST "${API}/forwarding-rules/${RULE_ID}/test" \
  -d "{
    \"from_address\": \"sender@example.com\",
    \"to_address\": \"${MAILBOX_ADDR}\",
    \"subject\": \"${MATCH_SUBJECT} something\",
    \"mailbox\": \"${MAILBOX_ADDR}\"
  }"
if [ "$CODE" = "200" ]; then
  pass "Test rule (matching) → 200"
else
  fail "Test rule (matching) → expected 200, got ${CODE}" "$BODY"
fi

TEST_MATCHED=$(echo "$BODY" | jq -r '.matched')
if [ "$TEST_MATCHED" = "true" ]; then
  pass "Dry-run matched = true"
else
  fail "Dry-run expected matched=true, got ${TEST_MATCHED}" "$BODY"
fi

TEST_DETAIL_SUBJ=$(echo "$BODY" | jq -r '.match_details.match_subject')
if [ "$TEST_DETAIL_SUBJ" = "true" ]; then
  pass "match_details.match_subject = true"
else
  fail "match_details.match_subject expected true, got ${TEST_DETAIL_SUBJ}"
fi

# Test with non-matching data
http POST "${API}/forwarding-rules/${RULE_ID}/test" \
  -d "{
    \"from_address\": \"sender@example.com\",
    \"to_address\": \"${MAILBOX_ADDR}\",
    \"subject\": \"Unrelated subject line\",
    \"mailbox\": \"${MAILBOX_ADDR}\"
  }"
if [ "$CODE" = "200" ]; then
  pass "Test rule (non-matching) → 200"
else
  fail "Test rule (non-matching) → expected 200, got ${CODE}" "$BODY"
fi

TEST_MATCHED2=$(echo "$BODY" | jq -r '.matched')
if [ "$TEST_MATCHED2" = "false" ]; then
  pass "Dry-run non-matching = false"
else
  fail "Dry-run expected matched=false, got ${TEST_MATCHED2}" "$BODY"
fi

TEST_DETAIL_SUBJ2=$(echo "$BODY" | jq -r '.match_details.match_subject')
if [ "$TEST_DETAIL_SUBJ2" = "false" ]; then
  pass "match_details.match_subject = false for non-match"
else
  fail "match_details.match_subject expected false, got ${TEST_DETAIL_SUBJ2}"
fi

# =============================================================================
# 5. INJECT MATCHING EMAIL — VERIFY WEBHOOK FIRES
# =============================================================================
section "Webhook Rule — Inject Matching Email"

http POST "${API}/emails/inject" \
  -d "{
    \"mailbox\": \"${MAILBOX_ADDR}\",
    \"from_address\": \"sender-${RUN_ID}@example.com\",
    \"to_addresses\": [\"${MAILBOX_ADDR}\"],
    \"subject\": \"${MATCH_SUBJECT} important notification\",
    \"text_body\": \"This email should trigger the forwarding rule.\",
    \"realistic_headers\": true
  }"
if [ "$CODE" = "201" ]; then
  pass "Inject matching email → 201"
else
  fail "Inject matching email → expected 201, got ${CODE}" "$BODY"
fi

INJECT_UID=$(echo "$BODY" | jq -r '.uid')
if [ -n "$INJECT_UID" ] && [ "$INJECT_UID" != "null" ]; then
  pass "Injected email UID: ${INJECT_UID}"
else
  fail "Injected email UID missing"
fi

# Wait for async forwarding-rule processing
sleep 5

# Check HTTP Bin captured the webhook request
section "Webhook Rule — Verify HTTP Bin Capture"

http GET "${API}/httpbin/bins/${BIN_ID}/requests"
if [ "$CODE" = "200" ]; then
  pass "List bin requests → 200"
else
  fail "List bin requests → expected 200, got ${CODE}" "$BODY"
fi

BIN_REQ_TOTAL=$(echo "$BODY" | jq -r '.total')
if [ "$BIN_REQ_TOTAL" -ge 1 ]; then
  pass "HTTP Bin captured requests (total: ${BIN_REQ_TOTAL})"
else
  fail "HTTP Bin has no captured requests (expected ≥1)" "$BODY"
fi

# Verify the captured request contains the email data
BIN_REQ_METHOD=$(echo "$BODY" | jq -r '.requests[0].method')
BIN_REQ_BODY=$(echo "$BODY" | jq -r '.requests[0].body')

if [ "$BIN_REQ_METHOD" = "POST" ]; then
  pass "Captured request method = POST"
else
  fail "Captured request method expected POST, got ${BIN_REQ_METHOD}"
fi

# The webhook payload should contain the subject
if echo "$BIN_REQ_BODY" | grep -q "${MATCH_SUBJECT}"; then
  pass "Captured request body contains match subject"
else
  fail "Captured request body missing match subject" "$BIN_REQ_BODY"
fi

# Verify the custom header was sent
BIN_REQ_HEADERS=$(echo "$BODY" | jq -r '.requests[0].headers')
if echo "$BIN_REQ_HEADERS" | jq -e '."x-test"' > /dev/null 2>&1; then
  HEADER_VAL=$(echo "$BIN_REQ_HEADERS" | jq -r '."x-test"')
  if [ "$HEADER_VAL" = "forwarding-e2e" ]; then
    pass "Custom header x-test = forwarding-e2e"
  else
    fail "Custom header x-test expected forwarding-e2e, got ${HEADER_VAL}"
  fi
else
  fail "Custom header x-test missing from captured request"
fi

# =============================================================================
# 6. INJECT NON-MATCHING EMAIL — SHOULD NOT TRIGGER
# =============================================================================
section "Non-Matching Email — Should Not Trigger"

# Note: not clearing bin requests so they remain visible for inspection

# Record current request count before injecting non-matching email
http GET "${API}/httpbin/bins/${BIN_ID}/requests"
BEFORE_NON_MATCH=$(echo "$BODY" | jq -r '.total')

http POST "${API}/emails/inject" \
  -d "{
    \"mailbox\": \"${MAILBOX_ADDR}\",
    \"from_address\": \"other-${RUN_ID}@example.com\",
    \"to_addresses\": [\"${MAILBOX_ADDR}\"],
    \"subject\": \"Completely unrelated subject ${RUN_ID}\",
    \"text_body\": \"This should NOT trigger the forwarding rule.\"
  }"
if [ "$CODE" = "201" ]; then
  pass "Inject non-matching email → 201"
else
  fail "Inject non-matching email → expected 201, got ${CODE}" "$BODY"
fi

# Wait for async processing
sleep 5

# Verify no new requests in HTTP Bin
http GET "${API}/httpbin/bins/${BIN_ID}/requests"
NON_MATCH_TOTAL=$(echo "$BODY" | jq -r '.total')
if [ "$NON_MATCH_TOTAL" = "$BEFORE_NON_MATCH" ]; then
  pass "Non-matching email did not trigger webhook (count unchanged: ${NON_MATCH_TOTAL})"
else
  fail "Non-matching email unexpectedly triggered webhook (before=${BEFORE_NON_MATCH}, after=${NON_MATCH_TOTAL})"
fi

# =============================================================================
# 7. DISABLED RULE — SHOULD NOT TRIGGER
# =============================================================================
section "Disabled Rule — Should Not Trigger"

# Disable the rule
http PUT "${API}/forwarding-rules/${RULE_ID}" \
  -d '{"enabled": false}'
if [ "$CODE" = "200" ]; then
  pass "Disable rule → 200"
else
  fail "Disable rule → expected 200, got ${CODE}" "$BODY"
fi

DISABLED_STATE=$(echo "$BODY" | jq -r '.enabled')
if [ "$DISABLED_STATE" = "false" ]; then
  pass "Rule enabled = false"
else
  fail "Rule enabled expected false, got ${DISABLED_STATE}"
fi

# Note: not clearing bin requests so they remain visible for inspection

# Record current request count before injecting with disabled rule
http GET "${API}/httpbin/bins/${BIN_ID}/requests"
BEFORE_DISABLED=$(echo "$BODY" | jq -r '.total')

# Inject email that WOULD match if rule were enabled
http POST "${API}/emails/inject" \
  -d "{
    \"mailbox\": \"${MAILBOX_ADDR}\",
    \"from_address\": \"sender-${RUN_ID}@example.com\",
    \"to_addresses\": [\"${MAILBOX_ADDR}\"],
    \"subject\": \"${MATCH_SUBJECT} while disabled\",
    \"text_body\": \"This should NOT trigger because rule is disabled.\"
  }"
if [ "$CODE" = "201" ]; then
  pass "Inject email (disabled rule) → 201"
else
  fail "Inject email (disabled rule) → expected 201, got ${CODE}" "$BODY"
fi

# Wait for async processing
sleep 5

# Verify no new requests in HTTP Bin
http GET "${API}/httpbin/bins/${BIN_ID}/requests"
DISABLED_TOTAL=$(echo "$BODY" | jq -r '.total')
if [ "$DISABLED_TOTAL" = "$BEFORE_DISABLED" ]; then
  pass "Disabled rule did not trigger webhook (count unchanged: ${DISABLED_TOTAL})"
else
  fail "Disabled rule unexpectedly triggered webhook (before=${BEFORE_DISABLED}, after=${DISABLED_TOTAL})"
fi

# Re-enable the rule
http PUT "${API}/forwarding-rules/${RULE_ID}" \
  -d '{"enabled": true}'

# =============================================================================
# 8. SMTP FORWARD RULE (CRUD only — delivery within container)
# =============================================================================
section "SMTP Forward Rule"

SMTP_RULE_NAME="smtp-fwd-e2e-${RUN_ID}"
FORWARD_TO="forward-target-${RUN_ID}@${DOMAIN}"

http POST "${API}/forwarding-rules" \
  -d "{
    \"name\": \"${SMTP_RULE_NAME}\",
    \"enabled\": true,
    \"match_from\": \"vip-.*@example\\\\.com\",
    \"action_type\": \"smtp_forward\",
    \"action_config\": {
      \"to_address\": \"${FORWARD_TO}\"
    }
  }"
if [ "$CODE" = "201" ]; then
  pass "Create SMTP forward rule → 201"
else
  fail "Create SMTP forward rule → expected 201, got ${CODE}" "$BODY"
fi

SMTP_RULE_ID=$(echo "$BODY" | jq -r '.id')
SMTP_ACTION=$(echo "$BODY" | jq -r '.action_type')
SMTP_MATCH_FROM=$(echo "$BODY" | jq -r '.match_from')
SMTP_CONFIG_TO=$(echo "$BODY" | jq -r '.action_config.to_address')

if [ "$SMTP_ACTION" = "smtp_forward" ]; then
  pass "SMTP rule action_type = smtp_forward"
else
  fail "SMTP rule action_type expected smtp_forward, got ${SMTP_ACTION}"
fi
if echo "$SMTP_MATCH_FROM" | grep -q "vip-"; then
  pass "SMTP rule match_from contains regex pattern"
else
  fail "SMTP rule match_from mismatch: ${SMTP_MATCH_FROM}"
fi
if [ "$SMTP_CONFIG_TO" = "$FORWARD_TO" ]; then
  pass "SMTP rule action_config.to_address = ${FORWARD_TO}"
else
  fail "SMTP rule to_address expected ${FORWARD_TO}, got ${SMTP_CONFIG_TO}"
fi

# Dry-run test the SMTP rule
http POST "${API}/forwarding-rules/${SMTP_RULE_ID}/test" \
  -d "{
    \"from_address\": \"vip-user@example.com\",
    \"to_address\": \"${MAILBOX_ADDR}\",
    \"subject\": \"Important from VIP\",
    \"mailbox\": \"${MAILBOX_ADDR}\"
  }"
if [ "$CODE" = "200" ]; then
  pass "Test SMTP rule (matching) → 200"
else
  fail "Test SMTP rule (matching) → expected 200, got ${CODE}" "$BODY"
fi

SMTP_TEST_MATCHED=$(echo "$BODY" | jq -r '.matched')
if [ "$SMTP_TEST_MATCHED" = "true" ]; then
  pass "SMTP dry-run matched = true"
else
  fail "SMTP dry-run expected matched=true, got ${SMTP_TEST_MATCHED}"
fi

# Non-matching from_address
http POST "${API}/forwarding-rules/${SMTP_RULE_ID}/test" \
  -d "{
    \"from_address\": \"regular-user@example.com\",
    \"to_address\": \"${MAILBOX_ADDR}\",
    \"subject\": \"Regular email\",
    \"mailbox\": \"${MAILBOX_ADDR}\"
  }"
SMTP_TEST_NO_MATCH=$(echo "$BODY" | jq -r '.matched')
if [ "$SMTP_TEST_NO_MATCH" = "false" ]; then
  pass "SMTP dry-run non-matching = false"
else
  fail "SMTP dry-run expected matched=false, got ${SMTP_TEST_NO_MATCH}"
fi

# =============================================================================
# 9. VALIDATION — INVALID REGEX
# =============================================================================
section "Validation — Invalid Regex"

http POST "${API}/forwarding-rules" \
  -d "{
    \"name\": \"bad-regex-${RUN_ID}\",
    \"match_subject\": \"[invalid(regex\",
    \"action_type\": \"webhook\",
    \"action_config\": {\"url\": \"https://example.com/hook\"}
  }"
if [ "$CODE" = "422" ]; then
  pass "Invalid regex rejected → 422"
else
  fail "Invalid regex expected 422, got ${CODE}" "$BODY"
fi

# =============================================================================
# 10. VALIDATION — INVALID ACTION CONFIG
# =============================================================================
section "Validation — Invalid Action Config"

http POST "${API}/forwarding-rules" \
  -d "{
    \"name\": \"bad-config-${RUN_ID}\",
    \"action_type\": \"webhook\",
    \"action_config\": {\"missing_url_field\": true}
  }"
if [ "$CODE" = "422" ]; then
  pass "Invalid action config rejected → 422"
else
  fail "Invalid action config expected 422, got ${CODE}" "$BODY"
fi

# =============================================================================
# 11. GET NON-EXISTENT RULE
# =============================================================================
section "Get Non-Existent Rule"

http GET "${API}/forwarding-rules/00000000-0000-0000-0000-000000000000"
if [ "$CODE" = "404" ]; then
  pass "Get non-existent rule → 404"
else
  fail "Get non-existent rule → expected 404, got ${CODE}" "$BODY"
fi

# =============================================================================
# 12. DELETE RULES (skipped — leave rules for manual inspection)
# =============================================================================
section "Forwarding Rule — Delete"
echo "  Skipped — rules left intact for manual validation."
echo "  Webhook rule: ${RULE_ID}"
echo "  SMTP rule:    ${SMTP_RULE_ID}"

# =============================================================================
# 13. CLEANUP (skipped — leave resources for manual inspection)
# =============================================================================
section "Cleanup"
echo "  Skipped — HTTP Bin (${BIN_ID}), mailbox (${MAILBOX_ADDR}), and forwarding rules left intact for manual validation."

# =============================================================================
summary
