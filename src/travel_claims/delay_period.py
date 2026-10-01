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


def measure(
    incident: Incident, rule: DelayPeriodRule, policy_ends: datetime | None
) -> timedelta | NothingCounts:
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
        counted = [r for r in incident.replacements if _counts(r, policy_ends)]
        ends = [r.departure for r in counted if r.departure is not None]
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
    if incident.scheduled_departure is None or not ends:
        raise NotImplementedError("a missing time is not reported yet")
    return min(ends) - incident.scheduled_departure


def _counts(replacement: Replacement, policy_ends: datetime | None) -> bool:
    """Whether a replacement for a cancelled flight counts toward the delay period."""
    if replacement.arranged_by is ArrangedBy.AIRLINE or replacement.returns_to_taiwan:
        return True
    if (
        replacement.arranged_by is None
        or replacement.arranged_at is None
        or policy_ends is None
        or (replacement.arranged_at > policy_ends and replacement.returns_to_taiwan is None)
    ):
        raise NotImplementedError("a missing fact is not reported yet")
    return replacement.arranged_at <= policy_ends
