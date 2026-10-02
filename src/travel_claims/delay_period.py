"""Measure a flight delay from the times a Scenario states, by the Wording version's rule.

Hours are computed by code, never estimated by a model.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from travel_claims.conditions import DelayPeriodRule
from travel_claims.local_models import ArrangedBy, Incident, Replacement


@dataclass(frozen=True)
class NothingCounts:
    """The rule counts no flight that ends the delay, so there is no delay period."""

    why: str


@dataclass(frozen=True)
class MissingFact:
    """The Scenario does not state a fact the rule needs."""

    fact: str


# What measuring a delay period gives.
Measured = timedelta | NothingCounts | MissingFact


# The old wording's delay-period rule carries the force-majeure proviso of its
# first-replacement exclusion.
FORCE_MAJEURE_RULE = (
    "the delay runs to the next replacement flight if force majeure prevented the insured "
    "from taking the first"
)


def measure(
    incident: Incident,
    rule: DelayPeriodRule,
    policy_ends: datetime | None,
    *,
    force_majeure: bool = False,
) -> Measured:
    """The delay period of an incident, from the booked flight's scheduled departure.

    The new-wording rule: a delayed flight's delay runs to its actual departure
    or the first replacement flight's, whichever is first. A cancelled flight's
    runs to the replacement's departure; a replacement the insured arranged
    counts only if arranged by the end of the policy period, unless it returns
    to Taiwan.

    The old-wording rule: the same, except that a cancelled flight's delay runs
    to a replacement the insured arranged only when the airline arranged none,
    and only if arranged within the policy period. With `force_majeure`, it is
    measured as if force majeure prevented the insured from taking the first
    replacement flight, not taken: to the next one, or the booked flight's
    actual departure if earlier. The new-wording rule has no such reading and
    ignores `force_majeure`.

    A delay stated without times is used as stated.
    """
    if incident.missed_connection:
        raise NotImplementedError("a missed connection is not measured yet")
    if rule is DelayPeriodRule.OLD:
        ends = _old_wording_ends(incident, policy_ends, force_majeure)
    else:
        ends = _new_wording_ends(incident, policy_ends)
    if isinstance(ends, NothingCounts | MissingFact):
        return ends
    if not ends and incident.stated_delay is not None:
        return incident.stated_delay
    if not ends:
        return MissingFact(
            "when the replacement flight departed"
            if incident.cancelled
            else "when the booked flight or a replacement flight departed"
        )
    if incident.scheduled_departure is None:
        return MissingFact("the booked flight's scheduled departure")
    return min(ends) - incident.scheduled_departure


def _new_wording_ends(
    incident: Incident, policy_ends: datetime | None
) -> list[datetime] | NothingCounts | MissingFact:
    """When the delay may end, by the new-wording rule; the earliest ends it."""
    departures = [r.departure for r in incident.replacements if r.departure is not None]
    if not incident.cancelled:
        if incident.actual_departure is not None:
            departures.append(incident.actual_departure)
        return departures
    ends: list[datetime] = []
    unknown: list[tuple[datetime, MissingFact]] = []
    for replacement in incident.replacements:
        if replacement.departure is None:
            continue
        counts = _counts(replacement, policy_ends)
        if isinstance(counts, MissingFact):
            unknown.append((replacement.departure, counts))
        elif counts:
            ends.append(replacement.departure)
    # A replacement whose counting is unknown matters only if it would end the delay first.
    earliest_unknown = min(unknown, default=None, key=lambda pair: pair[0])
    if earliest_unknown is not None and (not ends or earliest_unknown[0] < min(ends)):
        return earliest_unknown[1]
    if departures and not ends:
        return NothingCounts(
            "the one the insured arranged after the policy period ended does not return to Taiwan"
        )
    return ends


def _old_wording_ends(
    incident: Incident, policy_ends: datetime | None, force_majeure: bool
) -> list[datetime] | NothingCounts | MissingFact:
    """When the delay may end, by the old-wording rule; the earliest ends it."""
    replacements = sorted(
        ((r.departure, r) for r in incident.replacements if r.departure is not None),
        key=lambda pair: pair[0],
    )
    if incident.cancelled:
        counted = _counted_after_cancellation([r for _, r in replacements], policy_ends)
        if not isinstance(counted, list):
            return counted
        replacements = [(departure, r) for departure, r in replacements if r in counted]
        actual = []
    else:
        actual = [incident.actual_departure] if incident.actual_departure is not None else []
    if force_majeure and replacements and replacements[0][1].taken is False:
        # Force majeure prevented taking the first replacement flight: the delay runs to the next.
        if len(replacements) < 2:
            return MissingFact("when the next replacement flight departed")
        return actual + [replacements[1][0]]
    return actual + [departure for departure, _ in replacements]


def _counted_after_cancellation(
    replacements: list[Replacement], policy_ends: datetime | None
) -> list[Replacement] | NothingCounts | MissingFact:
    """The replacements for a cancelled flight that count, by the old-wording rule.

    Those the airline arranged; when it arranged none, those the insured
    arranged within the policy period.
    """
    if any(r.arranged_by is None for r in replacements):
        return MissingFact("who arranged the replacement flight")
    by_airline = [r for r in replacements if r.arranged_by is ArrangedBy.AIRLINE]
    if by_airline or not replacements:
        return by_airline
    if any(r.arranged_at is None for r in replacements):
        return MissingFact("when the insured arranged the replacement flight")
    if policy_ends is None:
        return MissingFact("the policy period")
    within = [r for r in replacements if r.arranged_at is not None and r.arranged_at <= policy_ends]
    if not within:
        return NothingCounts(
            "the one the insured arranged after the policy period ended does not count"
        )
    return within


def _counts(replacement: Replacement, policy_ends: datetime | None) -> bool | MissingFact:
    """Whether a replacement for a cancelled flight counts toward the delay period."""
    if replacement.arranged_by is ArrangedBy.AIRLINE or replacement.returns_to_taiwan:
        return True
    if replacement.arranged_by is None:
        return MissingFact("who arranged the replacement flight")
    if replacement.arranged_at is None:
        return MissingFact("when the insured arranged the replacement flight")
    if policy_ends is None:
        return MissingFact("the policy period")
    if replacement.arranged_at <= policy_ends:
        return True
    if replacement.returns_to_taiwan is None:
        return MissingFact("whether the replacement flight the insured arranged returns to Taiwan")
    return False
