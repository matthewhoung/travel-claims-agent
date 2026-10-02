"""Draft the condition table of a Product from its Clauses, through the local models.

Extraction covers the general provisions (definitions, general exclusions and
the policy period) and the travel-inconvenience cover, Benefit by Benefit. The
policy's other Clauses are stored and indexed but not extracted.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace

from travel_claims.conditions import (
    ALL,
    BENEFIT_NAMES,
    Benefit,
    BenefitType,
    ClauseRef,
    Condition,
    DelayPeriodRule,
    Exclusion,
)
from travel_claims.local_models import (
    ClauseRole,
    ExtractedCondition,
    Extraction,
    ExtractionRequest,
    LocalModels,
)
from travel_claims.policies import Clause, Wording

# Trip cancellation, flight delay and trip change are judged. Baggage delay,
# baggage loss and loss of travel documents are extracted for the Alignment
# table only.
_EXTRACTED_BENEFITS = (
    Benefit.TRIP_CANCELLATION,
    Benefit.FLIGHT_DELAY,
    Benefit.TRIP_CHANGE,
    Benefit.BAGGAGE_DELAY,
    Benefit.BAGGAGE_LOSS,
    Benefit.TRAVEL_DOCUMENT_LOSS,
)


@dataclass(frozen=True)
class _ClauseExtraction:
    clause: Clause
    benefit: Benefit | None
    extraction: Extraction


def draft_table(
    product: str, wording: Wording, clauses: Sequence[Clause], models: LocalModels
) -> tuple[list[Condition], list[Exclusion]]:
    """The draft Conditions and exclusions of a Product in a Wording version."""
    extracted = []
    for clause in clauses:
        scope = _scope(clause)
        if scope is None:
            continue
        role, benefit = scope
        context = tuple(c for c in clauses if c.chapter == clause.chapter and c is not clause)
        extraction = models.extract(ExtractionRequest(clause, role, benefit, context))
        if extraction.conditions and role is not ClauseRole.BENEFIT_COVER:
            raise ValueError(
                f"the local models returned Conditions for {ClauseRef(clause.number)} "
                f"{clause.heading}, which is not a Benefit's cover Clause"
            )
        extracted.append(_ClauseExtraction(clause, benefit, extraction))

    policy_period = "\n".join(
        e.extraction.policy_period for e in extracted if e.extraction.policy_period
    )
    conditions = _conditions(product, wording, extracted, policy_period or None)
    exclusions = [
        Exclusion(
            product=product,
            wording=wording,
            type=exclusion.type,
            applies_to=_applies_to(e.benefit, conditions),
            text=exclusion.text,
            proviso=exclusion.proviso,
            concerns_cause=exclusion.concerns_cause,
            clause=ClauseRef(e.clause.number, exclusion.item),
        )
        for e in extracted
        for exclusion in e.extraction.exclusions
    ]
    return conditions, exclusions


def _scope(clause: Clause) -> tuple[ClauseRole, Benefit | None] | None:
    """Why `clause` is extracted, and for which Benefit; None if it is not."""
    heading = clause.heading
    if "用詞定義" in heading or "名詞定義" in heading:
        return ClauseRole.DEFINITIONS, None
    if "共同不保事項" in heading:
        return ClauseRole.GENERAL_EXCLUSIONS, None
    if heading.startswith("保險期間"):
        return ClauseRole.POLICY_PERIOD, None
    # A Benefit is named in its chapter title or in its Clause headings.
    names = f"{clause.chapter or ''}{heading}"
    benefit = next((b for name, b in BENEFIT_NAMES.items() if name in names), None)
    if benefit not in _EXTRACTED_BENEFITS:
        return None
    if "承保範圍" in heading:
        return ClauseRole.BENEFIT_COVER, benefit
    if "不保" in heading or "除外" in heading:
        return ClauseRole.BENEFIT_EXCLUSIONS, benefit
    return None


def _conditions(
    product: str, wording: Wording, extracted: list[_ClauseExtraction], policy_period: str | None
) -> list[Condition]:
    # Only a Benefit's cover Clause states Conditions.
    found: list[tuple[Benefit, Clause, ExtractedCondition]] = [
        (e.benefit, e.clause, condition)
        for e in extracted
        if e.benefit is not None
        for condition in e.extraction.conditions
    ]
    keys = _keys([(benefit, condition.label) for benefit, _, condition in found])
    conditions = [
        Condition(
            key=key,
            product=product,
            wording=wording,
            benefit=benefit,
            covered_event=condition.covered_event,
            coverage_requirements=condition.coverage_requirements,
            coverage_window=condition.coverage_window or policy_period,
            window_days=condition.window_days,
            threshold_hours=condition.threshold_hours,
            delay_period_rule=(
                DelayPeriodRule.of(wording) if benefit is Benefit.FLIGHT_DELAY else None
            ),
            benefit_type=condition.benefit_type,
            step_hours=condition.step_hours,
            max_claims_per_period=condition.max_claims_per_period,
            aggregate_limit_group=None,
            eligible_costs=condition.eligible_costs,
            cost_maximums=condition.cost_maximums,
            clause=ClauseRef(clause.number, condition.item),
        )
        for key, (benefit, clause, condition) in zip(keys, found, strict=True)
    ]
    capped = {e.benefit for e in extracted if e.extraction.caps_period_total}
    return [
        replace(c, aggregate_limit_group=str(c.benefit))
        if c.benefit in _grouped(conditions, capped)
        else c
        for c in conditions
    ]


def _grouped(conditions: list[Condition], capped: set[Benefit | None]) -> set[Benefit]:
    """The Benefits whose Conditions share one Aggregate limit: those whose own Clause caps
    the total reimbursed in the policy period, and that have several Conditions to share it."""
    reimbursed = Counter(
        c.benefit for c in conditions if c.benefit_type is BenefitType.REIMBURSEMENT
    )
    return {
        benefit
        for benefit, count in reimbursed.items()
        if benefit in capped
        and count > 1
        and count == sum(c.benefit is benefit for c in conditions)
    }


def _keys(labelled: list[tuple[Benefit, str | None]]) -> list[str]:
    """Condition keys: the Benefit, plus the covered-event label if there is one.

    A key that would repeat, or would be the bare name of a Benefit with
    several Conditions, which "Applies to" reads as all of them, is numbered
    in Clause order. So the same extraction always gives the same keys.
    """
    bases = [
        f"{benefit} / {label}" if label and label != benefit else str(benefit)
        for benefit, label in labelled
    ]
    repeats = Counter(bases)
    per_benefit = Counter(benefit for benefit, _ in labelled)
    keys = []
    numbered: Counter[str] = Counter()
    for (benefit, _), base in zip(labelled, bases, strict=True):
        if repeats[base] > 1 or (base == benefit and per_benefit[benefit] > 1):
            numbered[base] += 1
            keys.append(f"{base} ({numbered[base]})")
        else:
            keys.append(base)
    return keys


def _applies_to(benefit: Benefit | None, conditions: list[Condition]) -> tuple[str, ...]:
    """An exclusion in a Benefit's own Clauses applies to its Conditions; any other, to all."""
    if benefit is None:
        return (ALL,)
    return tuple(c.key for c in conditions if c.benefit is benefit) or (str(benefit),)
