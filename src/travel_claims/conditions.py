"""The condition table: the Conditions and exclusions of one Product in one Wording version.

Extraction drafts it, a person confirms it in the workbook, and everything
after that is computed from it (ADR 0001).
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from travel_claims.numerals import format_numeral, parse_numeral
from travel_claims.policies import Wording


class Benefit(StrEnum):
    """One of the six standard benefits of travel-inconvenience cover."""

    TRIP_CANCELLATION = "trip cancellation"
    FLIGHT_DELAY = "flight delay"
    TRIP_CHANGE = "trip change"
    BAGGAGE_DELAY = "baggage delay"
    BAGGAGE_LOSS = "baggage loss"
    TRAVEL_DOCUMENT_LOSS = "loss of travel documents"


# Each Benefit's name in the Clauses.
BENEFIT_NAMES = {
    "旅程取消": Benefit.TRIP_CANCELLATION,
    "班機延誤": Benefit.FLIGHT_DELAY,
    "旅程更改": Benefit.TRIP_CHANGE,
    "行李延誤": Benefit.BAGGAGE_DELAY,
    "行李損失": Benefit.BAGGAGE_LOSS,
    "旅行文件損失": Benefit.TRAVEL_DOCUMENT_LOSS,
}


class BenefitType(StrEnum):
    PROGRESSIVE = "progressive fixed amount"
    ONE_OFF = "one-off fixed amount"
    REIMBURSEMENT = "reimbursement"


class DelayPeriodRule(StrEnum):
    """How a flight delay is measured. The old and new wordings differ."""

    OLD = "old-wording rule"
    NEW = "new-wording rule"

    @classmethod
    def of(cls, wording: Wording) -> "DelayPeriodRule":
        return cls.OLD if wording is Wording.OLD else cls.NEW


class ExclusionType(StrEnum):
    """What an exclusion is about, so that it lines up across Products and Wording versions.

    Each Benefit has a fixed list drawn from the reference clauses. Anything
    else, including every general exclusion, is "other".
    """

    # Flight delay
    OWN_REASON = "own reason or missed flight"
    TYPHOON_WARNING = "typhoon warning at purchase"
    STRIKE = "strike at purchase"
    LATE_CHECK_IN = "late check-in"
    FIRST_REPLACEMENT_NOT_TAKEN = "first replacement not taken"
    SELF_ARRANGED_ELSEWHERE = "self-arranged replacement to another destination"
    AIRLINE_INSOLVENCY = "airline insolvency"

    OTHER = "other"


# The exclusion types of each Benefit, besides OTHER. A Benefit not listed yet has only OTHER.
EXCLUSION_TYPES: dict[Benefit, tuple[ExclusionType, ...]] = {
    Benefit.FLIGHT_DELAY: (
        ExclusionType.OWN_REASON,
        ExclusionType.TYPHOON_WARNING,
        ExclusionType.STRIKE,
        ExclusionType.LATE_CHECK_IN,
        ExclusionType.FIRST_REPLACEMENT_NOT_TAKEN,
        ExclusionType.SELF_ARRANGED_ELSEWHERE,
        ExclusionType.AIRLINE_INSOLVENCY,
    ),
}

# The coverage requirements a Condition of each Benefit may state.
COVERAGE_REQUIREMENTS: dict[Benefit, tuple[str, ...]] = {
    Benefit.FLIGHT_DELAY: ("scheduled flight", "as a passenger"),
}

# The coverage requirements of each Benefit that are covered causes: a provision
# that concerns the Cause, so its judgement may turn on how the Cause is
# classified. Flight delay lists no covered causes.
COVERED_CAUSES: dict[Benefit, tuple[str, ...]] = {
    Benefit.FLIGHT_DELAY: (),
}

# "Applies to" names Condition keys, Benefits, or this, for every Condition.
ALL = "all"

_CLAUSE_REFERENCE = re.compile(r"第\s*([一二三四五六七八九十百零〇]+|\d+)\s*條\s*(.*)")


@dataclass(frozen=True)
class ClauseRef:
    """A Clause, or an item within it, as cited: 第三十一條, or 第三十一條 二."""

    number: int
    item: str | None = None

    def __str__(self) -> str:
        clause = f"第{format_numeral(self.number)}條"
        return f"{clause} {self.item}" if self.item else clause

    @classmethod
    def parse(cls, text: str) -> Self | None:
        match = _CLAUSE_REFERENCE.fullmatch(text.strip())
        if match is None:
            return None
        return cls(parse_numeral(match.group(1)), match.group(2) or None)


@dataclass(frozen=True)
class Condition:
    """The smallest unit that independently decides one payout."""

    # Unique within the Product and Wording version, and the same when the
    # same text is imported again: the Benefit, plus a short covered-event
    # label when the Benefit has several Conditions.
    key: str
    product: str
    wording: Wording
    benefit: Benefit
    covered_event: str
    coverage_requirements: tuple[str, ...]
    coverage_window: str | None
    threshold_hours: float | None
    delay_period_rule: DelayPeriodRule | None
    benefit_type: BenefitType
    step_hours: float | None
    max_claims_per_period: int | None
    aggregate_limit_group: str | None
    eligible_costs: tuple[str, ...]
    cost_maximums: str | None
    clause: ClauseRef


@dataclass(frozen=True)
class Exclusion:
    """One excluded item, judged and cited on its own."""

    product: str
    wording: Wording
    type: ExclusionType
    # Condition keys, Benefits (all their Conditions), or ALL.
    applies_to: tuple[str, ...]
    text: str
    proviso: str | None
    concerns_cause: bool
    clause: ClauseRef

    def applies_to_condition(self, condition: Condition) -> bool:
        """Whether "applies to" names the Condition: by its key, its Benefit, or all."""
        return bool({condition.key, str(condition.benefit), ALL}.intersection(self.applies_to))
