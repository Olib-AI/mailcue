"""Receiving-provider classification derived from a domain's MX records.

Whether an SMTP accept-all response means anything is decided almost entirely
by who runs the destination mailbox. A security gateway that does not sync the
recipient directory accepts every address and lets the backend generate an
asynchronous bounce; a provider that answers honestly at RCPT only accept-alls
when the tenant deliberately configured a catch-all route. Classifying the MX
turns one undifferentiated ``catch_all`` bucket into buckets whose expected
bounce behaviour differs by an order of magnitude, without needing any
delivery history for the domain.

The ``accept_all_bounce_prior`` values set the prior mean of the beta-binomial
in ``validation_feedback`` and are progressively overridden by observed
outcomes once a domain or provider accumulates enough samples.

They were originally spread from 0.05 to 0.35 on reasoning about how each
receiver handles unknown recipients. Measurement against a 314-address cohort
contradicted that spread, most sharply for Google Workspace: its accept-all
domains bounced at 15.4%, not the 5% assumed, while the security gateways
assumed to be worst bounced at 8.7%. The range is now compressed around the
observed base rate, and discrimination is left to the probe evidence, which
carries it far better than the choice of provider does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ProviderCategory = Literal[
    "hosted_mailbox",
    "security_gateway",
    "consumer",
    "self_hosted",
    "forwarder",
    "parked",
    "unroutable",
    "unknown",
]


@dataclass(frozen=True)
class MxProvider:
    """Behavioural profile for one receiving provider."""

    id: str
    name: str
    category: ProviderCategory
    accept_all_bounce_prior: float
    # Enhanced status codes this provider uses for a definitively absent
    # recipient beyond the RFC 3463 5.1.x codes every MTA shares.
    definitive_rejection_codes: frozenset[str] = field(default_factory=frozenset)
    # Whether the boundary MTA normally knows the recipient directory. False
    # means an accept-all carries no information about the mailbox at all.
    verifies_recipients: bool | None = None
    # A gateway forwards to a separate backend that produces the real bounce.
    fronts_backend: bool = False
    notes: str = ""


UNKNOWN_PROVIDER = MxProvider(
    id="unknown",
    name="Unknown",
    category="unknown",
    accept_all_bounce_prior=0.14,
    verifies_recipients=None,
    notes="MX does not match any known provider.",
)

NO_MX_PROVIDER = MxProvider(
    id="no_mx",
    name="No mail route",
    category="unroutable",
    accept_all_bounce_prior=0.9,
    verifies_recipients=None,
    notes="Domain published no usable MX host.",
)

_PROVIDERS: tuple[MxProvider, ...] = (
    MxProvider(
        id="microsoft365",
        name="Microsoft 365",
        category="hosted_mailbox",
        accept_all_bounce_prior=0.16,
        definitive_rejection_codes=frozenset({"5.4.1", "5.1.10"}),
        verifies_recipients=None,
        notes=(
            "Tenants with Directory Based Edge Blocking reject unknown recipients at the "
            "edge with 5.4.1. An accept-all therefore means DBEB is off and the mailbox "
            "store has not been consulted yet."
        ),
    ),
    MxProvider(
        id="google_workspace",
        name="Google Workspace",
        category="hosted_mailbox",
        accept_all_bounce_prior=0.14,
        verifies_recipients=True,
        notes=(
            "Google answers RCPT honestly for provisioned tenants, so an accept-all "
            "usually reflects a deliberately configured catch-all route that delivers."
        ),
    ),
    MxProvider(
        id="outlook_consumer",
        name="Outlook.com",
        category="consumer",
        accept_all_bounce_prior=0.25,
        definitive_rejection_codes=frozenset({"5.4.1"}),
        verifies_recipients=True,
        notes="Consumer mailboxes have no catch-all concept; accept-all implies throttling.",
    ),
    MxProvider(
        id="proofpoint",
        name="Proofpoint",
        category="security_gateway",
        accept_all_bounce_prior=0.16,
        verifies_recipients=None,
        fronts_backend=True,
        notes="Accepts every recipient unless LDAP recipient verification is enabled.",
    ),
    MxProvider(
        id="mimecast",
        name="Mimecast",
        category="security_gateway",
        accept_all_bounce_prior=0.16,
        verifies_recipients=None,
        fronts_backend=True,
        notes="Directory sync is optional; without it the backend generates the bounce.",
    ),
    MxProvider(
        id="barracuda",
        name="Barracuda",
        category="security_gateway",
        accept_all_bounce_prior=0.16,
        verifies_recipients=None,
        fronts_backend=True,
    ),
    MxProvider(
        id="cisco_ironport",
        name="Cisco Secure Email",
        category="security_gateway",
        accept_all_bounce_prior=0.16,
        verifies_recipients=None,
        fronts_backend=True,
    ),
    MxProvider(
        id="messagelabs",
        name="Broadcom Email Security",
        category="security_gateway",
        accept_all_bounce_prior=0.16,
        verifies_recipients=None,
        fronts_backend=True,
    ),
    MxProvider(
        id="forcepoint",
        name="Forcepoint",
        category="security_gateway",
        accept_all_bounce_prior=0.16,
        verifies_recipients=None,
        fronts_backend=True,
    ),
    MxProvider(
        id="sophos",
        name="Sophos Email",
        category="security_gateway",
        accept_all_bounce_prior=0.16,
        verifies_recipients=None,
        fronts_backend=True,
    ),
    MxProvider(
        id="trend_micro",
        name="Trend Micro Email Security",
        category="security_gateway",
        accept_all_bounce_prior=0.16,
        verifies_recipients=None,
        fronts_backend=True,
    ),
    MxProvider(
        id="hornetsecurity",
        name="Hornetsecurity",
        category="security_gateway",
        accept_all_bounce_prior=0.16,
        verifies_recipients=None,
        fronts_backend=True,
    ),
    MxProvider(
        id="retarus",
        name="Retarus",
        category="security_gateway",
        accept_all_bounce_prior=0.16,
        verifies_recipients=None,
        fronts_backend=True,
    ),
    MxProvider(
        id="spamexperts",
        name="N-able SpamExperts",
        category="security_gateway",
        accept_all_bounce_prior=0.17,
        verifies_recipients=None,
        fronts_backend=True,
    ),
    MxProvider(
        id="cloudflare_area1",
        name="Cloudflare Email Security",
        category="security_gateway",
        accept_all_bounce_prior=0.15,
        verifies_recipients=None,
        fronts_backend=True,
    ),
    MxProvider(
        id="fortinet",
        name="FortiMail",
        category="security_gateway",
        accept_all_bounce_prior=0.16,
        verifies_recipients=None,
        fronts_backend=True,
    ),
    MxProvider(
        id="zoho",
        name="Zoho Mail",
        category="hosted_mailbox",
        accept_all_bounce_prior=0.14,
        verifies_recipients=True,
    ),
    MxProvider(
        id="fastmail",
        name="Fastmail",
        category="hosted_mailbox",
        accept_all_bounce_prior=0.12,
        verifies_recipients=True,
    ),
    MxProvider(
        id="proton",
        name="Proton Mail",
        category="hosted_mailbox",
        accept_all_bounce_prior=0.13,
        verifies_recipients=True,
    ),
    MxProvider(
        id="migadu",
        name="Migadu",
        category="hosted_mailbox",
        accept_all_bounce_prior=0.13,
        verifies_recipients=True,
    ),
    MxProvider(
        id="mxroute",
        name="MXroute",
        category="hosted_mailbox",
        accept_all_bounce_prior=0.13,
        verifies_recipients=True,
    ),
    MxProvider(
        id="rackspace",
        name="Rackspace Email",
        category="hosted_mailbox",
        accept_all_bounce_prior=0.14,
        verifies_recipients=True,
    ),
    MxProvider(
        id="godaddy",
        name="GoDaddy",
        category="hosted_mailbox",
        accept_all_bounce_prior=0.14,
        verifies_recipients=True,
    ),
    MxProvider(
        id="namecheap",
        name="Namecheap Private Email",
        category="hosted_mailbox",
        accept_all_bounce_prior=0.14,
        verifies_recipients=True,
    ),
    MxProvider(
        id="ionos",
        name="IONOS",
        category="hosted_mailbox",
        accept_all_bounce_prior=0.14,
        verifies_recipients=True,
    ),
    MxProvider(
        id="ovh",
        name="OVH",
        category="hosted_mailbox",
        accept_all_bounce_prior=0.14,
        verifies_recipients=True,
    ),
    MxProvider(
        id="hostinger",
        name="Hostinger",
        category="hosted_mailbox",
        accept_all_bounce_prior=0.14,
        verifies_recipients=True,
    ),
    MxProvider(
        id="titan",
        name="Titan",
        category="hosted_mailbox",
        accept_all_bounce_prior=0.14,
        verifies_recipients=True,
    ),
    MxProvider(
        id="amazon_workmail",
        name="Amazon WorkMail",
        category="hosted_mailbox",
        accept_all_bounce_prior=0.14,
        verifies_recipients=True,
    ),
    MxProvider(
        id="yandex",
        name="Yandex 360",
        category="hosted_mailbox",
        accept_all_bounce_prior=0.15,
        verifies_recipients=True,
    ),
    MxProvider(
        id="gmail_consumer",
        name="Gmail",
        category="consumer",
        accept_all_bounce_prior=0.25,
        verifies_recipients=True,
        notes="Consumer Gmail has no catch-all; accept-all means rate limiting.",
    ),
    MxProvider(
        id="yahoo",
        name="Yahoo Mail",
        category="consumer",
        accept_all_bounce_prior=0.25,
        verifies_recipients=True,
    ),
    MxProvider(
        id="icloud",
        name="iCloud Mail",
        category="consumer",
        accept_all_bounce_prior=0.25,
        verifies_recipients=True,
    ),
    MxProvider(
        id="gmx",
        name="GMX / Web.de",
        category="consumer",
        accept_all_bounce_prior=0.24,
        verifies_recipients=True,
    ),
    MxProvider(
        id="mailru",
        name="Mail.ru",
        category="consumer",
        accept_all_bounce_prior=0.24,
        verifies_recipients=True,
    ),
    MxProvider(
        id="qq",
        name="Tencent QQ Mail",
        category="consumer",
        accept_all_bounce_prior=0.24,
        verifies_recipients=True,
    ),
    MxProvider(
        id="netease",
        name="NetEase Mail",
        category="consumer",
        accept_all_bounce_prior=0.24,
        verifies_recipients=True,
    ),
    MxProvider(
        id="parked",
        name="Parked domain",
        category="parked",
        accept_all_bounce_prior=0.85,
        verifies_recipients=False,
        notes="Registrar or parking-page MX; mail is discarded or bounced.",
    ),
)

_PROVIDERS_BY_ID = {provider.id: provider for provider in _PROVIDERS}

# Ordered longest-suffix-first at import so a specific host such as
# ``mx.zoho.eu`` is never shadowed by a broader entry.
_SUFFIX_RULES: tuple[tuple[str, str], ...] = (
    ("mail.protection.outlook.com", "microsoft365"),
    ("mail.eo.outlook.com", "microsoft365"),
    ("mail.protection.office365.us", "microsoft365"),
    ("olc.protection.outlook.com", "outlook_consumer"),
    ("gmail-smtp-in.l.google.com", "gmail_consumer"),
    ("aspmx.l.google.com", "google_workspace"),
    ("googlemail.com", "google_workspace"),
    ("google.com", "google_workspace"),
    ("pphosted.com", "proofpoint"),
    ("ppe-hosted.com", "proofpoint"),
    ("pphosted.co.uk", "proofpoint"),
    ("mimecast.com", "mimecast"),
    ("mimecast.co.za", "mimecast"),
    ("mimecast-offshore.com", "mimecast"),
    ("barracudanetworks.com", "barracuda"),
    ("ess.barracuda.com", "barracuda"),
    ("iphmx.com", "cisco_ironport"),
    ("messagelabs.com", "messagelabs"),
    ("mailcontrol.com", "forcepoint"),
    ("sophos.com", "sophos"),
    ("tmes.trendmicro.com", "trend_micro"),
    ("trendmicro.com", "trend_micro"),
    ("hornetsecurity.com", "hornetsecurity"),
    ("antispameurope.com", "hornetsecurity"),
    ("retarus.com", "retarus"),
    ("antispamcloud.com", "spamexperts"),
    ("spamexperts.com", "spamexperts"),
    ("mx.cloudflare.net", "cloudflare_area1"),
    ("fortimail.com", "fortinet"),
    ("zoho.com", "zoho"),
    ("zoho.eu", "zoho"),
    ("zohomail.com", "zoho"),
    ("messagingengine.com", "fastmail"),
    ("protonmail.ch", "proton"),
    ("proton.me", "proton"),
    ("migadu.com", "migadu"),
    ("mxroute.com", "mxroute"),
    ("emailsrvr.com", "rackspace"),
    ("secureserver.net", "godaddy"),
    ("privateemail.com", "namecheap"),
    ("registrar-servers.com", "namecheap"),
    ("ionos.com", "ionos"),
    ("1and1.com", "ionos"),
    ("kundenserver.de", "ionos"),
    ("ovh.net", "ovh"),
    ("hostinger.com", "hostinger"),
    ("titan.email", "titan"),
    ("awsapps.com", "amazon_workmail"),
    ("yandex.net", "yandex"),
    ("yandex.ru", "yandex"),
    ("am0.yahoodns.net", "yahoo"),
    ("yahoodns.net", "yahoo"),
    ("mail.icloud.com", "icloud"),
    ("icloud.com", "icloud"),
    ("gmx.net", "gmx"),
    ("web.de", "gmx"),
    ("mail.ru", "mailru"),
    ("qq.com", "qq"),
    ("163.com", "netease"),
    ("126.com", "netease"),
    ("sedoparking.com", "parked"),
    ("parkingcrew.net", "parked"),
    ("above.com", "parked"),
    ("bodis.com", "parked"),
    ("afternic.com", "parked"),
)

_AMAZON_INBOUND_PREFIX = "inbound-smtp."
_AMAZON_INBOUND_SUFFIX = ".amazonaws.com"


@dataclass(frozen=True)
class MxProfile:
    """Provider classification for one domain's full MX set."""

    provider: MxProvider
    mx_hosts: tuple[str, ...]
    matched_host: str | None

    @property
    def id(self) -> str:
        return self.provider.id

    @property
    def category(self) -> ProviderCategory:
        return self.provider.category


def _host_matches(host: str, suffix: str) -> bool:
    return host == suffix or host.endswith(f".{suffix}")


def provider_for_host(host: str) -> MxProvider | None:
    """Classify a single MX hostname, or return None when it is unrecognised."""
    normalized = host.strip().rstrip(".").lower()
    if not normalized:
        return None
    if normalized.startswith(_AMAZON_INBOUND_PREFIX) and normalized.endswith(
        _AMAZON_INBOUND_SUFFIX
    ):
        return _PROVIDERS_BY_ID["amazon_workmail"]
    for suffix, provider_id in _SUFFIX_RULES:
        if _host_matches(normalized, suffix):
            return _PROVIDERS_BY_ID[provider_id]
    return None


def _self_hosted_profile(hosts: tuple[str, ...], domain: str) -> MxProvider | None:
    """Recognise an MX operated by the domain itself rather than a provider."""
    domain = domain.strip().rstrip(".").lower()
    if not domain:
        return None
    if any(_host_matches(host, domain) for host in hosts):
        return MxProvider(
            id="self_hosted",
            name="Self-hosted",
            category="self_hosted",
            accept_all_bounce_prior=0.15,
            verifies_recipients=None,
            notes=(
                "MX is inside the recipient domain. Control panel defaults such as cPanel "
                "usually forward a catch-all to a real mailbox, but a discard route is "
                "equally common."
            ),
        )
    return None


def classify_mx(mx_hosts: list[str] | tuple[str, ...], domain: str = "") -> MxProfile:
    """Classify a domain's receiving infrastructure from its MX host list.

    Gateway matches win over mailbox-host matches because the gateway is what
    answers RCPT, and it is the layer that decides whether accept-all carries
    any recipient information.
    """
    hosts = tuple(host.strip().rstrip(".").lower() for host in mx_hosts if host and host.strip())
    if not hosts:
        return MxProfile(provider=NO_MX_PROVIDER, mx_hosts=(), matched_host=None)

    matches: list[tuple[str, MxProvider]] = []
    for host in hosts:
        provider = provider_for_host(host)
        if provider is not None:
            matches.append((host, provider))

    for host, provider in matches:
        if provider.category == "security_gateway":
            return MxProfile(provider=provider, mx_hosts=hosts, matched_host=host)
    if matches:
        host, provider = matches[0]
        return MxProfile(provider=provider, mx_hosts=hosts, matched_host=host)

    self_hosted = _self_hosted_profile(hosts, domain)
    if self_hosted is not None:
        return MxProfile(provider=self_hosted, mx_hosts=hosts, matched_host=hosts[0])

    return MxProfile(provider=UNKNOWN_PROVIDER, mx_hosts=hosts, matched_host=None)


def parse_mx_hosts(mx_records: list[str]) -> list[str]:
    """Extract hostnames from the ``"<pref> <host>."`` strings the DNS stage emits."""
    hosts: list[str] = []
    for record in mx_records:
        parts = record.split()
        host = parts[1] if len(parts) == 2 else record
        host = host.strip().rstrip(".")
        if host:
            hosts.append(host)
    return hosts
