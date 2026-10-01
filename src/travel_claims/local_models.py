"""The local-models port: every model call the application makes goes through it.

It has five entries: extract the Conditions and exclusions a Clause states,
extract the facts of a Scenario, judge one provision against the facts, index
the Clauses of a Product, and find the Clauses that bear on the facts. The
real adapter serves them from models on this machine. Tests substitute a
scripted fake, and nothing else.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from travel_claims.conditions import Benefit, BenefitType, ClauseRef, ExclusionType
from travel_claims.policies import Clause, Wording

# Extracting from a Clause ----------------------------------------------------


class ClauseRole(StrEnum):
    """Why a Clause is extracted: what it is expected to state."""

    DEFINITIONS = "definitions"
    GENERAL_EXCLUSIONS = "general exclusions"
    POLICY_PERIOD = "policy period"
    BENEFIT_COVER = "benefit cover"
    BENEFIT_EXCLUSIONS = "benefit exclusions"


@dataclass(frozen=True)
class ExtractionRequest:
    clause: Clause
    role: ClauseRole
    # The Benefit a cover or exclusions Clause belongs to.
    benefit: Benefit | None
    # The other Clauses of the same chapter.
    context: tuple[Clause, ...]


@dataclass(frozen=True)
class ExtractedCondition:
    covered_event: str
    # Values from the Benefit's list in conditions.COVERAGE_REQUIREMENTS.
    coverage_requirements: tuple[str, ...]
    threshold_hours: float | None
    benefit_type: BenefitType
    step_hours: float | None
    max_claims_per_period: int | None
    # Tells apart the Conditions of a Benefit that has several, such as
    # "strike" for trip cancellation. None when the Benefit has one.
    label: str | None = None
    # None when the Condition is covered within the policy period.
    coverage_window: str | None = None
    eligible_costs: tuple[str, ...] = ()
    cost_maximums: str | None = None
    # The item of the Clause that states the Condition, such as 三.
    item: str | None = None


@dataclass(frozen=True)
class ExtractedExclusion:
    type: ExclusionType
    # Verbatim from the Clause.
    text: str
    concerns_cause: bool
    proviso: str | None = None
    # The item of the Clause that states the exclusion, such as 二.
    item: str | None = None


@dataclass(frozen=True)
class Extraction:
    # Only from a Benefit's cover Clause. Exclusions may come from any Clause,
    # such as a definition that leaves something out.
    conditions: tuple[ExtractedCondition, ...] = ()
    exclusions: tuple[ExtractedExclusion, ...] = ()
    # What a policy-period Clause says the policy period is.
    policy_period: str | None = None


# The facts of a Scenario ---------------------------------------------------------


class Leg(StrEnum):
    OUTBOUND = "outbound"
    RETURN = "return"


class ArrangedBy(StrEnum):
    AIRLINE = "airline"
    INSURED = "insured"


@dataclass(frozen=True)
class Replacement:
    """A replacement flight, offered or taken."""

    departure: datetime | None
    arranged_by: ArrangedBy | None
    taken: bool | None
    # For a replacement the insured arranged.
    arranged_at: datetime | None = None
    destination: str | None = None
    # Whether it flies to Taiwan (the Republic of China): a self-arranged
    # replacement home counts toward the delay period whenever it was arranged.
    returns_to_taiwan: bool | None = None


@dataclass(frozen=True)
class Incident:
    """One incident of a Scenario, such as a delay of the outbound flight."""

    leg: Leg | None
    airport: str | None
    transport: str | None
    scheduled_departure: datetime | None = None
    actual_departure: datetime | None = None
    cancelled: bool = False
    replacements: tuple[Replacement, ...] = ()
    missed_connection: bool = False
    # A delay stated without times.
    stated_delay: timedelta | None = None


@dataclass(frozen=True)
class ScenarioFacts:
    """What a Scenario states, and nothing more."""

    benefits: tuple[Benefit, ...]
    incidents: tuple[Incident, ...]
    cause: str | None = None
    purchased_at: datetime | None = None
    policy_period: tuple[datetime, datetime] | None = None
    # Whether the trip is within the policy period, when the Scenario says so
    # without giving the period's dates (保險期間內).
    within_policy_period: bool | None = None
    # Warnings or strikes in force when the policy was bought.
    in_force_at_purchase: tuple[str, ...] = ()
    earlier_claims: int | None = None


# Judging one provision -----------------------------------------------------------


class ProvisionKind(StrEnum):
    COVERED_EVENT = "covered event"
    COVERAGE_REQUIREMENT = "coverage requirement"
    EXCLUSION = "exclusion"
    PROVISO = "proviso"


@dataclass(frozen=True)
class Provision:
    kind: ProvisionKind
    text: str
    clause: ClauseRef
    # Whether the judgement may turn on the Cause: an exclusion the workbook
    # marks so, its proviso, or a covered-cause requirement.
    concerns_cause: bool


@dataclass(frozen=True)
class JudgementRequest:
    provision: Provision
    facts: ScenarioFacts
    # The provision's own Clause, and related Clauses as context.
    clauses: tuple[Clause, ...]


@dataclass(frozen=True)
class Settled:
    """The Clause text settles the provision.

    Met means within, for a covered event or requirement, or applies, for an
    exclusion or proviso.
    """

    met: bool


@dataclass(frozen=True)
class Reading:
    """One plausible classification of the Cause."""

    cause: str
    met: bool


@dataclass(frozen=True)
class TurnsOnCause:
    readings: tuple[Reading, ...]


@dataclass(frozen=True)
class NeedsFact:
    fact: str


@dataclass(frozen=True)
class NotSettled:
    """The Clause text does not settle the situation."""

    unaddressed: str


Judgement = Settled | TurnsOnCause | NeedsFact | NotSettled


# The port ------------------------------------------------------------------------


class LocalModels(Protocol):
    def extract(self, request: ExtractionRequest) -> Extraction:
        """The Conditions and exclusions one Clause states."""
        ...

    def extract_facts(self, scenario: str) -> ScenarioFacts:
        """What a Scenario, described in free text, states."""
        ...

    def judge(self, request: JudgementRequest) -> Judgement:
        """Judge one provision against the facts of a Scenario.

        A provision that does not concern the Cause is never answered TurnsOnCause.
        """
        ...

    def index(self, product: str, wording: Wording, clauses: Sequence[Clause]) -> None:
        """Index the Clauses of one Product in one Wording version for find_related."""
        ...

    def find_related(self, product: str, wording: Wording, facts: ScenarioFacts) -> tuple[int, ...]:
        """Numbers of the Clauses of one Product in one Wording version that bear on the facts."""
        ...
