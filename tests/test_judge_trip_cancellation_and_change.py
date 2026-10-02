"""Judge trip cancellation and trip change, and list the benefits that are not judged.

Each test imports 享樂遊 with trip cancellation and trip change scripted
(hsiang_le_you.TRIP_EXTRACTIONS), confirms the workbook, scripts the facts read
from the Scenario and the provision judgements, and judges. Each covered cause
is a Condition of its own, so a Scenario is judged against every one of them.
"""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from travel_claims.app import judge_scenario
from travel_claims.conditions import Benefit, ClauseRef, CostCategory
from travel_claims.judging import (
    Cell,
    ConditionOutcome,
    NamedCost,
    PlanAmount,
    ReadingOutcome,
    Reason,
    TurningProvision,
    Verdict,
)
from travel_claims.local_models import (
    Cost,
    Incident,
    Judgement,
    ProvisionKind,
    Reading,
    ScenarioFacts,
    Settled,
    TurnsOnCause,
)
from travel_claims.policies import Wording

from hsiang_le_you import (
    CANCELLED_BY_STRIKE,
    CHANGED_BY_RELATIVES_DEATH,
    CHANGED_BY_STRIKE,
    NOTHING_APPLIES,
    OLD_TRIP_EXTRACTIONS,
    TRIP_EXTRACTIONS,
    cathay_century_trip_change,
    confirm,
    delayed_by,
    enter_amounts,
    import_draft,
)
from scripted_models import ScriptedModels

SCENARIO = "出發前十天，我的祖母過世，只好取消整個旅程。"
CATHAY_SOURCE = "https://www.cathay-ins.com.tw/cathayins/personal/travel/oversea/"

# The relative's death is within its covered cause and the strike is not; no
# exclusion applies.
RELATIVES_DEATH: dict[str, Judgement] = {
    "第二十七條 一": Settled(met=True),
    "第二十七條 三": Settled(met=False),
    "第二十八條 三": Settled(met=False),
    "第二十八條 四": Settled(met=False),
    "第四條 二": Settled(met=False),
}


def trip_event(
    benefit: Benefit = Benefit.TRIP_CANCELLATION,
    *,
    event: str = "祖母過世",
    event_day: int | None = None,
    during_trip: bool | None = None,
    costs: tuple[Cost, ...] = (),
) -> ScenarioFacts:
    """A Scenario touching one Benefit, with one incident: what made the insured
    cancel or change the trip, and the costs it names."""
    incident = Incident(
        leg=None,
        airport=None,
        transport=None,
        event=event,
        event_day=event_day,
        during_trip=during_trip,
        costs=costs,
    )
    return ScenarioFacts(benefits=(benefit,), incidents=(incident,), cause=event)


def test_a_relatives_death_ten_days_before_departure_is_outside_the_old_window_inside_the_new(
    tmp_path: Path,
) -> None:
    old, store = import_draft(
        tmp_path, ScriptedModels(extractions=OLD_TRIP_EXTRACTIONS), Wording.OLD
    )
    new, _ = import_draft(tmp_path, ScriptedModels(extractions=TRIP_EXTRACTIONS))
    for workbook in (old, new):
        confirm(workbook)
    models = ScriptedModels(facts=trip_event(event_day=-10), judgements=RELATIVES_DEATH)

    matrix = judge_scenario(SCENARIO, [old, new], store=store, models=models)

    assert matrix.cells == (
        Cell(
            product="享樂遊",
            wording=Wording.OLD,
            verdict=Verdict.NOT_PAID,
            outcomes=(
                ConditionOutcome(
                    condition="trip cancellation / relative's death",
                    incident=1,
                    verdict=Verdict.NOT_PAID,
                    grounds=(
                        "the event, 10 days before departure, is outside the window from "
                        "7 days before departure to the start of the overseas travel period"
                    ),
                    clause=ClauseRef(27, "一"),
                ),
            ),
        ),
        Cell(
            product="享樂遊",
            wording=Wording.NEW,
            verdict=Verdict.PAID,
            outcomes=(
                ConditionOutcome(
                    condition="trip cancellation / relative's death",
                    incident=1,
                    verdict=Verdict.PAID,
                    grounds="reimburses tour fee, transport, lodging, tickets",
                    clause=ClauseRef(27, "一"),
                    eligible_costs=("tour fee", "transport", "lodging", "tickets"),
                ),
                ConditionOutcome(
                    condition="trip cancellation / strike",
                    incident=1,
                    verdict=Verdict.NOT_PAID,
                    grounds=f"outside the covered event: {CANCELLED_BY_STRIKE.covered_event}",
                    clause=ClauseRef(27, "三"),
                ),
            ),
        ),
    )


def test_an_incident_after_departure_claimed_as_trip_cancellation_is_not_paid(
    tmp_path: Path,
) -> None:
    workbook, store = import_draft(tmp_path, ScriptedModels(extractions=TRIP_EXTRACTIONS))
    confirm(workbook)
    # Code finds it outside the window, so nothing is asked of the models.
    models = ScriptedModels(facts=trip_event(event_day=3, during_trip=True))

    matrix = judge_scenario(SCENARIO, [workbook], store=store, models=models)

    grounds = (
        "the event happened during the overseas trip, after the window that closes "
        "when the overseas travel period begins"
    )
    assert matrix.cells[0].verdict is Verdict.NOT_PAID
    assert [(o.condition, o.verdict, o.grounds, o.clause) for o in matrix.cells[0].outcomes] == [
        ("trip cancellation / relative's death", Verdict.NOT_PAID, grounds, ClauseRef(27, "一")),
        ("trip cancellation / strike", Verdict.NOT_PAID, grounds, ClauseRef(27, "三")),
    ]
    assert models.judged == []


def test_a_trip_stated_outside_the_policy_period_is_not_paid(tmp_path: Path) -> None:
    workbook, store = import_draft(tmp_path, ScriptedModels(extractions=TRIP_EXTRACTIONS))
    confirm(workbook)

    for benefit in (Benefit.TRIP_CANCELLATION, Benefit.TRIP_CHANGE):
        facts = replace(
            trip_event(benefit, event_day=-1, during_trip=False), within_policy_period=False
        )
        matrix = judge_scenario("……", [workbook], store=store, models=ScriptedModels(facts=facts))
        assert {o.grounds for o in matrix.cells[0].outcomes} == {
            "the Scenario states the trip is outside the policy period"
        }


def test_a_trip_cancellation_without_the_day_of_the_event_lacks_a_fact(tmp_path: Path) -> None:
    workbook, store = import_draft(tmp_path, ScriptedModels(extractions=TRIP_EXTRACTIONS))
    confirm(workbook)
    models = ScriptedModels(facts=trip_event())

    matrix = judge_scenario(SCENARIO, [workbook], store=store, models=models)

    assert (matrix.cells[0].verdict, matrix.cells[0].reason) == (
        Verdict.UNDETERMINED,
        Reason.MISSING_FACT,
    )
    assert matrix.cells[0].outcomes[0].grounds == (
        "the Scenario does not state the day of the event, counted from departure"
    )


STRIKE_AND_ON_THE_TRIP: dict[str, Judgement] = {
    "第三十三條 一": Settled(met=True),
    "第三十三條 三": Settled(met=False),
    "第三十四條 二": Settled(met=False),
    "第三十四條 六": Settled(met=False),
    "第四條 二": Settled(met=False),
}


def test_a_trip_change_names_each_cost_eligible_or_not_and_the_limit_per_plan(
    tmp_path: Path,
) -> None:
    workbook, store = import_draft(tmp_path, ScriptedModels(extractions=TRIP_EXTRACTIONS))
    confirm(workbook)
    enter_amounts(workbook, cathay_century_trip_change("trip change / strike"))
    facts = trip_event(
        benefit=Benefit.TRIP_CHANGE,
        event="當地航空公司地勤罷工，回程班機取消",
        during_trip=True,
        costs=(
            Cost("多住一晚的飯店費用", CostCategory.LODGING),
            Cost("多出來的餐費", CostCategory.MEALS),
        ),
    )
    models = ScriptedModels(facts=facts, judgements=STRIKE_AND_ON_THE_TRIP)

    matrix = judge_scenario("……", [workbook], store=store, models=models)

    assert matrix.cells[0].verdict is Verdict.PAID
    assert matrix.cells[0].outcomes[0] == ConditionOutcome(
        condition="trip change / strike",
        incident=1,
        verdict=Verdict.PAID,
        grounds="reimburses transport, lodging",
        clause=ClauseRef(33, "一"),
        amounts=(
            PlanAmount("安心型(T5)", 60000, None, CATHAY_SOURCE),
            PlanAmount("海外豪華型(U3)", 120000, None, CATHAY_SOURCE),
        ),
        eligible_costs=("transport", "lodging"),
        costs=(
            NamedCost("多住一晚的飯店費用", CostCategory.LODGING, True, ClauseRef(33, "一")),
            NamedCost("多出來的餐費", CostCategory.MEALS, False, ClauseRef(33, "一")),
        ),
    )
    # Costs are not a required fact: the same Scenario naming none is still paid.
    no_costs = replace(facts, incidents=(replace(facts.incidents[0], costs=()),))
    models = ScriptedModels(facts=no_costs, judgements=STRIKE_AND_ON_THE_TRIP)
    matrix = judge_scenario("……", [workbook], store=store, models=models)
    assert (matrix.cells[0].verdict, matrix.cells[0].outcomes[0].costs) == (Verdict.PAID, ())


def test_a_trip_change_before_the_trip_began_is_outside_the_overseas_travel_period(
    tmp_path: Path,
) -> None:
    workbook, store = import_draft(tmp_path, ScriptedModels(extractions=TRIP_EXTRACTIONS))
    confirm(workbook)

    def grounds(event_day: int | None = None, during_trip: bool | None = None) -> list[str]:
        facts = trip_event(Benefit.TRIP_CHANGE, event_day=event_day, during_trip=during_trip)
        matrix = judge_scenario("……", [workbook], store=store, models=ScriptedModels(facts=facts))
        return [o.grounds for o in matrix.cells[0].outcomes]

    before = "the event happened before the overseas trip began, outside the overseas travel period"
    assert grounds(event_day=-2) == [before, before]
    assert grounds(during_trip=False) == [before, before]
    missing = "the Scenario does not state whether the event happened during the overseas trip"
    assert grounds() == [missing, missing]


def test_a_covered_cause_can_turn_on_how_the_cause_is_classified(tmp_path: Path) -> None:
    workbook, store = import_draft(tmp_path, ScriptedModels(extractions=TRIP_EXTRACTIONS))
    confirm(workbook)
    facts = trip_event(
        benefit=Benefit.TRIP_CHANGE, event="當地機場地勤集體請病假，班機取消", during_trip=True
    )
    readings = TurnsOnCause((Reading("罷工", met=True), Reading("非罷工", met=False)))
    models = ScriptedModels(
        facts=facts,
        judgements=STRIKE_AND_ON_THE_TRIP | {"strike of the booked transport": readings},
    )

    matrix = judge_scenario("……", [workbook], store=store, models=models)

    strike = "strike of the booked transport"
    assert (matrix.cells[0].verdict, matrix.cells[0].reason) == (
        Verdict.UNDETERMINED,
        Reason.CAUSE_AMBIGUOUS,
    )
    assert matrix.cells[0].outcomes[0] == ConditionOutcome(
        condition="trip change / strike",
        incident=1,
        verdict=Verdict.UNDETERMINED,
        grounds=f"turns on how the Cause is classified, under the coverage requirement: {strike}",
        clause=ClauseRef(33, "一"),
        reason=Reason.CAUSE_AMBIGUOUS,
        turns_on=(
            TurningProvision(
                ProvisionKind.COVERAGE_REQUIREMENT,
                strike,
                ClauseRef(33, "一"),
                (
                    ReadingOutcome(
                        "罷工", Verdict.PAID, "reimburses transport, lodging", ClauseRef(33, "一")
                    ),
                    ReadingOutcome(
                        "非罷工",
                        Verdict.NOT_PAID,
                        f"outside the coverage requirement: {strike}",
                        ClauseRef(33, "一"),
                    ),
                ),
            ),
        ),
    )
    # A covered cause is judged as concerning the Cause; the covered event is not.
    concerns = {r.provision.text: r.provision.concerns_cause for r in models.judged}
    assert concerns[strike] is True
    assert concerns[CHANGED_BY_STRIKE.covered_event] is False
    assert CHANGED_BY_RELATIVES_DEATH.covered_event in concerns


# Benefits that are not judged ------------------------------------------------------


def test_a_benefit_not_judged_is_listed_as_not_supported_and_left_out_of_the_verdict(
    tmp_path: Path,
) -> None:
    workbook, store = import_draft(tmp_path)
    confirm(workbook)
    facts = replace(
        delayed_by(timedelta(hours=5)), benefits=(Benefit.FLIGHT_DELAY, Benefit.BAGGAGE_DELAY)
    )
    models = ScriptedModels(facts=facts, judgements=NOTHING_APPLIES)

    matrix = judge_scenario(
        "班機延誤五小時，行李也延誤了。", [workbook], store=store, models=models
    )

    assert matrix.not_supported == (Benefit.BAGGAGE_DELAY,)
    [cell] = matrix.cells
    assert (cell.verdict, cell.not_supported) == (Verdict.PAID, (Benefit.BAGGAGE_DELAY,))
    assert [o.condition for o in cell.outcomes] == ["flight delay"]


def test_a_scenario_with_no_supported_benefit_returns_only_that_notice(tmp_path: Path) -> None:
    workbook, store = import_draft(tmp_path)
    confirm(workbook)
    facts = replace(
        delayed_by(timedelta(hours=8)), benefits=(Benefit.BAGGAGE_LOSS, Benefit.BAGGAGE_DELAY)
    )
    models = ScriptedModels(facts=facts)

    matrix = judge_scenario("行李遺失。", [workbook], store=store, models=models)

    assert (matrix.cells, matrix.not_supported) == (
        (),
        (Benefit.BAGGAGE_LOSS, Benefit.BAGGAGE_DELAY),
    )
    assert models.judged == []
