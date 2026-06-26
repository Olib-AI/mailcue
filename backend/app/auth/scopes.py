"""API-key permission scopes.

A scope is a ``resource:action`` string that gates one class of API
operation. An API key carries a set of granted scopes; an interactive
session (JWT / refresh cookie) is treated as holding every scope.

The wildcard ``"*"`` grants all scopes and is what legacy keys (created
before permissions existed) are backfilled with, preserving their
unrestricted behaviour.

Mailbox restriction (which mailboxes a key may touch) is handled
separately from scopes -- see ``APIKey.allowed_mailboxes`` and
``AuthContext`` in ``app.dependencies``.
"""

from __future__ import annotations

from dataclasses import dataclass

WILDCARD = "*"

# ── Email (message content, per-mailbox) ─────────────────────────
EMAIL_READ = "email:read"
EMAIL_SEND = "email:send"
EMAIL_DELETE = "email:delete"
EMAIL_VALIDATE = "email:validate"

# ── Mailbox (containers + organisation, per-mailbox) ─────────────
MAILBOX_READ = "mailbox:read"
MAILBOX_MANAGE = "mailbox:manage"

# ── GPG keys ─────────────────────────────────────────────────────
GPG_READ = "gpg:read"
GPG_MANAGE = "gpg:manage"

# ── Forwarding rules ─────────────────────────────────────────────
FORWARDING_READ = "forwarding:read"
FORWARDING_MANAGE = "forwarding:manage"

# ── Domains (admin) ──────────────────────────────────────────────
DOMAIN_READ = "domain:read"
DOMAIN_MANAGE = "domain:manage"

# ── Aliases (admin) ──────────────────────────────────────────────
ALIAS_READ = "alias:read"
ALIAS_MANAGE = "alias:manage"

# ── System / server settings (admin) ─────────────────────────────
SYSTEM_READ = "system:read"
SYSTEM_MANAGE = "system:manage"

# ── Tunnels (admin) ──────────────────────────────────────────────
TUNNEL_READ = "tunnel:read"
TUNNEL_MANAGE = "tunnel:manage"

# ── API key self-management ──────────────────────────────────────
APIKEY_READ = "apikey:read"
APIKEY_MANAGE = "apikey:manage"


@dataclass(frozen=True)
class ScopeDef:
    """Metadata for a single scope, used by the API and the UI."""

    value: str
    group: str
    label: str
    description: str
    admin_only: bool = False


# Ordered catalogue -- drives validation and the create-key UI.
SCOPES: tuple[ScopeDef, ...] = (
    ScopeDef(
        EMAIL_READ, "Email", "Read email", "List, search, and read messages and attachments."
    ),
    ScopeDef(EMAIL_SEND, "Email", "Send email", "Send new messages and replies."),
    ScopeDef(
        EMAIL_DELETE, "Email", "Delete email", "Delete messages, bulk-delete, and purge mailboxes."
    ),
    ScopeDef(
        EMAIL_VALIDATE,
        "Email",
        "Validate email",
        "Validate email addresses (DNS, MX, mailbox probe, disposable check).",
    ),
    ScopeDef(MAILBOX_READ, "Mailbox", "Read mailboxes", "List mailboxes and read their stats."),
    ScopeDef(
        MAILBOX_MANAGE,
        "Mailbox",
        "Manage mailboxes",
        "Create/delete mailboxes, edit signature and display name, flag and triage messages.",
    ),
    ScopeDef(GPG_READ, "GPG", "Read GPG keys", "List and export GPG keys."),
    ScopeDef(
        GPG_MANAGE, "GPG", "Manage GPG keys", "Generate, import, publish, and delete GPG keys."
    ),
    ScopeDef(FORWARDING_READ, "Forwarding", "Read forwarding", "List forwarding rules."),
    ScopeDef(
        FORWARDING_MANAGE,
        "Forwarding",
        "Manage forwarding",
        "Create, edit, test, and delete forwarding rules.",
    ),
    ScopeDef(APIKEY_READ, "API keys", "Read API keys", "List API keys."),
    ScopeDef(
        APIKEY_MANAGE,
        "API keys",
        "Manage API keys",
        "Create and revoke API keys (cannot exceed this key's own grants).",
    ),
    ScopeDef(
        DOMAIN_READ, "Domains", "Read domains", "List domains and DNS state.", admin_only=True
    ),
    ScopeDef(
        DOMAIN_MANAGE,
        "Domains",
        "Manage domains",
        "Create, delete, and verify domains.",
        admin_only=True,
    ),
    ScopeDef(ALIAS_READ, "Aliases", "Read aliases", "List aliases.", admin_only=True),
    ScopeDef(
        ALIAS_MANAGE,
        "Aliases",
        "Manage aliases",
        "Create, edit, and delete aliases.",
        admin_only=True,
    ),
    ScopeDef(
        SYSTEM_READ,
        "System",
        "Read system",
        "Read server settings and TLS status.",
        admin_only=True,
    ),
    ScopeDef(
        SYSTEM_MANAGE,
        "System",
        "Manage system",
        "Update server settings and upload TLS certificates.",
        admin_only=True,
    ),
    ScopeDef(
        TUNNEL_READ,
        "Tunnels",
        "Read tunnels",
        "List tunnels and client identity.",
        admin_only=True,
    ),
    ScopeDef(
        TUNNEL_MANAGE,
        "Tunnels",
        "Manage tunnels",
        "Create, edit, delete, and check tunnels.",
        admin_only=True,
    ),
)

ALL_SCOPES: tuple[str, ...] = tuple(s.value for s in SCOPES)
_VALID: frozenset[str] = frozenset(ALL_SCOPES) | {WILDCARD}


def is_valid_scope(scope: str) -> bool:
    """Return ``True`` if *scope* is a known scope or the wildcard."""
    return scope in _VALID


def normalize_scopes(scopes: list[str] | None) -> list[str]:
    """Validate and de-duplicate a requested scope list.

    ``None`` or an empty list defaults to ``["*"]`` (full access), so a
    key created without an explicit scope choice keeps the historical
    unrestricted behaviour. Unknown scopes raise ``ValueError``.
    The returned list preserves catalogue order (wildcard first).
    """
    if not scopes:
        return [WILDCARD]

    requested = set(scopes)
    unknown = sorted(s for s in requested if not is_valid_scope(s))
    if unknown:
        raise ValueError(f"Unknown scope(s): {', '.join(unknown)}")

    if WILDCARD in requested:
        return [WILDCARD]
    return [s for s in ALL_SCOPES if s in requested]


def scope_satisfied(granted: list[str], required: str) -> bool:
    """Return ``True`` when *granted* scopes satisfy *required*."""
    return WILDCARD in granted or required in granted


def is_subset(child: list[str], parent: list[str]) -> bool:
    """Return ``True`` if *child* grants no more than *parent*.

    Used to stop an API key from minting a key more powerful than itself.
    """
    if WILDCARD in parent:
        return True
    if WILDCARD in child:
        return False
    return set(child) <= set(parent)
