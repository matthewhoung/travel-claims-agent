"""Judge a Scenario against confirmed condition tables: the Verdict matrix.

Judging is one pass through a LangGraph graph: read the facts, select the
Conditions, check what code can check, judge the provisions one at a time,
and derive the outcomes. Code derives every outcome; the local models only
read the facts and judge single provisions (ADR 0001).
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from travel_claims.clause_store import ClauseStore
from travel_claims.conditions import (
    COVERED_CAUSES,
    Availability,
    Benefit,
    BenefitType,
    ClauseRef,
    Condition,
    DelayPeriodRule,
    ExclusionType,
)
from travel_claims.delay_period import (
    FORCE_MAJEURE_RULE,
    Measured,
    MissingFact,
    NothingCounts,
    measure,
)
from travel_claims.loading import ConditionTable
from travel_claims.local_models import (
    Incident,
    Judgement,
    JudgementRequest,
    LocalModels,
    NeedsFact,
    NotSettled,
    Provision,
    ProvisionKind,
    ScenarioFacts,
    Settled,
    TurnsOnCause,
)
from travel_claims.policies import Clause, Wording


class Verdict(StrEnum):
    PAID = "paid"
    NOT_PAID = "not paid"
    UNDETERMINED = "undetermined"


class Reason(StrEnum):
    """Why an outcome is undetermined. A cell takes the first, in this order, of its Conditions'."""

    MISSING_FACT = "missing fact"
    CAUSE_AMBIGUOUS = "Cause ambiguous"
    CLAUSES_SILENT = "Clauses silent"


class OutOfContract(Exception):
    """The local models answered in a way the port does not allow."""


@dataclass(frozen=True)
class ReadingOutcome:
    """A Condition's outcome under one plausible classification of the Cause."""

    cause: str
    verdict: Verdict
    grounds: str
    clause: ClauseRef
    reason: Reason | None = None
    # The delay period under this reading, when code measured one.
    delay: timedelta | None = None


# The old wording's delay-period rule turns on the Cause with the proviso it
# shares with the first-replacement exclusion. Code measures it under each of
# the proviso's readings; the local models never judge it.
DELAY_PERIOD_RULE: Final = "delay-period rule"


@dataclass(frozen=True)
class TurningProvision:
    """A provision whose judgement turns on the Cause, with the outcome under each reading."""

    kind: ProvisionKind | Literal["delay-period rule"]
    text: str
    clause: ClauseRef
    readings: tuple[ReadingOutcome, ...]


@dataclass(frozen=True)
class PlanAmount:
    """What a paid outcome pays under one Plan, from a published Benefit amount."""

    plan: str
    # In whole NT$: per step for a progressive fixed amount, once for a one-off
    # fixed amount, the Plan's limit for reimbursement.
    benefit_amount: int
    # A fixed amount's total: the steps times the amount, capped at the maximum
    # per incident. None for a progressive benefit with no maximum, whose
    # amount per step and step count are shown instead, and for reimbursement.
    total: int | None
    source: str


@dataclass(frozen=True)
class ConditionOutcome:
    """The outcome of one Condition for one incident of the Scenario."""

    condition: str
    # The incident's number among the facts' incidents, from 1.
    incident: int
    verdict: Verdict
    # For a paid outcome, what is paid; for a not-paid one, the threshold,
    # window, requirement or exclusion that decides it; for an undetermined
    # one, the missing fact, the provisions that turn on the Cause, or what
    # the Clauses leave unaddressed.
    grounds: str
    clause: ClauseRef
    # The delay period, when code measured one and it is the same under every reading.
    delay: timedelta | None = None
    # Full steps of a progressive benefit that is paid.
    steps: int | None = None
    # Only for an undetermined outcome.
    reason: Reason | None = None
    # For a Cause-ambiguous outcome, each provision it turns on.
    turns_on: tuple[TurningProvision, ...] = ()
    # For a paid outcome, what each Plan pays, where its amount is published.
    # The Verdict never depends on it.
    amounts: tuple[PlanAmount, ...] = ()


@dataclass(frozen=True)
class Cell:
    """One Product in one Wording version."""

    product: str
    wording: Wording
    verdict: Verdict
    outcomes: tuple[ConditionOutcome, ...]
    # Only for an undetermined cell.
    reason: Reason | None = None


@dataclass(frozen=True)
class VerdictMatrix:
    scenario: str
    # What the local models read from the Scenario, shown so that a misreading is seen.
    facts: ScenarioFacts
    cells: tuple[Cell, ...]


# Benefits judged so far.
_JUDGED = (Benefit.FLIGHT_DELAY,)


def judge(
    scenario: str,
    tables: Sequence[ConditionTable],
    store: ClauseStore,
    models: LocalModels,
) -> VerdictMatrix:
    """The Verdict matrix of a Scenario: one cell per condition table, in the order given."""
    graph = StateGraph(_State)
    graph.add_node("facts", lambda state: _facts(state, models))
    graph.add_node("select", _select)
    graph.add_node("check", _check)
    graph.add_node("judge", lambda state: _judge(state, store, models))
    graph.add_node("outcome", _outcome)
    graph.add_edge(START, "facts")
    graph.add_edge("facts", "select")
    graph.add_edge("select", "check")
    graph.add_edge("check", "judge")
    graph.add_edge("judge", "outcome")
    graph.add_edge("outcome", END)
    # One pass: no checkpointer, so judging never pauses.
    final = graph.compile().invoke({"scenario": scenario, "tables": tuple(tables)})
    matrix = final["matrix"]
    assert isinstance(matrix, VerdictMatrix)
    return matrix


@dataclass(frozen=True)
class _ConditionIncident:
    """One Condition of one cell, for one incident, as judging fills it in."""

    table: ConditionTable
    condition: Condition
    incident: int
    delay: timedelta | None = None
    # By the old-wording rule, the delay period if force majeure prevented the
    # insured from taking the first replacement flight, when it differs from `delay`.
    force_majeure_delay: Measured | None = None
    # Facts the threshold or a window needs that the Scenario does not state.
    missing: tuple[str, ...] = ()
    # A threshold or window that code found not met, and its Clause.
    not_met: tuple[str, ClauseRef] | None = None
    judgements: tuple["_Judged", ...] = ()


@dataclass(frozen=True)
class _Judged:
    provision: Provision
    judgement: Judgement
    # An exclusion's proviso, judged unless the exclusion surely does not apply.
    proviso: "_Judged | None" = None
    # Whether this is the first-replacement exclusion, whose proviso the
    # old-wording delay-period rule shares.
    force_majeure: bool = False


class _State(TypedDict, total=False):
    scenario: str
    tables: tuple[ConditionTable, ...]
    facts: ScenarioFacts
    items: tuple[_ConditionIncident, ...]
    matrix: VerdictMatrix


def _facts(state: _State, models: LocalModels) -> _State:
    return {"facts": models.extract_facts(state["scenario"])}


def _select(state: _State) -> _State:
    """Code selects the Conditions that cover each Benefit the Scenario touches."""
    facts = state["facts"]
    return {
        "items": tuple(
            _ConditionIncident(table, condition, number)
            for table in state["tables"]
            for condition in table.conditions
            if condition.benefit in facts.benefits and condition.benefit in _JUDGED
            for number in range(1, len(facts.incidents) + 1)
        )
    }


def _check(state: _State) -> _State:
    """Code measures the delay period and checks the threshold and the policy period."""
    facts = state["facts"]
    policy_ends = facts.policy_period[1] if facts.policy_period else None
    checked = []
    for item in state["items"]:
        condition = item.condition
        incident = facts.incidents[item.incident - 1]
        rule = condition.delay_period_rule
        assert rule is not None  # Load requires it of a flight delay
        delay = measure(incident, rule, policy_ends)
        if isinstance(delay, timedelta):
            item = replace(item, delay=delay)
        if rule is DelayPeriodRule.OLD:
            force_majeure = measure(incident, rule, policy_ends, force_majeure=True)
            if force_majeure != delay:
                item = replace(item, force_majeure_delay=force_majeure)
        missing = _missing_for_window(facts, incident)
        if isinstance(delay, MissingFact) and delay.fact not in missing:
            missing.append(delay.fact)
        if missing:
            item = replace(item, missing=tuple(missing))
        elif (window := _outside_policy_period(facts, incident)) is not None:
            item = replace(item, not_met=(window, condition.clause))
        elif isinstance(delay, NothingCounts):
            item = replace(
                item,
                not_met=(
                    f"no replacement flight counts toward the delay period: {delay.why}",
                    condition.clause,
                ),
            )
        elif isinstance(delay, timedelta) and all(
            _under_threshold(d, condition)
            for d in (delay, item.force_majeure_delay)
            if d is not None
        ):
            # Under the threshold under every reading of the Cause.
            readings = item.force_majeure_delay
            under = _threshold_not_met(
                condition, delay, readings if isinstance(readings, timedelta) else None
            )
            item = replace(item, not_met=(under, condition.clause))
        checked.append(item)
    return {"items": tuple(checked)}


def _under_threshold(delay: Measured, condition: Condition) -> bool:
    if isinstance(delay, NothingCounts):
        return True
    threshold = timedelta(hours=condition.threshold_hours or 0)
    return isinstance(delay, timedelta) and delay < threshold


def _threshold_not_met(
    condition: Condition, delay: timedelta, force_majeure_delay: timedelta | None = None
) -> str:
    """Why the threshold is not met: under `delay`, and under `force_majeure_delay` if given."""
    measured = f"a delay of {_duration(delay)}"
    if force_majeure_delay is not None:
        measured += (
            f", or {_duration(force_majeure_delay)} if force majeure prevented taking "
            "the first replacement flight"
        )
    return f"{measured}, under the threshold of {condition.threshold_hours:g} hours"


def _missing_for_window(facts: ScenarioFacts, incident: Incident) -> list[str]:
    """The facts the policy-period check needs that the Scenario does not state."""
    if facts.policy_period is None:
        return [] if facts.within_policy_period is not None else ["the policy period"]
    if incident.scheduled_departure is None:
        return ["the booked flight's scheduled departure"]
    return []


def _outside_policy_period(facts: ScenarioFacts, incident: Incident) -> str | None:
    """Why the booked flight is not covered by the policy period; None if it is."""
    if facts.policy_period is None:
        return None if facts.within_policy_period else _STATED_OUTSIDE
    assert incident.scheduled_departure is not None
    starts, ends = facts.policy_period
    if starts <= incident.scheduled_departure <= ends:
        return None
    return (
        f"the booked flight's scheduled departure, {_time(incident.scheduled_departure)}, "
        f"is outside the policy period, {_time(starts)} – {_time(ends)}"
    )


_STATED_OUTSIDE = "the Scenario states the trip is outside the policy period"


def _judge(state: _State, store: ClauseStore, models: LocalModels) -> _State:
    """The local models judge each provision of a Condition that passed the code checks.

    The covered event and the coverage requirements come first; the
    exclusions are judged only if the facts may fall within them. An
    exclusion's proviso is judged only if the exclusion may apply.
    """
    facts = state["facts"]
    judged = []
    for item in state["items"]:
        if item.missing or item.not_met is not None:
            judged.append(item)
            continue
        clauses = {c.number: c for c in store.clauses(item.table.product, item.table.wording)}
        incident_facts = replace(facts, incidents=(facts.incidents[item.incident - 1],))
        judgements = [
            _ask(models, provision, incident_facts, clauses)
            for provision in _coverage(item.condition)
        ]
        if not any(_settled(j.judgement, met=False) for j in judgements):
            for exclusion, proviso, force_majeure in _exclusions(item):
                judged_exclusion = replace(
                    _ask(models, exclusion, incident_facts, clauses), force_majeure=force_majeure
                )
                if proviso is not None and not _settled(judged_exclusion.judgement, met=False):
                    judged_exclusion = replace(
                        judged_exclusion, proviso=_ask(models, proviso, incident_facts, clauses)
                    )
                judgements.append(judged_exclusion)
        judged.append(replace(item, judgements=tuple(judgements)))
    return {"items": tuple(judged)}


def _ask(
    models: LocalModels, provision: Provision, facts: ScenarioFacts, clauses: dict[int, Clause]
) -> _Judged:
    """Judge one provision, with its Clause, and hold the answer to the port's contract."""
    judgement = models.judge(
        JudgementRequest(provision, facts, (clauses[provision.clause.number],))
    )
    if isinstance(judgement, TurnsOnCause) and not provision.concerns_cause:
        raise OutOfContract(
            f"the local models answered that the {provision.kind} of {provision.clause} "
            f"turns on the Cause, which only a provision that concerns the Cause may: "
            f"{provision.text}"
        )
    return _Judged(provision, judgement)


def _coverage(condition: Condition) -> list[Provision]:
    event = Provision(ProvisionKind.COVERED_EVENT, condition.covered_event, condition.clause, False)
    # A covered-cause requirement concerns the Cause; any other requirement does not.
    causes = COVERED_CAUSES.get(condition.benefit, ())
    requirements = [
        Provision(
            ProvisionKind.COVERAGE_REQUIREMENT,
            requirement,
            condition.clause,
            requirement in causes,
        )
        for requirement in condition.coverage_requirements
    ]
    return [event, *requirements]


def _exclusions(item: _ConditionIncident) -> list[tuple[Provision, Provision | None, bool]]:
    """The exclusions that apply to the Condition, by its key, its Benefit, or all, each
    with its proviso. A proviso concerns the Cause when its exclusion does.

    Each is marked if it is the first exclusion of the first-replacement type
    with a proviso, whose proviso the old-wording delay-period rule shares.
    """
    found = [e for e in item.table.exclusions if e.applies_to_condition(item.condition)]
    shared = next(
        (
            e
            for e in found
            if e.type is ExclusionType.FIRST_REPLACEMENT_NOT_TAKEN and e.proviso is not None
        ),
        None,
    )
    return [
        (
            Provision(ProvisionKind.EXCLUSION, e.text, e.clause, e.concerns_cause),
            None
            if e.proviso is None
            else Provision(ProvisionKind.PROVISO, e.proviso, e.clause, e.concerns_cause),
            e is shared,
        )
        for e in found
    ]


def _outcome(state: _State) -> _State:
    """Code derives each Condition's outcome, and each cell's Verdict from them."""
    cells = []
    for table in state["tables"]:
        mine = tuple(_condition_outcome(c) for c in state["items"] if c.table is table)
        verdicts = {o.verdict for o in mine}
        if Verdict.PAID in verdicts:
            cells.append(Cell(table.product, table.wording, Verdict.PAID, mine))
        elif Verdict.UNDETERMINED in verdicts:
            precedence = list(Reason)
            reason = min((o.reason for o in mine if o.reason is not None), key=precedence.index)
            cells.append(Cell(table.product, table.wording, Verdict.UNDETERMINED, mine, reason))
        else:
            cells.append(Cell(table.product, table.wording, Verdict.NOT_PAID, mine))
    return {"matrix": VerdictMatrix(state["scenario"], state["facts"], tuple(cells))}


def _condition_outcome(item: _ConditionIncident) -> ConditionOutcome:
    """The outcome order, steps 1 and 2 as far as code checks them; the rest by judgements."""
    # Nothing is judged yet: the delay period is open while it turns on the proviso.
    delay = _delay(item, ())
    if item.missing:
        return _undetermined(
            item,
            Reason.MISSING_FACT,
            f"the Scenario does not state {'; '.join(item.missing)}",
            item.condition.clause,
            delay,
        )
    if item.not_met is not None:
        return _not_paid(item, *item.not_met, delay)
    return _from_judgements(item, item.judgements)


@dataclass(frozen=True)
class _Open:
    """A judgement that is not settled, and where it sits among a Condition's judgements."""

    provision: Provision
    judgement: TurnsOnCause | NeedsFact | NotSettled
    index: int
    in_proviso: bool


def _from_judgements(item: _ConditionIncident, judged: tuple[_Judged, ...]) -> ConditionOutcome:
    """The outcome order from step 2 on: a covered event or requirement not met; an
    exclusion that applies; a judgement that needs a fact; one that turns on the Cause;
    one the Clause text does not settle; otherwise paid.

    While the delay period turns on the force-majeure proviso, the threshold is
    checked under each reading of it, as the proviso's readings are derived.
    """
    measured = _delay(item, judged)
    delay = measured if isinstance(measured, timedelta) else None
    clause = item.condition.clause
    if isinstance(measured, MissingFact):
        reason = f"the Scenario does not state {measured.fact}"
        return _undetermined(item, Reason.MISSING_FACT, reason, clause, delay)
    if isinstance(measured, NothingCounts):
        reason = f"no replacement flight counts toward the delay period: {measured.why}"
        return _not_paid(item, reason, clause, delay)
    if delay is not None and _under_threshold(delay, item.condition):
        return _not_paid(item, _threshold_not_met(item.condition, delay), clause, delay)
    for j in judged:
        if j.provision.kind is not ProvisionKind.EXCLUSION and _settled(j.judgement, met=False):
            return _not_paid(
                item,
                f"outside the {j.provision.kind}: {j.provision.text}",
                j.provision.clause,
                delay,
            )
    for j in judged:
        if j.provision.kind is ProvisionKind.EXCLUSION and _applies(j) is True:
            return _not_paid(
                item, f"the exclusion applies: {j.provision.text}", j.provision.clause, delay
            )

    unsettled = _unsettled(judged)
    needs = [u for u in unsettled if isinstance(u.judgement, NeedsFact)]
    if needs:
        return _undetermined(
            item,
            Reason.MISSING_FACT,
            "; ".join(
                f"the {u.provision.kind} needs a fact the Scenario does not state: "
                f"{u.judgement.fact}"
                for u in needs
                if isinstance(u.judgement, NeedsFact)
            ),
            needs[0].provision.clause,
            delay,
        )
    turning = [u for u in unsettled if isinstance(u.judgement, TurnsOnCause)]
    if turning:
        provisions = [_turning(item, judged, u, turning) for u in turning]
        if measured is None:
            # The delay period turns on the force-majeure proviso: cite the rule too.
            proviso = next(
                p
                for u, p in zip(turning, provisions, strict=True)
                if u.in_proviso and judged[u.index].force_majeure
            )
            rule = TurningProvision(DELAY_PERIOD_RULE, FORCE_MAJEURE_RULE, clause, proviso.readings)
            provisions.insert(0, rule)
        return _undetermined(
            item,
            Reason.CAUSE_AMBIGUOUS,
            "turns on how the Cause is classified, under "
            + "; ".join(f"the {p.kind}: {p.text}" for p in provisions),
            provisions[0].clause,
            delay,
            tuple(provisions),
        )
    silent = [u for u in unsettled if isinstance(u.judgement, NotSettled)]
    if silent:
        return _undetermined(
            item,
            Reason.CLAUSES_SILENT,
            "; ".join(
                f"the Clauses do not settle the {u.provision.kind}: {u.judgement.unaddressed}"
                for u in silent
                if isinstance(u.judgement, NotSettled)
            ),
            silent[0].provision.clause,
            delay,
        )
    assert delay is not None  # an open proviso leaves the outcome undetermined above
    return _paid(item, delay)


def _delay(item: _ConditionIncident, judged: tuple[_Judged, ...]) -> Measured | None:
    """The delay period under the judgements given; None while it turns on the
    force-majeure proviso, which is then open or not yet judged."""
    if item.force_majeure_delay is None:
        return item.delay
    shared = next((j for j in judged if j.force_majeure), None)
    if shared is None:
        return None
    if _settled(shared.judgement, met=False):
        return item.delay
    proviso = shared.proviso.judgement if shared.proviso else None
    if _settled(proviso, met=True):
        return item.force_majeure_delay
    if _settled(proviso, met=False):
        return item.delay
    return None


def _applies(exclusion: _Judged) -> bool | None:
    """Whether an exclusion applies once its proviso is taken into account; None if open."""
    proviso = exclusion.proviso.judgement if exclusion.proviso else None
    if _settled(exclusion.judgement, met=False) or _settled(proviso, met=True):
        return False
    if isinstance(exclusion.judgement, Settled) and (proviso is None or _settled(proviso)):
        return True
    return None


def _unsettled(judged: tuple[_Judged, ...]) -> list[_Open]:
    """The judgements, in order, that are not settled and still bear on the outcome."""
    unsettled = []
    for index, j in enumerate(judged):
        if j.provision.kind is ProvisionKind.EXCLUSION and _applies(j) is not None:
            continue
        for in_proviso, part in ((False, j), (True, j.proviso)):
            if part is not None and not isinstance(part.judgement, Settled):
                unsettled.append(_Open(part.provision, part.judgement, index, in_proviso))
    return unsettled


def _turning(
    item: _ConditionIncident,
    judged: tuple[_Judged, ...],
    provision: _Open,
    turning: list[_Open],
) -> TurningProvision:
    """A provision that turns on the Cause, with the outcome under each of its readings.

    Under a reading, every provision that turns on the Cause and has a reading
    of the same classification is settled by it, so that one classification
    is applied throughout.
    """
    assert isinstance(provision.judgement, TurnsOnCause)
    readings = []
    for reading in provision.judgement.readings:
        settled = judged
        for other in turning:
            assert isinstance(other.judgement, TurnsOnCause)
            same = next((r for r in other.judgement.readings if r.cause == reading.cause), None)
            if same is not None:
                settled = _with_settled(settled, other, same.met)
        outcome = _from_judgements(item, settled)
        readings.append(
            ReadingOutcome(
                reading.cause,
                outcome.verdict,
                outcome.grounds,
                outcome.clause,
                outcome.reason,
                outcome.delay,
            )
        )
    p = provision.provision
    return TurningProvision(p.kind, p.text, p.clause, tuple(readings))


def _with_settled(judged: tuple[_Judged, ...], where: _Open, met: bool) -> tuple[_Judged, ...]:
    """The judgements with the one at `where` settled as `met`."""
    j = judged[where.index]
    if where.in_proviso:
        assert j.proviso is not None
        j = replace(j, proviso=replace(j.proviso, judgement=Settled(met)))
    else:
        j = replace(j, judgement=Settled(met))
    return (*judged[: where.index], j, *judged[where.index + 1 :])


def _settled(judgement: Judgement | None, met: bool | None = None) -> bool:
    """Whether a judgement is settled, and settled as `met` if that is given."""
    return isinstance(judgement, Settled) and (met is None or judgement.met is met)


def _not_paid(
    item: _ConditionIncident,
    grounds: str,
    clause: ClauseRef,
    delay: Measured | None,
) -> ConditionOutcome:
    return ConditionOutcome(
        item.condition.key, item.incident, Verdict.NOT_PAID, grounds, clause, _shown(delay)
    )


def _undetermined(
    item: _ConditionIncident,
    reason: Reason,
    grounds: str,
    clause: ClauseRef,
    delay: Measured | None,
    turns_on: tuple[TurningProvision, ...] = (),
) -> ConditionOutcome:
    return ConditionOutcome(
        item.condition.key,
        item.incident,
        Verdict.UNDETERMINED,
        grounds,
        clause,
        _shown(delay),
        reason=reason,
        turns_on=turns_on,
    )


def _shown(delay: Measured | None) -> timedelta | None:
    """The delay period an outcome shows: one code measured, the same under every reading."""
    return delay if isinstance(delay, timedelta) else None


def _paid(item: _ConditionIncident, delay: timedelta) -> ConditionOutcome:
    condition = item.condition
    steps = None
    grounds = f"a delay of {_duration(delay)}"
    if condition.benefit_type is BenefitType.PROGRESSIVE and condition.step_hours:
        steps = delay // timedelta(hours=condition.step_hours)
        noun = "step" if steps == 1 else "steps"
        grounds += f": {steps} full {noun} of {condition.step_hours:g} hours"
    elif condition.benefit_type is BenefitType.ONE_OFF:
        grounds += ": one payment"
    return ConditionOutcome(
        condition.key,
        item.incident,
        Verdict.PAID,
        grounds,
        condition.clause,
        delay,
        steps,
        amounts=_plan_amounts(item, steps),
    )


def _plan_amounts(item: _ConditionIncident, steps: int | None) -> tuple[PlanAmount, ...]:
    """What each Plan pays, for the Plans whose Benefit amount is published."""
    paid = []
    benefit_type = item.condition.benefit_type
    for amount in item.table.amounts_of(item.condition):
        if amount.availability is not Availability.PUBLISHED:
            continue
        # Load requires them of a published amount.
        assert amount.plan and amount.benefit_amount is not None and amount.source
        total: int | None = None
        if benefit_type is BenefitType.ONE_OFF:
            total = amount.benefit_amount
        elif benefit_type is BenefitType.PROGRESSIVE and amount.max_per_incident is not None:
            total = (steps or 0) * amount.benefit_amount
        if total is not None and amount.max_per_incident is not None:
            total = min(total, amount.max_per_incident)
        paid.append(PlanAmount(amount.plan, amount.benefit_amount, total, amount.source))
    return tuple(paid)


def _time(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M")


def _duration(delay: timedelta) -> str:
    minutes = delay // timedelta(minutes=1)
    return f"{minutes // 60} h {minutes % 60} min"
