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


def measure(
    incident: Incident, rule: DelayPeriodRule, policy_ends: datetime | None
) -> timedelta | NothingCounts | MissingFact:
    """The delay period of an incident, from the booked flight's scheduled departure.

    The new-wording rule: a delayed flight's delay runs to its actual departure
    or the first replacement flight's, whichever is first. A cancelled flight's
    runs to the replacement's departure; a replacement the insured arranged
    counts only if arranged by the end of the policy period, unless it returns
    to Taiwan. A delay stated without times is used as stated.
    """
    if rule is not DelayPeriodRule.NEW:
        raise NotImplementedError(f"the {rule} is not applied yet")
    if incident.missed_connection:
        raise NotImplementedError("a missed connection is not measured yet")
    departures = [r.departure for r in incident.replacements if r.departure is not None]
    if incident.cancelled:
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
                "the one the insured arranged after the policy period ended "
                "does not return to Taiwan"
            )
    else:
        ends = departures
        if incident.actual_departure is not None:
            ends.append(incident.actual_departure)
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
