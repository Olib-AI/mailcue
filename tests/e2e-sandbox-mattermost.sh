#!/usr/bin/env bash
# =============================================================================
# MailCue — Sandbox Mattermost E2E Tests
# Validates: Mattermost API v4 sandbox endpoints (posts CRUD, channels,
#            users/me, auth errors)
#
# Usage:   ./tests/e2e-sandbox-mattermost.sh [BASE_URL]
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

# Mattermost sandbox helper — uses access_token as Bearer auth
mm() {
  local method="$1" url="$2"
  shift 2
  CODE=$(curl -s -o "$_HTTP_TMP" -w "%{http_code}" -X "$method" "$url" \
    -H "Authorization: Bearer ${MM_ACCESS_TOKEN}" \
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

MM_ACCESS_TOKEN="mm-token-${RUN_ID}"
PROVIDER_NAME="e2e-mattermost-${RUN_ID}"
MM_BASE="${BASE_URL}/sandbox/mattermost/api/v4"
CHANNEL_ID="ch-e2e-${RUN_ID}"

http POST "${API}/sandbox/providers" \
  -d "{\"provider_type\":\"mattermost\",\"name\":\"${PROVIDER_NAME}\",\"credentials\":{\"access_token\":\"${MM_ACCESS_TOKEN}\"}}"
if [ "$CODE" = "201" ]; then
  pass "Create mattermost provider → 201"
else
  fail "Create mattermost provider → expected 201, got ${CODE}" "$BODY"
  summary
fi
PROVIDER_ID=$(echo "$BODY" | jq -r '.id')

# =============================================================================
# 1. Create Post
# =============================================================================
section "Create Post"

mm POST "${MM_BASE}/posts" \
  -d "{\"channel_id\":\"${CHANNEL_ID}\",\"message\":\"Hello mattermost e2e ${RUN_ID}\"}"
if [ "$CODE" = "200" ]; then
  pass "Create post → 200"
else
  fail "Create post → expected 200, got ${CODE}" "$BODY"
fi

POST_MSG=$(echo "$BODY" | jq -r '.message')
POST_ID=$(echo "$BODY" | jq -r '.id')
CREATE_AT=$(echo "$BODY" | jq -r '.create_at')
if [ "$POST_MSG" = "Hello mattermost e2e ${RUN_ID}" ]; then
  pass "Create post → message matches"
else
  fail "Create post → message mismatch: ${POST_MSG}"
fi
if [ -n "$POST_ID" ] && [ "$POST_ID" != "null" ]; then
  pass "Create post → id present: ${POST_ID}"
else
  fail "Create post → id missing"
fi
if [ -n "$CREATE_AT" ] && [ "$CREATE_AT" != "null" ]; then
  pass "Create post → create_at present"
else
  fail "Create post → create_at missing"
fi

# Create post with root_id
mm POST "${MM_BASE}/posts" \
  -d "{\"channel_id\":\"${CHANNEL_ID}\",\"message\":\"thread reply ${RUN_ID}\",\"root_id\":\"${POST_ID}\"}"
if [ "$CODE" = "200" ]; then
  pass "Create post with root_id → 200"
else
  fail "Create post with root_id → expected 200, got ${CODE}" "$BODY"
fi

# =============================================================================
# 2. Get Post
# =============================================================================
section "Get Post"

mm GET "${MM_BASE}/posts/${POST_ID}"
if [ "$CODE" = "200" ]; then
  pass "Get post → 200"
else
  fail "Get post → expected 200, got ${CODE}" "$BODY"
fi

RET_ID=$(echo "$BODY" | jq -r '.id')
RET_MSG=$(echo "$BODY" | jq -r '.message')
if [ "$RET_ID" = "$POST_ID" ]; then
  pass "Get post → id matches"
else
  fail "Get post → id mismatch: ${RET_ID}"
fi
if [ "$RET_MSG" = "Hello mattermost e2e ${RUN_ID}" ]; then
  pass "Get post → message matches"
else
  fail "Get post → message mismatch: ${RET_MSG}"
fi

# Get nonexistent post
mm GET "${MM_BASE}/posts/nonexistent-post-${RUN_ID}"
if [ "$CODE" = "404" ]; then
  pass "Get nonexistent post → 404"
else
  fail "Get nonexistent post → expected 404, got ${CODE}" "$BODY"
fi

# =============================================================================
# 3. Update Post
# =============================================================================
section "Update Post"

mm PUT "${MM_BASE}/posts/${POST_ID}" \
  -d "{\"channel_id\":\"${CHANNEL_ID}\",\"message\":\"updated-${RUN_ID}\"}"
if [ "$CODE" = "200" ]; then
  pass "Update post → 200"
else
  fail "Update post → expected 200, got ${CODE}" "$BODY"
fi

UPDATED_MSG=$(echo "$BODY" | jq -r '.message')
if [ "$UPDATED_MSG" = "updated-${RUN_ID}" ]; then
  pass "Update post → message = updated-${RUN_ID}"
else
  fail "Update post → message mismatch: ${UPDATED_MSG}"
fi

# =============================================================================
# 4. Delete Post
# =============================================================================
section "Delete Post"

# Create a post to delete
mm POST "${MM_BASE}/posts" \
  -d "{\"channel_id\":\"${CHANNEL_ID}\",\"message\":\"to-delete-${RUN_ID}\"}"
DEL_POST_ID=$(echo "$BODY" | jq -r '.id')

mm DELETE "${MM_BASE}/posts/${DEL_POST_ID}"
if [ "$CODE" = "200" ]; then
  pass "Delete post → 200"
else
  fail "Delete post → expected 200, got ${CODE}" "$BODY"
fi

DEL_STATUS=$(echo "$BODY" | jq -r '.status')
if [ "$DEL_STATUS" = "OK" ]; then
  pass "Delete post → status = OK"
else
  fail "Delete post → status expected OK, got ${DEL_STATUS}"
fi

# Delete nonexistent post
mm DELETE "${MM_BASE}/posts/nonexistent-post-${RUN_ID}"
if [ "$CODE" = "404" ]; then
  pass "Delete nonexistent post → 404"
else
  fail "Delete nonexistent post → expected 404, got ${CODE}" "$BODY"
fi

# =============================================================================
# 5. Channels
# =============================================================================
section "Channels"

mm GET "${MM_BASE}/channels"
if [ "$CODE" = "200" ]; then
  pass "List channels → 200"
else
  fail "List channels → expected 200, got ${CODE}" "$BODY"
fi

CH_COUNT=$(echo "$BODY" | jq 'length')
if [ "$CH_COUNT" -gt 0 ]; then
  pass "List channels → array not empty (count: ${CH_COUNT})"
else
  fail "List channels → array is empty"
fi

# Get channel
mm GET "${MM_BASE}/channels/${CHANNEL_ID}"
if [ "$CODE" = "200" ]; then
  pass "Get channel → 200"
else
  fail "Get channel → expected 200, got ${CODE}" "$BODY"
fi

CH_ID=$(echo "$BODY" | jq -r '.id')
CH_NAME=$(echo "$BODY" | jq -r '.name')
if [ -n "$CH_ID" ] && [ "$CH_ID" != "null" ]; then
  pass "Get channel → id present"
else
  fail "Get channel → id missing"
fi
if [ -n "$CH_NAME" ] && [ "$CH_NAME" != "null" ]; then
  pass "Get channel → name present"
else
  fail "Get channel → name missing"
fi

# Get nonexistent channel
mm GET "${MM_BASE}/channels/nonexistent-ch-${RUN_ID}"
if [ "$CODE" = "404" ]; then
  pass "Get nonexistent channel → 404"
else
  fail "Get nonexistent channel → expected 404, got ${CODE}" "$BODY"
fi

# Get channel posts
mm GET "${MM_BASE}/channels/${CHANNEL_ID}/posts"
if [ "$CODE" = "200" ]; then
  pass "Get channel posts → 200"
else
  fail "Get channel posts → expected 200, got ${CODE}" "$BODY"
fi

ORDER=$(echo "$BODY" | jq '.order')
POSTS=$(echo "$BODY" | jq '.posts')
if [ "$ORDER" != "null" ]; then
  pass "Get channel posts → order array present"
else
  fail "Get channel posts → order array missing"
fi
if [ "$POSTS" != "null" ]; then
  pass "Get channel posts → posts object present"
else
  fail "Get channel posts → posts object missing"
fi

# =============================================================================
# 6. Users
# =============================================================================
section "Users"

mm GET "${MM_BASE}/users/me"
if [ "$CODE" = "200" ]; then
  pass "Get current user → 200"
else
  fail "Get current user → expected 200, got ${CODE}" "$BODY"
fi

USER_ID=$(echo "$BODY" | jq -r '.id')
USERNAME=$(echo "$BODY" | jq -r '.username')
if [ -n "$USER_ID" ] && [ "$USER_ID" != "null" ]; then
  pass "Get current user → id present: ${USER_ID}"
else
  fail "Get current user → id missing"
fi
if [ -n "$USERNAME" ] && [ "$USERNAME" != "null" ]; then
  pass "Get current user → username present: ${USERNAME}"
else
  fail "Get current user → username missing"
fi

# =============================================================================
# 7. Auth Errors
# =============================================================================
section "Auth Errors"

# Invalid auth
CODE=$(curl -s -o "$_HTTP_TMP" -w "%{http_code}" -X GET "${MM_BASE}/users/me" \
  -H "Authorization: Bearer INVALID-TOKEN" \
  -H "Content-Type: application/json") || true
BODY=$(cat "$_HTTP_TMP")
if [ "$CODE" = "401" ]; then
  pass "Invalid auth → 401"
else
  fail "Invalid auth → expected 401, got ${CODE}" "$BODY"
fi
STATUS_CODE=$(echo "$BODY" | jq -r '.status_code')
if [ "$STATUS_CODE" = "401" ]; then
  pass "Invalid auth → status_code:401"
else
  fail "Invalid auth → status_code expected 401, got ${STATUS_CODE}"
fi

# Missing auth
CODE=$(curl -s -o "$_HTTP_TMP" -w "%{http_code}" -X GET "${MM_BASE}/users/me" \
  -H "Content-Type: application/json") || true
BODY=$(cat "$_HTTP_TMP")
if [ "$CODE" = "401" ]; then
  pass "Missing auth → 401"
else
  fail "Missing auth → expected 401, got ${CODE}" "$BODY"
fi

# =============================================================================
# 8. Management API Verification
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
# 9. Send Outbound (User Message)
# =============================================================================
section "Send Outbound Message"

http POST "${API}/sandbox/providers/${PROVIDER_ID}/send" \
  -d "{\"sender\":\"mm-user-${RUN_ID}\",\"content\":\"User reply ${RUN_ID}\",\"content_type\":\"text\"}"
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
