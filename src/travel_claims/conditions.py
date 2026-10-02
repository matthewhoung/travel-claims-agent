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

    # Baggage delay
    RETURN_TO_TAIWAN_AIRPORT = "delay on return to an airport in Taiwan"
    RETURN_HOME = "delay on return home"
    SENT_SEPARATELY = "baggage sent in advance or separately"

    # Baggage loss: the items not covered
    BUSINESS_GOODS_AND_VALUABLES = "business goods, vehicles, jewellery or phones"
    MONEY_AND_DOCUMENTS = "money, securities, tickets or travel documents"
    MANUSCRIPTS_AND_SAMPLES = "manuscripts, samples or business records"
    CONTRABAND = "contraband or illegal goods"
    CONTAINERS = "suitcases and other containers"
    RENTED_EQUIPMENT = "rented equipment"
    STORED_DATA = "stored data"
    FRAGILE_ITEMS = "fragile items"
    PAYMENT_CARDS = "payment cards"
    # Baggage loss: the incidents not covered
    WEAR_AND_DEFECTS = "wear, decay or inherent defect"
    REPAIR_OR_CLEANING = "repair, cleaning or alteration"
    RIOT_OR_REVOLUTION = "riot, rebellion or revolution"
    CARRIER_OR_HOTEL_COMPENSATES = "compensated by a carrier or hotel"
    APPEARANCE_ONLY = "damage to appearance only"
    LIQUID_LEAKAGE = "liquid leakage"
    CARRIER_NOT_NOTIFIED = "carrier not notified"
    UNEXPLAINED_LOSS = "unexplained loss"

    # Loss of travel documents
    NOT_REPORTED_TO_POLICE = "not reported to the police within 24 hours"

    # Trip cancellation and trip change
    REFUNDABLE = "refundable or repaid in kind"
    LAW_OR_GOVERNMENT_ORDER = "law or government order"
    AGENCY_OR_CARRIER_INSOLVENCY = "travel agency or carrier insolvency"
    OCCURRED_AT_PURCHASE = "incident already occurred at purchase"
    LATE_NOTICE = "agency or providers not notified in time"
    COSTS_IN_TAIWAN = "lodging and transport costs in Taiwan"

    OTHER = "other"


# The exclusion types of each Benefit, besides OTHER, in the order of the
# reference clauses. A Benefit not listed yet has only OTHER.
EXCLUSION_TYPES: dict[Benefit, tuple[ExclusionType, ...]] = {
    Benefit.TRIP_CANCELLATION: (
        ExclusionType.REFUNDABLE,
        ExclusionType.LAW_OR_GOVERNMENT_ORDER,
        ExclusionType.AGENCY_OR_CARRIER_INSOLVENCY,
        ExclusionType.OCCURRED_AT_PURCHASE,
        ExclusionType.STRIKE,
        ExclusionType.LATE_NOTICE,
    ),
    Benefit.FLIGHT_DELAY: (
        ExclusionType.OWN_REASON,
        ExclusionType.TYPHOON_WARNING,
        ExclusionType.STRIKE,
        ExclusionType.LATE_CHECK_IN,
        ExclusionType.FIRST_REPLACEMENT_NOT_TAKEN,
        ExclusionType.SELF_ARRANGED_ELSEWHERE,
        ExclusionType.AIRLINE_INSOLVENCY,
    ),
    Benefit.TRIP_CHANGE: (
        ExclusionType.LAW_OR_GOVERNMENT_ORDER,
        ExclusionType.AGENCY_OR_CARRIER_INSOLVENCY,
        ExclusionType.OCCURRED_AT_PURCHASE,
        ExclusionType.TYPHOON_WARNING,
        ExclusionType.STRIKE,
        ExclusionType.LATE_NOTICE,
        ExclusionType.FIRST_REPLACEMENT_NOT_TAKEN,
        ExclusionType.COSTS_IN_TAIWAN,
    ),
    Benefit.BAGGAGE_DELAY: (
        ExclusionType.RETURN_TO_TAIWAN_AIRPORT,
        ExclusionType.RETURN_HOME,
        ExclusionType.SENT_SEPARATELY,
    ),
    Benefit.BAGGAGE_LOSS: (
        ExclusionType.BUSINESS_GOODS_AND_VALUABLES,
        ExclusionType.MONEY_AND_DOCUMENTS,
        ExclusionType.MANUSCRIPTS_AND_SAMPLES,
        ExclusionType.CONTRABAND,
        ExclusionType.SENT_SEPARATELY,
        ExclusionType.CONTAINERS,
        ExclusionType.RENTED_EQUIPMENT,
        ExclusionType.STORED_DATA,
        ExclusionType.FRAGILE_ITEMS,
        ExclusionType.PAYMENT_CARDS,
        ExclusionType.WEAR_AND_DEFECTS,
        ExclusionType.REPAIR_OR_CLEANING,
        ExclusionType.RIOT_OR_REVOLUTION,
        ExclusionType.CARRIER_OR_HOTEL_COMPENSATES,
        ExclusionType.APPEARANCE_ONLY,
        ExclusionType.LIQUID_LEAKAGE,
        ExclusionType.CARRIER_NOT_NOTIFIED,
        ExclusionType.UNEXPLAINED_LOSS,
    ),
    Benefit.TRAVEL_DOCUMENT_LOSS: (ExclusionType.NOT_REPORTED_TO_POLICE,),
}

# The coverage requirements of each Benefit that are covered causes: a provision
# that concerns the Cause, so its judgement may turn on how the Cause is
# classified. Flight delay lists no covered causes. The covered causes of the
# old and new wordings differ in detail, such as the old trip change covering
# a relative's death and the new also a critical illness, but line up.
COVERED_CAUSES: dict[Benefit, tuple[str, ...]] = {
    Benefit.TRIP_CANCELLATION: (
        "death or critical illness of the insured or a relative",
        "witness in a court case in Taiwan",
        "strike cancelling or delaying the booked transport",
        "riot or civil commotion at the destination",
        "home damaged by fire or natural disaster",
    ),
    Benefit.FLIGHT_DELAY: (),
    Benefit.TRIP_CHANGE: (
        "strike of the booked transport",
        "war, riot or natural disaster where the insured is or is going",
        "death or critical illness of a spouse or relative in Taiwan",
        "travel documents robbed, stolen or lost",
        "accident of the transport taken",
    ),
}

# The coverage requirements a Condition of each Benefit may state. A Condition
# of a Benefit that lists covered causes states one of them: each covered
# cause is its own Condition, since all of a Condition's requirements must be met.
COVERAGE_REQUIREMENTS: dict[Benefit, tuple[str, ...]] = {
    Benefit.TRIP_CANCELLATION: COVERED_CAUSES[Benefit.TRIP_CANCELLATION],
    Benefit.FLIGHT_DELAY: ("scheduled flight", "as a passenger"),
    Benefit.TRIP_CHANGE: COVERED_CAUSES[Benefit.TRIP_CHANGE],
}


class CostCategory(StrEnum):
    """What a cost is for: a reimbursement Benefit pays some categories and not others."""

    TOUR_FEE = "tour fee"
    TRANSPORT = "transport"
    LODGING = "lodging"
    TICKETS = "tickets"
    MEALS = "meals"
    OTHER = "other"


# The cost categories a reimbursement Benefit may pay, in the order of the
# reference clauses: trip cancellation the prepaid tour fee, transport, lodging
# and tickets that cannot be refunded; trip change the added transport or lodging.
ELIGIBLE_COSTS: dict[Benefit, tuple[CostCategory, ...]] = {
    Benefit.TRIP_CANCELLATION: (
        CostCategory.TOUR_FEE,
        CostCategory.TRANSPORT,
        CostCategory.LODGING,
        CostCategory.TICKETS,
    ),
    Benefit.TRIP_CHANGE: (CostCategory.TRANSPORT, CostCategory.LODGING),
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
    # How many days before the trip's departure a window like trip
    # cancellation's opens; it closes when the overseas travel period begins.
    window_days: int | None
    threshold_hours: float | None
    delay_period_rule: DelayPeriodRule | None
    benefit_type: BenefitType
    step_hours: float | None
    max_claims_per_period: int | None
    aggregate_limit_group: str | None
    # Values from the Benefit's list in ELIGIBLE_COSTS.
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


class Availability(StrEnum):
    """Whether a Benefit amount is known: published, or why it is not available."""

    PUBLISHED = "published"
    NOT_PUBLISHED = "not published"
    NOT_COLLECTED = "not collected"


@dataclass(frozen=True)
class Amount:
    """A row of the Amounts sheet: a Condition's Benefit amount under a Plan, and its source.

    Amounts are whole NT$. For a progressive fixed amount the Benefit amount is
    per step; for a reimbursement Condition it is the Plan's limit. A row that
    is not published or not collected may leave the Plan, the amounts and the
    source empty, and may name ALL in place of a Condition key.
    """

    condition: str
    availability: Availability
    plan: str | None = None
    benefit_amount: int | None = None
    max_per_incident: int | None = None
    source: str | None = None


def nt_dollars(amount: int) -> str:
    """A whole amount of NT$, as in NT$12,000."""
    return f"NT${amount:,}"
