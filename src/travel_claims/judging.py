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
from travel_claims.conditions import ALL, Benefit, BenefitType, ClauseRef, Condition
from travel_claims.delay_period import NothingCounts, measure
from travel_claims.loading import ConditionTable
from travel_claims.local_models import (
    Incident,
    JudgementRequest,
    LocalModels,
    Provision,
    ProvisionKind,
    ScenarioFacts,
    Settled,
)
from travel_claims.policies import Wording


class Verdict(StrEnum):
    PAID = "paid"
    NOT_PAID = "not paid"


@dataclass(frozen=True)
class ConditionOutcome:
    """The outcome of one Condition for one incident of the Scenario."""

    condition: str
    # The incident's number among the facts' incidents, from 1.
    incident: int
    verdict: Verdict
    # For a paid outcome, what is paid; for a not-paid one, the threshold,
    # window, requirement or exclusion that decides it.
    grounds: str
    clause: ClauseRef
    # The delay period, when code measured one.
    delay: timedelta | None = None
    # Full steps of a progressive benefit that is paid.
    steps: int | None = None


@dataclass(frozen=True)
class Cell:
    """One Product in one Wording version."""

    product: str
    wording: Wording
    verdict: Verdict
    outcomes: tuple[ConditionOutcome, ...]


@dataclass(frozen=True)
class VerdictMatrix:
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
    # A threshold or window that code found not met, and its Clause.
    not_met: tuple[str, ClauseRef] | None = None
    judgements: tuple[tuple[Provision, Settled], ...] = ()


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
        threshold = timedelta(hours=condition.threshold_hours or 0)
        window = _outside_policy_period(facts, incident)
        if window is not None:
            item = replace(
                item,
                delay=None if isinstance(delay, NothingCounts) else delay,
                not_met=(window, condition.clause),
            )
        elif isinstance(delay, NothingCounts):
            item = replace(
                item,
                not_met=(
                    f"no replacement flight counts toward the delay period: {delay.why}",
                    condition.clause,
                ),
            )
        elif delay < threshold:
            item = replace(
                item,
                delay=delay,
                not_met=(
                    (
                        f"a delay of {_duration(delay)}, under the threshold of "
                        f"{condition.threshold_hours:g} hours"
                    ),
                    condition.clause,
                ),
            )
        else:
            item = replace(item, delay=delay)
        checked.append(item)
    return {"items": tuple(checked)}


def _outside_policy_period(facts: ScenarioFacts, incident: Incident) -> str | None:
    """Why the booked flight is not covered by the policy period; None if it is."""
    if facts.policy_period is None or incident.scheduled_departure is None:
        raise NotImplementedError("a missing fact is not reported yet")
    starts, ends = facts.policy_period
    if starts <= incident.scheduled_departure <= ends:
        return None
    return (
        f"the booked flight's scheduled departure, {_time(incident.scheduled_departure)}, "
        f"is outside the policy period, {_time(starts)} – {_time(ends)}"
    )


def _judge(state: _State, store: ClauseStore, models: LocalModels) -> _State:
    """The local models judge each provision of a Condition that passed the code checks.

    The covered event and the coverage requirements come first; the
    exclusions are judged only if the facts fall within them.
    """
    facts = state["facts"]
    judged = []
    for item in state["items"]:
        if item.not_met is not None:
            judged.append(item)
            continue
        clauses = {c.number: c for c in store.clauses(item.table.product, item.table.wording)}
        incident_facts = replace(facts, incidents=(facts.incidents[item.incident - 1],))
        judgements: list[tuple[Provision, Settled]] = []
        for provisions in (_coverage(item.condition), _exclusions(item)):
            for provision in provisions:
                judgement = models.judge(
                    JudgementRequest(provision, incident_facts, (clauses[provision.clause.number],))
                )
                if not isinstance(judgement, Settled):
                    raise NotImplementedError(
                        f"a judgement that is not settled ({type(judgement).__name__}) "
                        "is not handled yet"
                    )
                judgements.append((provision, judgement))
            if any(not j.met for _, j in judgements):
                break
        judged.append(replace(item, judgements=tuple(judgements)))
    return {"items": tuple(judged)}


def _coverage(condition: Condition) -> list[Provision]:
    event = Provision(ProvisionKind.COVERED_EVENT, condition.covered_event, condition.clause, False)
    requirements = [
        Provision(ProvisionKind.COVERAGE_REQUIREMENT, requirement, condition.clause, False)
        for requirement in condition.coverage_requirements
    ]
    return [event, *requirements]


def _exclusions(item: _ConditionIncident) -> list[Provision]:
    """The exclusions that apply to the Condition: by its key, its Benefit, or all."""
    names = {item.condition.key, str(item.condition.benefit), ALL}
    return [
        Provision(ProvisionKind.EXCLUSION, e.text, e.clause, e.concerns_cause)
        for e in item.table.exclusions
        if names.intersection(e.applies_to)
    ]


def _outcome(state: _State) -> _State:
    """Code derives each Condition's outcome, and each cell's Verdict from them."""
    cells = []
    for table in state["tables"]:
        mine = tuple(_condition_outcome(c) for c in state["items"] if c.table is table)
        paid = any(o.verdict is Verdict.PAID for o in mine)
        cells.append(
            Cell(table.product, table.wording, Verdict.PAID if paid else Verdict.NOT_PAID, mine)
        )
    return {"matrix": VerdictMatrix(state["facts"], tuple(cells))}


def _condition_outcome(item: _ConditionIncident) -> ConditionOutcome:
    """The outcome order: a threshold, window, covered event or requirement not met; then
    an exclusion that applies; otherwise paid."""
    condition = item.condition

    def not_paid(grounds: str, clause: ClauseRef) -> ConditionOutcome:
        return ConditionOutcome(
            condition.key, item.incident, Verdict.NOT_PAID, grounds, clause, item.delay
        )

    if item.not_met is not None:
        return not_paid(*item.not_met)
    for provision, judgement in item.judgements:
        if provision.kind is not ProvisionKind.EXCLUSION and not judgement.met:
            return not_paid(f"outside the {provision.kind}: {provision.text}", provision.clause)
    for provision, judgement in item.judgements:
        if provision.kind is ProvisionKind.EXCLUSION and judgement.met:
            return not_paid(f"the exclusion applies: {provision.text}", provision.clause)
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
