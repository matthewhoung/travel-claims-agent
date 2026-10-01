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
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from travel_claims.clause_store import ClauseStore
from travel_claims.conditions import (
    ALL,
    COVERED_CAUSES,
    Benefit,
    BenefitType,
    ClauseRef,
    Condition,
)
from travel_claims.delay_period import MissingFact, NothingCounts, measure
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


@dataclass(frozen=True)
class TurningProvision:
    """A provision whose judgement turns on the Cause, with the outcome under each reading."""

    kind: ProvisionKind
    text: str
    clause: ClauseRef
    readings: tuple[ReadingOutcome, ...]


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
    # The delay period, when code measured one.
    delay: timedelta | None = None
    # Full steps of a progressive benefit that is paid.
    steps: int | None = None
    # Only for an undetermined outcome.
    reason: Reason | None = None
    # For a Cause-ambiguous outcome, each provision it turns on.
    turns_on: tuple[TurningProvision, ...] = ()


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
        assert condition.delay_period_rule is not None  # Load requires it of a flight delay
        delay = measure(incident, condition.delay_period_rule, policy_ends)
        if isinstance(delay, timedelta):
            item = replace(item, delay=delay)
        missing = _missing_for_window(facts, incident)
        if isinstance(delay, MissingFact) and delay.fact not in missing:
            missing.append(delay.fact)
        threshold = timedelta(hours=condition.threshold_hours or 0)
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
        elif isinstance(delay, timedelta) and delay < threshold:
            item = replace(
                item,
                not_met=(
                    (
                        f"a delay of {_duration(delay)}, under the threshold of "
                        f"{condition.threshold_hours:g} hours"
                    ),
                    condition.clause,
                ),
            )
        checked.append(item)
    return {"items": tuple(checked)}


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
            for exclusion, proviso in _exclusions(item):
                judged_exclusion = _ask(models, exclusion, incident_facts, clauses)
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


def _exclusions(item: _ConditionIncident) -> list[tuple[Provision, Provision | None]]:
    """The exclusions that apply to the Condition, by its key, its Benefit, or all, each
    with its proviso. A proviso concerns the Cause when its exclusion does."""
    names = {item.condition.key, str(item.condition.benefit), ALL}
    return [
        (
            Provision(ProvisionKind.EXCLUSION, e.text, e.clause, e.concerns_cause),
            None
            if e.proviso is None
            else Provision(ProvisionKind.PROVISO, e.proviso, e.clause, e.concerns_cause),
        )
        for e in item.table.exclusions
        if names.intersection(e.applies_to)
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
    if item.missing:
        return _undetermined(
            item,
            Reason.MISSING_FACT,
            f"the Scenario does not state {'; '.join(item.missing)}",
            item.condition.clause,
        )
    if item.not_met is not None:
        return _not_paid(item, *item.not_met)
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
    one the Clause text does not settle; otherwise paid."""
    for j in judged:
        if j.provision.kind is not ProvisionKind.EXCLUSION and _settled(j.judgement, met=False):
            return _not_paid(
                item, f"outside the {j.provision.kind}: {j.provision.text}", j.provision.clause
            )
    for j in judged:
        if j.provision.kind is ProvisionKind.EXCLUSION and _applies(j) is True:
            return _not_paid(item, f"the exclusion applies: {j.provision.text}", j.provision.clause)

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
        )
    turning = [u for u in unsettled if isinstance(u.judgement, TurnsOnCause)]
    if turning:
        return _undetermined(
            item,
            Reason.CAUSE_AMBIGUOUS,
            "turns on how the Cause is classified, under "
            + "; ".join(f"the {u.provision.kind}: {u.provision.text}" for u in turning),
            turning[0].provision.clause,
            tuple(_turning(item, judged, u, turning) for u in turning),
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
        )
    return _paid(item)


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
                reading.cause, outcome.verdict, outcome.grounds, outcome.clause, outcome.reason
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


def _not_paid(item: _ConditionIncident, grounds: str, clause: ClauseRef) -> ConditionOutcome:
    return ConditionOutcome(
        item.condition.key, item.incident, Verdict.NOT_PAID, grounds, clause, item.delay
    )


def _undetermined(
    item: _ConditionIncident,
    reason: Reason,
    grounds: str,
    clause: ClauseRef,
    turns_on: tuple[TurningProvision, ...] = (),
) -> ConditionOutcome:
    return ConditionOutcome(
        item.condition.key,
        item.incident,
        Verdict.UNDETERMINED,
        grounds,
        clause,
        item.delay,
        reason=reason,
        turns_on=turns_on,
    )


def _paid(item: _ConditionIncident) -> ConditionOutcome:
    condition = item.condition
    assert item.delay is not None
    steps = None
    grounds = f"a delay of {_duration(item.delay)}"
    if condition.benefit_type is BenefitType.PROGRESSIVE and condition.step_hours:
        steps = item.delay // timedelta(hours=condition.step_hours)
        noun = "step" if steps == 1 else "steps"
        grounds += f": {steps} full {noun} of {condition.step_hours:g} hours"
    elif condition.benefit_type is BenefitType.ONE_OFF:
        grounds += ": one payment"
    return ConditionOutcome(
        condition.key, item.incident, Verdict.PAID, grounds, condition.clause, item.delay, steps
    )


def _time(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M")


def _duration(delay: timedelta) -> str:
    minutes = delay // timedelta(minutes=1)
    return f"{minutes // 60} h {minutes % 60} min"
