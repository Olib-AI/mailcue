#!/usr/bin/env bash
# =============================================================================
# Validates the CI example pattern against a running MailCue instance.
# This exercises the exact auth → API key → inject → verify flow that
# all CI examples use, proving the pattern works end-to-end.
#
# Usage:   ./examples/ci/validate-examples.sh [BASE_URL]
# Default: http://localhost:8088
# =============================================================================

set -eo pipefail

BASE_URL="${1:-http://localhost:8088}"
API="${BASE_URL}/api/v1"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

PASS=0
FAIL=0

pass() { PASS=$((PASS + 1)); echo -e "  ${GREEN}PASS${NC} $1"; }
fail() { FAIL=$((FAIL + 1)); echo -e "  ${RED}FAIL${NC} $1"; [ "${2:-}" ] && echo -e "       ${RED}$2${NC}"; }

echo -e "\n${CYAN}${BOLD}━━━ Validating CI example pattern ━━━${NC}\n"

# 1. Health check (all examples start with this)
echo -e "${CYAN}Step 1: Health check${NC}"
for i in $(seq 1 30); do
  if curl -sf "${API}/health" > /dev/null 2>&1; then
    pass "Health check passed"
    break
  fi
  if [ "$i" = "30" ]; then fail "MailCue not reachable at ${BASE_URL}"; exit 1; fi
  sleep 2
done

# 2. Login (JWT token)
echo -e "${CYAN}Step 2: Login${NC}"
LOGIN_RESP=$(curl -sf -X POST "${API}/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"mailcue"}')
TOKEN=$(echo "$LOGIN_RESP" | jq -r '.access_token')
if [ -n "$TOKEN" ] && [ "$TOKEN" != "null" ]; then
  pass "Login successful (got JWT)"
else
  fail "Login failed" "$LOGIN_RESP"; exit 1
fi

# 3. Create API key (all examples create one for simpler auth)
echo -e "${CYAN}Step 3: Create API key${NC}"
KEY_RESP=$(curl -sf -X POST "${API}/auth/api-keys" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"ci-validation"}')
API_KEY=$(echo "$KEY_RESP" | jq -r '.key')
if [ -n "$API_KEY" ] && [ "$API_KEY" != "null" ]; then
  pass "API key created (mc_...)"
else
  fail "API key creation failed" "$KEY_RESP"; exit 1
fi

# 4. Inject email (the core operation in every CI example)
echo -e "${CYAN}Step 4: Inject test email${NC}"
RUN_ID="$(date +%s)"
INJECT_RESP=$(curl -sf -w "\n%{http_code}" -X POST "${API}/emails/inject" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"mailbox\": \"admin@mailcue.local\",
    \"from_address\": \"ci-validation-${RUN_ID}@example.com\",
    \"to_addresses\": [\"admin@mailcue.local\"],
    \"subject\": \"CI Validation ${RUN_ID}\",
    \"html_body\": \"<h1>It works!</h1><p>Email testing from CI.</p>\"
  }")
INJECT_CODE=$(echo "$INJECT_RESP" | tail -1)
INJECT_BODY=$(echo "$INJECT_RESP" | sed '$d')
if [ "$INJECT_CODE" = "201" ]; then
  pass "Email injected (201)"
else
  fail "Inject failed (${INJECT_CODE})" "$INJECT_BODY"; exit 1
fi

# 5. Verify email arrived (all examples check this)
echo -e "${CYAN}Step 5: Verify email arrived${NC}"
LIST_RESP=$(curl -sf "${API}/emails?mailbox=admin@mailcue.local" \
  -H "X-API-Key: $API_KEY")
COUNT=$(echo "$LIST_RESP" | jq '.total')
if [ "$COUNT" -ge 1 ]; then
  pass "Email found in mailbox (total: ${COUNT})"
else
  fail "No emails found" "$LIST_RESP"; exit 1
fi

# 6. Search for the specific email by subject
echo -e "${CYAN}Step 6: Search by subject${NC}"
SEARCH_RESP=$(curl -sf "${API}/emails?mailbox=admin@mailcue.local&search=CI+Validation+${RUN_ID}" \
  -H "X-API-Key: $API_KEY")
SEARCH_COUNT=$(echo "$SEARCH_RESP" | jq '.total')
if [ "$SEARCH_COUNT" -ge 1 ]; then
  pass "Email found by subject search (total: ${SEARCH_COUNT})"
else
  fail "Email not found by search" "$SEARCH_RESP"
fi

# 7. Send email via SMTP (the other common pattern)
echo -e "${CYAN}Step 7: Send via SMTP API${NC}"
SEND_RESP=$(curl -sf -w "\n%{http_code}" -X POST "${API}/emails/send" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"from_address\": \"admin@mailcue.local\",
    \"to_addresses\": [\"admin@mailcue.local\"],
    \"subject\": \"SMTP Send Test ${RUN_ID}\",
    \"text_body\": \"Sent via SMTP API.\"
  }")
SEND_CODE=$(echo "$SEND_RESP" | tail -1)
if [ "$SEND_CODE" = "200" ] || [ "$SEND_CODE" = "201" ] || [ "$SEND_CODE" = "202" ]; then
  pass "Email sent via SMTP API (${SEND_CODE})"
else
  SEND_BODY=$(echo "$SEND_RESP" | sed '$d')
  fail "SMTP send failed (${SEND_CODE})" "$SEND_BODY"
fi

# Summary
TOTAL=$((PASS + FAIL))
echo -e "\n${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  Results: ${GREEN}${PASS} passed${NC}, ${RED}${FAIL} failed${NC}, ${TOTAL} total${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

[ "$FAIL" -eq 0 ] || exit 1
