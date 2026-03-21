#!/usr/bin/env bash
# =============================================================================
# MailCue — Core Email CI/CD E2E Tests
# Validates the full email workflow that CI/CD users depend on:
#   login → API key → create mailbox → inject email → list → search →
#   get detail → verify headers → bulk inject → delete → cleanup
#
# Usage:   ./tests/e2e-email-cicd.sh [BASE_URL]
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

# Helper that uses API key instead of JWT
API_KEY=""
http_key() {
  local method="$1" url="$2"
  shift 2
  CODE=$(curl -s -o "$_HTTP_TMP" -w "%{http_code}" -X "$method" "$url" \
    -H "X-API-Key: ${API_KEY}" \
    -H "Content-Type: application/json" \
    "$@") || true
  BODY=$(cat "$_HTTP_TMP")
}

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
# 0. HEALTH CHECK (no auth)
# =============================================================================
wait_ready

section "Health Check (no auth)"
CODE=$(curl -s -o "$_HTTP_TMP" -w "%{http_code}" "${API}/health") || true
BODY=$(cat "$_HTTP_TMP")
STATUS=$(echo "$BODY" | jq -r '.status')
if [ "$CODE" = "200" ]; then
  pass "Health check → 200"
else
  fail "Health check → expected 200, got ${CODE}" "$BODY"
fi
if [ "$STATUS" = "ok" ]; then
  pass "Health status = ok"
else
  fail "Health status expected ok, got ${STATUS}"
fi

# =============================================================================
# 1. LOGIN
# =============================================================================
section "Authentication"

http POST "${API}/auth/login" -d "{\"username\":\"${ADMIN_USER}\",\"password\":\"${ADMIN_PASS}\"}"
TOKEN=$(echo "$BODY" | jq -r '.access_token')
if [ -n "$TOKEN" ] && [ "$TOKEN" != "null" ]; then
  pass "Admin login → JWT obtained"
else
  fail "Admin login failed" "$BODY"
  summary
fi

# =============================================================================
# 2. API KEY
# =============================================================================
section "API Key Management"

http POST "${API}/auth/api-keys" -d "{\"name\":\"ci-e2e-${RUN_ID}\"}"
if [ "$CODE" = "201" ]; then
  pass "Create API key → 201"
else
  fail "Create API key → expected 201, got ${CODE}" "$BODY"
fi
API_KEY=$(echo "$BODY" | jq -r '.key')
KEY_ID=$(echo "$BODY" | jq -r '.id')
if echo "$API_KEY" | grep -q "^mc_"; then
  pass "API key has mc_ prefix"
else
  fail "API key missing mc_ prefix: ${API_KEY}"
fi

# Verify API key works
http_key GET "${API}/auth/me"
if [ "$CODE" = "200" ]; then
  pass "API key auth → 200 on /auth/me"
else
  fail "API key auth failed → ${CODE}" "$BODY"
fi

# =============================================================================
# 3. MAILBOX MANAGEMENT
# =============================================================================
section "Mailbox Management"

MAILBOX_USER="citest-${RUN_ID}"
MAILBOX_ADDR="${MAILBOX_USER}@mailcue.local"

http POST "${API}/mailboxes" \
  -d "{\"username\":\"${MAILBOX_USER}\",\"password\":\"testpass1234\"}"
if [ "$CODE" = "201" ]; then
  pass "Create mailbox → 201"
else
  fail "Create mailbox → expected 201, got ${CODE}" "$BODY"
fi
CREATED_ADDR=$(echo "$BODY" | jq -r '.address')
if [ "$CREATED_ADDR" = "${MAILBOX_ADDR}" ]; then
  pass "Mailbox address = ${MAILBOX_ADDR}"
else
  fail "Mailbox address expected ${MAILBOX_ADDR}, got ${CREATED_ADDR}"
fi

# List mailboxes
http_key GET "${API}/mailboxes"
if [ "$CODE" = "200" ]; then
  pass "List mailboxes → 200"
else
  fail "List mailboxes → expected 200, got ${CODE}" "$BODY"
fi
MAILBOX_COUNT=$(echo "$BODY" | jq '.total')
if [ "$MAILBOX_COUNT" -gt 0 ]; then
  pass "Mailboxes found (count: ${MAILBOX_COUNT})"
else
  fail "No mailboxes found"
fi

# =============================================================================
# 4. EMAIL INJECTION
# =============================================================================
section "Email Injection"

SUBJECT="CI Test Email ${RUN_ID}"
http_key POST "${API}/emails/inject" \
  -d "{
    \"mailbox\": \"${MAILBOX_ADDR}\",
    \"from_address\": \"sender-${RUN_ID}@example.com\",
    \"to_addresses\": [\"${MAILBOX_ADDR}\"],
    \"subject\": \"${SUBJECT}\",
    \"html_body\": \"<h1>Hello CI</h1><p>Run ID: ${RUN_ID}</p>\",
    \"text_body\": \"Hello CI - Run ID: ${RUN_ID}\",
    \"realistic_headers\": true
  }"
if [ "$CODE" = "201" ]; then
  pass "Inject email → 201"
else
  fail "Inject email → expected 201, got ${CODE}" "$BODY"
fi
INJECTED_UID=$(echo "$BODY" | jq -r '.uid')
if [ -n "$INJECTED_UID" ] && [ "$INJECTED_UID" != "null" ]; then
  pass "Injected email UID: ${INJECTED_UID}"
else
  fail "Injected email UID missing"
fi

# Small delay for IMAP to index
sleep 1

# =============================================================================
# 5. LIST & SEARCH EMAILS
# =============================================================================
section "List & Search Emails"

# List all emails in mailbox
http_key GET "${API}/emails?mailbox=${MAILBOX_ADDR}&folder=INBOX"
if [ "$CODE" = "200" ]; then
  pass "List emails → 200"
else
  fail "List emails → expected 200, got ${CODE}" "$BODY"
fi
EMAIL_COUNT=$(echo "$BODY" | jq '.total')
if [ "$EMAIL_COUNT" -gt 0 ]; then
  pass "Emails in INBOX (count: ${EMAIL_COUNT})"
else
  fail "No emails in INBOX"
fi

# Search for the injected email by subject keyword
http_key GET "${API}/emails?mailbox=${MAILBOX_ADDR}&search=${RUN_ID}"
if [ "$CODE" = "200" ]; then
  pass "Search emails → 200"
else
  fail "Search emails → expected 200, got ${CODE}" "$BODY"
fi
SEARCH_COUNT=$(echo "$BODY" | jq '.total')
if [ "$SEARCH_COUNT" -gt 0 ]; then
  pass "Search found email (count: ${SEARCH_COUNT})"
else
  fail "Search found no emails for RUN_ID=${RUN_ID}"
fi

# Verify subject matches
FOUND_SUBJECT=$(echo "$BODY" | jq -r '.emails[0].subject')
if echo "$FOUND_SUBJECT" | grep -q "${RUN_ID}"; then
  pass "Found email subject contains RUN_ID"
else
  fail "Subject mismatch: ${FOUND_SUBJECT}"
fi

# =============================================================================
# 6. GET EMAIL DETAIL
# =============================================================================
section "Email Detail"

DETAIL_UID=$(echo "$BODY" | jq -r '.emails[0].uid')
http_key GET "${API}/emails/${DETAIL_UID}?mailbox=${MAILBOX_ADDR}&folder=INBOX"
if [ "$CODE" = "200" ]; then
  pass "Get email detail → 200"
else
  fail "Get email detail → expected 200, got ${CODE}" "$BODY"
fi

# Verify content
DETAIL_SUBJECT=$(echo "$BODY" | jq -r '.subject')
DETAIL_FROM=$(echo "$BODY" | jq -r '.from_address')
DETAIL_HTML=$(echo "$BODY" | jq -r '.html_body')
DETAIL_TEXT=$(echo "$BODY" | jq -r '.text_body')

if echo "$DETAIL_SUBJECT" | grep -q "${RUN_ID}"; then
  pass "Detail subject matches"
else
  fail "Detail subject mismatch: ${DETAIL_SUBJECT}"
fi
if echo "$DETAIL_FROM" | grep -q "sender-${RUN_ID}"; then
  pass "Detail from_address matches"
else
  fail "Detail from_address mismatch: ${DETAIL_FROM}"
fi
if echo "$DETAIL_HTML" | grep -q "Hello CI"; then
  pass "Detail html_body contains expected content"
else
  fail "Detail html_body mismatch"
fi
if echo "$DETAIL_TEXT" | grep -q "Hello CI"; then
  pass "Detail text_body contains expected content"
else
  fail "Detail text_body mismatch"
fi

# =============================================================================
# 7. VERIFY REALISTIC HEADERS
# =============================================================================
section "Realistic Headers"

RAW_HEADERS=$(echo "$BODY" | jq -r '.raw_headers')
if echo "$RAW_HEADERS" | jq -e '.Received' > /dev/null 2>&1; then
  pass "Received header present"
else
  fail "Received header missing from realistic headers"
fi
if echo "$RAW_HEADERS" | jq -e '."Authentication-Results"' > /dev/null 2>&1; then
  pass "Authentication-Results header present"
else
  fail "Authentication-Results header missing"
fi
if echo "$RAW_HEADERS" | jq -e '."Return-Path"' > /dev/null 2>&1; then
  pass "Return-Path header present"
else
  fail "Return-Path header missing"
fi

# =============================================================================
# 8. BULK INJECTION
# =============================================================================
section "Bulk Injection"

http_key POST "${API}/emails/bulk-inject" \
  -d "{\"emails\": [
    {
      \"mailbox\": \"${MAILBOX_ADDR}\",
      \"from_address\": \"bulk1@example.com\",
      \"to_addresses\": [\"${MAILBOX_ADDR}\"],
      \"subject\": \"Bulk 1 ${RUN_ID}\",
      \"text_body\": \"Bulk email 1\"
    },
    {
      \"mailbox\": \"${MAILBOX_ADDR}\",
      \"from_address\": \"bulk2@example.com\",
      \"to_addresses\": [\"${MAILBOX_ADDR}\"],
      \"subject\": \"Bulk 2 ${RUN_ID}\",
      \"text_body\": \"Bulk email 2\"
    },
    {
      \"mailbox\": \"${MAILBOX_ADDR}\",
      \"from_address\": \"bulk3@example.com\",
      \"to_addresses\": [\"${MAILBOX_ADDR}\"],
      \"subject\": \"Bulk 3 ${RUN_ID}\",
      \"text_body\": \"Bulk email 3\"
    }
  ]}"
if [ "$CODE" = "201" ]; then
  pass "Bulk inject → 201"
else
  fail "Bulk inject → expected 201, got ${CODE}" "$BODY"
fi
INJECTED_COUNT=$(echo "$BODY" | jq -r '.injected')
FAILED_COUNT=$(echo "$BODY" | jq -r '.failed')
if [ "$INJECTED_COUNT" = "3" ]; then
  pass "Bulk injected 3 emails"
else
  fail "Bulk injected expected 3, got ${INJECTED_COUNT}"
fi
if [ "$FAILED_COUNT" = "0" ]; then
  pass "Bulk inject 0 failures"
else
  fail "Bulk inject had ${FAILED_COUNT} failures"
fi

sleep 1

# Verify total count after bulk inject
http_key GET "${API}/emails?mailbox=${MAILBOX_ADDR}&folder=INBOX"
TOTAL_AFTER=$(echo "$BODY" | jq '.total')
if [ "$TOTAL_AFTER" -ge 4 ]; then
  pass "Total emails after bulk inject: ${TOTAL_AFTER}"
else
  fail "Expected ≥4 emails after bulk inject, got ${TOTAL_AFTER}"
fi

# =============================================================================
# 9. DELETE EMAIL
# =============================================================================
section "Delete Email"

http_key DELETE "${API}/emails/${DETAIL_UID}?mailbox=${MAILBOX_ADDR}&folder=INBOX"
if [ "$CODE" = "204" ]; then
  pass "Delete email → 204"
else
  fail "Delete email → expected 204, got ${CODE}" "$BODY"
fi

# =============================================================================
# 10. MAILBOX EMAILS ENDPOINT
# =============================================================================
section "Mailbox Emails Endpoint"

http_key GET "${API}/mailboxes/${MAILBOX_ADDR}/emails"
if [ "$CODE" = "200" ]; then
  pass "GET /mailboxes/{addr}/emails → 200"
else
  fail "GET /mailboxes/{addr}/emails → expected 200, got ${CODE}" "$BODY"
fi

# =============================================================================
# 11. CLEANUP
# =============================================================================
section "Cleanup"

# Revoke API key
http DELETE "${API}/auth/api-keys/${KEY_ID}"
if [ "$CODE" = "204" ]; then
  pass "Revoke API key → 204"
else
  fail "Revoke API key → expected 204, got ${CODE}" "$BODY"
fi

# Delete mailbox
http DELETE "${API}/mailboxes/${MAILBOX_ADDR}"
if [ "$CODE" = "204" ]; then
  pass "Delete mailbox → 204"
else
  fail "Delete mailbox → expected 204, got ${CODE}" "$BODY"
fi

# =============================================================================
summary
