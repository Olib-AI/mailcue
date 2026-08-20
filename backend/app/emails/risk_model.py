"""Hierarchical hard-bounce risk model for accept-all recipients.

The estimate is built by partial pooling rather than by a single lookup. An
address inherits the seeded prior for its receiving provider, that prior is
refined by every outcome observed at the same provider, and the result becomes
the prior for the recipient domain's own observations. A domain seen for the
first time therefore still gets an informed estimate, which is what a lookup
keyed on history alone can never do.

Evidence that is not history is applied as an additive shift in log-odds:
local-part shape, passive domain signals, and what the SMTP probe saw when it
tested control recipients alongside the target.

All functions here are pure so the model can be unit tested and replayed
against stored predictions during calibration.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from app.emails.mx_providers import MxProvider

RiskLevel = Literal["low", "medium", "high", "unknown"]
RiskAction = Literal["send", "caution", "hold"]
RiskSource = Literal[
    "no_history",
    "exact_history",
    "domain_history",
    "shared_domain_history",
    "provider_history",
    "provider_prior",
]

SEND_THRESHOLD = 0.04
HOLD_THRESHOLD = 0.10

# Pseudo-observation weights. The provider level pools far more traffic than a
# single domain, so it takes more evidence to move and lends more stability to
# the domains beneath it. Both were lowered after the seeded priors turned out
# to be worse than the observed rates they were meant to stand in for.
_PROVIDER_PRIOR_STRENGTH = 25.0
_DOMAIN_PRIOR_STRENGTH = 15.0
_GLOBAL_PRIOR = 0.14

# Measured against a 314-address cohort with 45 confirmed hard bounces.
#
# Comparing the target's RCPT latency against control recipients at the same
# destination turned out to be the strongest evidence available, by a wide
# margin. Holding the domain constant, recipients whose lookup was slower than
# the controls bounced at 2.9% while the rest bounced at 44.1%; within Google
# Workspace alone the split was 0.6% against 46.5%. The destination performs a
# directory lookup for a mailbox it has and short-circuits for one it does
# not, and the delay leaks which happened.
#
# The signal is only evidence when both latencies were actually measured. An
# address probed without controls has not been shown to lack a lookup, so it
# gets neither adjustment.
_TIMING_LOOKUP_OBSERVED = -1.8
_TIMING_NO_LOOKUP = 1.2
# Ratio of target to control latency above which a lookup is considered seen.
_TIMING_RATIO = 1.8

# Local-part evidence is real but far weaker than the probe, so its raw deltas
# are damped rather than applied at face value.
_LOCAL_PART_SCALE = 0.5


@dataclass(frozen=True)
class ObservationCounts:
    """Outcome tallies at one level of the hierarchy."""

    delivered: int = 0
    hard_bounce: int = 0
    soft_bounce: int = 0
    tenants: int = 0

    @property
    def decisive(self) -> int:
        """Outcomes that speak to permanent failure. Soft bounces are excluded."""
        return self.delivered + self.hard_bounce

    @property
    def total(self) -> int:
        return self.delivered + self.hard_bounce + self.soft_bounce


@dataclass(frozen=True)
class ProbeEvidence:
    """What the SMTP probe observed for the target and its control recipients."""

    accepted: bool | None = None
    control_total: int = 0
    control_accepted: int = 0
    control_rejected: int = 0
    control_inconclusive: int = 0
    target_latency_ms: float | None = None
    control_median_latency_ms: float | None = None
    sender_reputation_signal: bool = False

    @property
    def uniform_accept_all(self) -> bool:
        return self.control_total > 0 and self.control_accepted == self.control_total

    @property
    def selective(self) -> bool:
        """The destination rejected at least one synthetic recipient.

        A destination that rejects any control is running recipient logic, so
        its acceptance of the target is real information rather than a blanket
        answer, even if another control was accepted.
        """
        return self.control_rejected > 0


@dataclass(frozen=True)
class RiskContribution:
    """One named adjustment applied to the base rate, in log-odds."""

    label: str
    delta: float
    detail: str = ""


@dataclass
class RiskAssessment:
    """Calibrated hard-bounce estimate with the reasoning that produced it."""

    score: float
    level: RiskLevel
    recommended_action: RiskAction
    source: RiskSource
    sample_size: int
    explanation: str
    base_rate: float = _GLOBAL_PRIOR
    provider_id: str | None = None
    provider_rate: float | None = None
    confidence: float = 0.3
    contributions: list[RiskContribution] = field(default_factory=list)


def _logit(probability: float) -> float:
    clamped = min(max(probability, 1e-6), 1 - 1e-6)
    return math.log(clamped / (1 - clamped))


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1 / (1 + math.exp(-value))
    exponential = math.exp(value)
    return exponential / (1 + exponential)


def _pooled_rate(counts: ObservationCounts, prior_mean: float, prior_strength: float) -> float:
    """Beta-binomial posterior mean for the hard-bounce rate."""
    observed = counts.decisive
    return (counts.hard_bounce + prior_mean * prior_strength) / (observed + prior_strength)


def _level_for(score: float) -> tuple[RiskLevel, RiskAction]:
    if score <= SEND_THRESHOLD:
        return "low", "send"
    if score >= HOLD_THRESHOLD:
        return "high", "hold"
    return "medium", "caution"


def exact_recipient_risk(
    outcome: Literal["delivered", "hard_bounce", "soft_bounce"],
    *,
    recent_delivery: bool,
) -> RiskAssessment | None:
    """Score an address whose own outcome has already been observed."""
    if outcome == "hard_bounce":
        return RiskAssessment(
            score=0.98,
            level="high",
            recommended_action="hold",
            source="exact_history",
            sample_size=1,
            explanation="This exact recipient recently produced a hard bounce.",
            confidence=0.95,
        )
    if outcome == "delivered" and recent_delivery:
        return RiskAssessment(
            score=0.02,
            level="low",
            recommended_action="send",
            source="exact_history",
            sample_size=1,
            explanation="This exact recipient has a recent confirmed delivery.",
            confidence=0.9,
        )
    if outcome == "soft_bounce":
        return RiskAssessment(
            score=0.20,
            level="medium",
            recommended_action="caution",
            source="exact_history",
            sample_size=1,
            explanation="This exact recipient recently produced a temporary delivery failure.",
            confidence=0.6,
        )
    return None


def compute_risk(
    *,
    provider: MxProvider,
    provider_counts: ObservationCounts | None = None,
    domain_counts: ObservationCounts | None = None,
    domain_counts_shared: bool = False,
    local_part_delta: float = 0.0,
    local_part_notes: list[str] | None = None,
    domain_signal_delta: float = 0.0,
    domain_signal_notes: list[str] | None = None,
    probe: ProbeEvidence | None = None,
) -> RiskAssessment:
    """Estimate the hard-bounce probability for one accept-all recipient."""
    provider_counts = provider_counts or ObservationCounts()
    domain_counts = domain_counts or ObservationCounts()
    contributions: list[RiskContribution] = []

    provider_rate = _pooled_rate(
        provider_counts, provider.accept_all_bounce_prior, _PROVIDER_PRIOR_STRENGTH
    )
    base_rate = _pooled_rate(domain_counts, provider_rate, _DOMAIN_PRIOR_STRENGTH)

    if domain_counts.decisive > 0:
        source: RiskSource = "shared_domain_history" if domain_counts_shared else "domain_history"
        explanation = (
            f"Estimated from {domain_counts.decisive} observed outcomes at this domain, "
            f"anchored on {provider.name} behaviour."
        )
    elif provider_counts.decisive > 0:
        source = "provider_history"
        explanation = (
            f"No outcomes recorded for this domain. Estimated from "
            f"{provider_counts.decisive} outcomes across {provider.name} destinations."
        )
    else:
        source = "provider_prior"
        explanation = (
            f"No delivery history available. Estimated from the {provider.name} accept-all "
            f"prior, which reflects how that receiver handles unknown recipients."
        )

    log_odds = _logit(base_rate)

    if probe is not None:
        if probe.selective:
            # The destination proved it evaluates recipients, so accepting the
            # target is a real answer rather than a blanket one. Rejecting every
            # control is stronger evidence than rejecting only some.
            rejected_share = probe.control_rejected / max(probe.control_total, 1)
            delta = -1.2 - 0.6 * rejected_share
            log_odds += delta
            contributions.append(
                RiskContribution(
                    "probe_selective",
                    round(delta, 3),
                    f"{probe.control_rejected} of {probe.control_total} control recipients were "
                    "rejected, so the destination validates recipients.",
                )
            )
        if (
            probe.target_latency_ms is not None
            and probe.control_median_latency_ms is not None
            and probe.control_median_latency_ms > 0
        ):
            ratio = probe.target_latency_ms / probe.control_median_latency_ms
            if ratio >= _TIMING_RATIO:
                log_odds += _TIMING_LOOKUP_OBSERVED
                contributions.append(
                    RiskContribution(
                        "probe_timing",
                        _TIMING_LOOKUP_OBSERVED,
                        f"The target took {ratio:.1f} times longer to answer than the control "
                        "recipients, so the destination looked this mailbox up rather than "
                        "accepting blindly.",
                    )
                )
            else:
                log_odds += _TIMING_NO_LOOKUP
                contributions.append(
                    RiskContribution(
                        "probe_timing",
                        _TIMING_NO_LOOKUP,
                        "The target was answered as quickly as recipients known not to exist, "
                        "so no mailbox lookup took place.",
                    )
                )
        if probe.sender_reputation_signal:
            # The receiver was reacting to our sending host, so its answers
            # describe us rather than the mailbox. Pull back toward the prior.
            pull = (_logit(provider.accept_all_bounce_prior) - log_odds) * 0.5
            log_odds += pull
            contributions.append(
                RiskContribution(
                    "probe_reputation",
                    round(pull, 3),
                    "The destination reacted to the probing host's reputation, so its "
                    "responses are not evidence about this mailbox.",
                )
            )

    if local_part_delta:
        scaled = round(local_part_delta * _LOCAL_PART_SCALE, 3)
        log_odds += scaled
        contributions.append(
            RiskContribution(
                "local_part",
                scaled,
                "; ".join(local_part_notes or []) or "Local-part shape adjustment.",
            )
        )
    if domain_signal_delta:
        log_odds += domain_signal_delta
        contributions.append(
            RiskContribution(
                "domain_signals",
                domain_signal_delta,
                "; ".join(domain_signal_notes or []) or "Passive domain signal adjustment.",
            )
        )

    score = _sigmoid(log_odds)
    level, action = _level_for(score)

    evidence = domain_counts.decisive + min(provider_counts.decisive, 200) / 10
    confidence = min(0.35 + evidence / 60, 0.9)
    if probe is not None and probe.sender_reputation_signal:
        confidence = min(confidence, 0.35)
    if source == "provider_prior":
        confidence = min(confidence, 0.45)

    return RiskAssessment(
        score=round(score, 4),
        level=level,
        recommended_action=action,
        source=source,
        sample_size=domain_counts.decisive or provider_counts.decisive,
        explanation=explanation,
        base_rate=round(base_rate, 4),
        provider_id=provider.id,
        provider_rate=round(provider_rate, 4),
        confidence=round(confidence, 3),
        contributions=contributions,
    )


@dataclass(frozen=True)
class BudgetCandidate:
    """One address competing for inclusion under a blended bounce-rate target."""

    email: str
    score: float


@dataclass
class BudgetSelection:
    """Which addresses fit inside a target blended bounce rate."""

    included: list[str]
    excluded: list[str]
    projected_bounce_rate: float
    target_bounce_rate: float
    included_count: int
    excluded_count: int


def select_within_budget(
    candidates: list[BudgetCandidate],
    *,
    target_bounce_rate: float,
    committed: list[float] | None = None,
) -> BudgetSelection:
    """Pick the largest set of addresses whose blended risk stays under target.

    Reputation is judged on the aggregate bounce rate of a send, not on any one
    address, so the useful decision is how many risky addresses a batch can
    carry rather than whether a single address is acceptable. Taking candidates
    in ascending risk maximises the count for a given ceiling.
    """
    committed = committed or []
    ordered = sorted(candidates, key=lambda item: item.score)

    total_score = sum(committed)
    count = len(committed)
    included: list[str] = []
    excluded: list[str] = []

    for candidate in ordered:
        projected_total = total_score + candidate.score
        projected_count = count + 1
        if projected_count and projected_total / projected_count <= target_bounce_rate:
            total_score = projected_total
            count = projected_count
            included.append(candidate.email)
        else:
            excluded.append(candidate.email)

    projected = total_score / count if count else 0.0
    return BudgetSelection(
        included=included,
        excluded=excluded,
        projected_bounce_rate=round(projected, 5),
        target_bounce_rate=target_bounce_rate,
        included_count=len(included),
        excluded_count=len(excluded),
    )


@dataclass
class CalibrationBin:
    """One reliability-diagram bucket."""

    lower: float
    upper: float
    count: int
    predicted_mean: float
    observed_rate: float


@dataclass
class CalibrationReport:
    """Measured agreement between predicted scores and observed outcomes."""

    sample_size: int
    brier_score: float | None
    mean_predicted: float | None
    observed_rate: float | None
    bins: list[CalibrationBin]


def calibration_report(
    observations: list[tuple[float, bool]],
    *,
    bin_count: int = 10,
) -> CalibrationReport:
    """Build a reliability diagram and Brier score from scored outcomes.

    ``observations`` pairs the score issued at validation time with whether the
    address went on to hard bounce.
    """
    if not observations:
        return CalibrationReport(0, None, None, None, [])

    brier = sum((score - (1.0 if bounced else 0.0)) ** 2 for score, bounced in observations)
    brier /= len(observations)
    mean_predicted = sum(score for score, _ in observations) / len(observations)
    observed_rate = sum(1 for _, bounced in observations if bounced) / len(observations)

    width = 1.0 / bin_count
    bins: list[CalibrationBin] = []
    for index in range(bin_count):
        lower = index * width
        upper = lower + width
        members = [
            (score, bounced)
            for score, bounced in observations
            if (lower <= score < upper) or (index == bin_count - 1 and score == 1.0)
        ]
        if not members:
            continue
        bins.append(
            CalibrationBin(
                lower=round(lower, 4),
                upper=round(upper, 4),
                count=len(members),
                predicted_mean=round(sum(score for score, _ in members) / len(members), 4),
                observed_rate=round(sum(1 for _, bounced in members if bounced) / len(members), 4),
            )
        )

    return CalibrationReport(
        sample_size=len(observations),
        brier_score=round(brier, 5),
        mean_predicted=round(mean_predicted, 4),
        observed_rate=round(observed_rate, 4),
        bins=bins,
    )
