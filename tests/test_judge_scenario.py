"""Judge a Scenario: a Verdict matrix with one cell per confirmed workbook.

Each test imports 享樂遊 in the new wording with scripted extraction,
confirms the workbook, scripts the facts read from the Scenario and the
provision judgements, and judges.
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from travel_claims.app import CannotJudge, import_product, judge_scenario
from travel_claims.conditions import Benefit, ClauseRef
from travel_claims.judging import Cell, ConditionOutcome, Verdict
from travel_claims.local_models import (
    ArrangedBy,
    Incident,
    Judgement,
    Leg,
    Replacement,
    ScenarioFacts,
    Settled,
)
from travel_claims.policies import Wording

from hsiang_le_you import EXTRACTIONS, FIXTURE, confirm, import_draft, review
from scripted_models import ScriptedModels

# Times in the policy are Taiwan time (中原標準時間).
TAIPEI = timezone(timedelta(hours=8))
SCENARIO = "我七月十日從桃園搭長榮班機去東京，班機延誤。"
SCHEDULED = datetime(2026, 7, 10, 8, 0, tzinfo=TAIPEI)
POLICY_PERIOD = (
    datetime(2026, 7, 10, 0, 0, tzinfo=TAIPEI),
    datetime(2026, 7, 14, 23, 59, tzinfo=TAIPEI),
)

# The covered event and its requirements are met, and no exclusion applies.
NOTHING_APPLIES: dict[str, Judgement] = {
    "第三十條": Settled(met=True),
    "第四條 二": Settled(met=False),
    "第三十一條 二": Settled(met=False),
    "第三十一條 五": Settled(met=False),
}


def delayed_by(delay: timedelta) -> ScenarioFacts:
    """The outbound flight from 桃園 departs `delay` late, within the policy period."""
    return ScenarioFacts(
        benefits=(Benefit.FLIGHT_DELAY,),
        incidents=(
            Incident(
                leg=Leg.OUTBOUND,
                airport="桃園國際機場",
                transport="flight",
                scheduled_departure=SCHEDULED,
                actual_departure=SCHEDULED + delay,
            ),
        ),
        cause="機械故障",
        purchased_at=datetime(2026, 7, 1, 12, 0, tzinfo=TAIPEI),
        policy_period=POLICY_PERIOD,
    )


def test_a_delay_of_exactly_four_hours_is_paid_with_one_step(tmp_path: Path) -> None:
    workbook, store = import_draft(tmp_path)
    confirm(workbook)
    models = ScriptedModels(facts=delayed_by(timedelta(hours=4)), judgements=NOTHING_APPLIES)

    matrix = judge_scenario(SCENARIO, [workbook], store=store, models=models)

    assert matrix.facts == delayed_by(timedelta(hours=4))
    assert matrix.cells == (
        Cell(
            product="享樂遊",
            wording=Wording.NEW,
            verdict=Verdict.PAID,
            outcomes=(
                ConditionOutcome(
                    condition="flight delay",
                    incident=1,
                    verdict=Verdict.PAID,
                    grounds="a delay of 4 h 0 min: 1 full step of 4 hours",
                    clause=ClauseRef(30),
                    delay=timedelta(hours=4),
                    steps=1,
                ),
            ),
        ),
    )


def test_a_delay_one_minute_short_of_four_hours_is_not_paid(tmp_path: Path) -> None:
    workbook, store = import_draft(tmp_path)
    confirm(workbook)
    # No judgement is scripted: a Condition whose threshold is not met is not judged further.
    models = ScriptedModels(facts=delayed_by(timedelta(hours=3, minutes=59)))

    matrix = judge_scenario(SCENARIO, [workbook], store=store, models=models)

    assert [cell.verdict for cell in matrix.cells] == [Verdict.NOT_PAID]
    assert matrix.cells[0].outcomes == (
        ConditionOutcome(
            condition="flight delay",
            incident=1,
            verdict=Verdict.NOT_PAID,
            grounds="a delay of 3 h 59 min, under the threshold of 4 hours",
            clause=ClauseRef(30),
            delay=timedelta(hours=3, minutes=59),
        ),
    )


def test_a_progressive_benefit_pays_each_full_step(tmp_path: Path) -> None:
    workbook, store = import_draft(tmp_path)
    confirm(workbook)

    def steps(delay: timedelta) -> int | None:
        models = ScriptedModels(facts=delayed_by(delay), judgements=NOTHING_APPLIES)
        matrix = judge_scenario(SCENARIO, [workbook], store=store, models=models)
        return matrix.cells[0].outcomes[0].steps

    assert steps(timedelta(hours=7, minutes=59)) == 1
    assert steps(timedelta(hours=8)) == 2


def test_a_one_off_benefit_pays_once_however_long_the_delay(tmp_path: Path) -> None:
    workbook, store = import_draft(tmp_path)
    review(workbook, {"Conditions!J5": "one-off fixed amount", "Conditions!K5": None})
    confirm(workbook)
    models = ScriptedModels(facts=delayed_by(timedelta(hours=8)), judgements=NOTHING_APPLIES)

    matrix = judge_scenario(SCENARIO, [workbook], store=store, models=models)

    assert matrix.cells[0].outcomes == (
        ConditionOutcome(
            condition="flight delay",
            incident=1,
            verdict=Verdict.PAID,
            grounds="a delay of 8 h 0 min: one payment",
            clause=ClauseRef(30),
            delay=timedelta(hours=8),
        ),
    )


def test_the_delay_runs_to_the_booked_flights_departure_not_a_later_flight_taken(
    tmp_path: Path,
) -> None:
    workbook, store = import_draft(tmp_path)
    confirm(workbook)
    booked = delayed_by(timedelta(hours=2, minutes=30))
    next_day = Replacement(
        departure=SCHEDULED + timedelta(days=1),
        arranged_by=ArrangedBy.INSURED,
        taken=True,
        arranged_at=SCHEDULED + timedelta(hours=1),
        destination="東京",
        returns_to_taiwan=False,
    )
    facts = replace(booked, incidents=(replace(booked.incidents[0], replacements=(next_day,)),))

    matrix = judge_scenario(SCENARIO, [workbook], store=store, models=ScriptedModels(facts=facts))

    assert matrix.cells[0].outcomes == (
        ConditionOutcome(
            condition="flight delay",
            incident=1,
            verdict=Verdict.NOT_PAID,
            grounds="a delay of 2 h 30 min, under the threshold of 4 hours",
            clause=ClauseRef(30),
            delay=timedelta(hours=2, minutes=30),
        ),
    )


def cancelled_return_flight(replacement_to: str, *, returns_to_taiwan: bool) -> ScenarioFacts:
    """The return flight from 成田 is cancelled at the end of the policy period.

    The insured arranges a replacement the next morning, after the policy expired.
    """
    scheduled = datetime(2026, 7, 14, 20, 0, tzinfo=TAIPEI)
    return ScenarioFacts(
        benefits=(Benefit.FLIGHT_DELAY,),
        incidents=(
            Incident(
                leg=Leg.RETURN,
                airport="成田國際機場",
                transport="flight",
                scheduled_departure=scheduled,
                cancelled=True,
                replacements=(
                    Replacement(
                        departure=datetime(2026, 7, 15, 14, 0, tzinfo=TAIPEI),
                        arranged_by=ArrangedBy.INSURED,
                        taken=True,
                        arranged_at=datetime(2026, 7, 15, 9, 0, tzinfo=TAIPEI),
                        destination=replacement_to,
                        returns_to_taiwan=returns_to_taiwan,
                    ),
                ),
            ),
        ),
        cause="颱風",
        purchased_at=datetime(2026, 7, 1, 12, 0, tzinfo=TAIPEI),
        policy_period=POLICY_PERIOD,
    )


def test_a_self_arranged_replacement_home_counts_though_arranged_after_the_policy_expired(
    tmp_path: Path,
) -> None:
    workbook, store = import_draft(tmp_path)
    confirm(workbook)
    facts = cancelled_return_flight("桃園", returns_to_taiwan=True)
    models = ScriptedModels(facts=facts, judgements=NOTHING_APPLIES)

    matrix = judge_scenario(SCENARIO, [workbook], store=store, models=models)

    assert matrix.cells[0].outcomes == (
        ConditionOutcome(
            condition="flight delay",
            incident=1,
            verdict=Verdict.PAID,
            grounds="a delay of 18 h 0 min: 4 full steps of 4 hours",
            clause=ClauseRef(30),
            delay=timedelta(hours=18),
            steps=4,
        ),
    )


def test_a_self_arranged_replacement_elsewhere_after_the_policy_expired_does_not_count(
    tmp_path: Path,
) -> None:
    workbook, store = import_draft(tmp_path)
    confirm(workbook)
    facts = cancelled_return_flight("首爾", returns_to_taiwan=False)

    matrix = judge_scenario(SCENARIO, [workbook], store=store, models=ScriptedModels(facts=facts))

    assert matrix.cells[0].verdict is Verdict.NOT_PAID
    assert matrix.cells[0].outcomes == (
        ConditionOutcome(
            condition="flight delay",
            incident=1,
            verdict=Verdict.NOT_PAID,
            grounds=(
                "no replacement flight counts toward the delay period: the one the insured "
                "arranged after the policy period ended does not return to Taiwan"
            ),
            clause=ClauseRef(30),
        ),
    )


def test_a_delay_stated_without_times_is_used_as_stated(tmp_path: Path) -> None:
    workbook, store = import_draft(tmp_path)
    confirm(workbook)
    timed = delayed_by(timedelta(0))
    stated = replace(timed.incidents[0], actual_departure=None, stated_delay=timedelta(hours=5))
    models = ScriptedModels(facts=replace(timed, incidents=(stated,)), judgements=NOTHING_APPLIES)

    matrix = judge_scenario(SCENARIO, [workbook], store=store, models=models)

    assert matrix.cells[0].outcomes[0].verdict is Verdict.PAID
    assert matrix.cells[0].outcomes[0].delay == timedelta(hours=5)


def test_a_booked_flight_scheduled_before_the_policy_period_is_not_paid(tmp_path: Path) -> None:
    workbook, store = import_draft(tmp_path)
    confirm(workbook)
    facts = replace(
        delayed_by(timedelta(hours=6)),
        policy_period=(
            datetime(2026, 7, 10, 9, 0, tzinfo=TAIPEI),
            datetime(2026, 7, 14, 23, 59, tzinfo=TAIPEI),
        ),
    )

    matrix = judge_scenario(SCENARIO, [workbook], store=store, models=ScriptedModels(facts=facts))

    assert matrix.cells[0].outcomes == (
        ConditionOutcome(
            condition="flight delay",
            incident=1,
            verdict=Verdict.NOT_PAID,
            grounds=(
                "the booked flight's scheduled departure, 2026-07-10 08:00, is outside "
                "the policy period, 2026-07-10 09:00 – 2026-07-14 23:59"
            ),
            clause=ClauseRef(30),
            delay=timedelta(hours=6),
        ),
    )


def test_a_coverage_requirement_the_facts_fall_outside_is_not_paid(tmp_path: Path) -> None:
    workbook, store = import_draft(tmp_path)
    review(workbook, {"Conditions!F5": "as a passenger"})  # judged as its own provision
    confirm(workbook)
    models = ScriptedModels(
        facts=delayed_by(timedelta(hours=5)),
        judgements={"第三十條": Settled(met=True), "as a passenger": Settled(met=False)},
    )

    matrix = judge_scenario(SCENARIO, [workbook], store=store, models=models)

    assert matrix.cells[0].outcomes[0].verdict is Verdict.NOT_PAID
    assert matrix.cells[0].outcomes[0].grounds == "outside the coverage requirement: as a passenger"
    assert matrix.cells[0].outcomes[0].clause == ClauseRef(30)


def test_an_exclusion_that_applies_is_not_paid_citing_it(tmp_path: Path) -> None:
    workbook, store = import_draft(tmp_path)
    confirm(workbook)
    models = ScriptedModels(
        facts=delayed_by(timedelta(hours=5)),
        judgements=NOTHING_APPLIES | {"第三十一條 二": Settled(met=True)},
    )

    matrix = judge_scenario(SCENARIO, [workbook], store=store, models=models)

    assert matrix.cells[0].outcomes == (
        ConditionOutcome(
            condition="flight delay",
            incident=1,
            verdict=Verdict.NOT_PAID,
            grounds=(
                "the exclusion applies: "
                "要保人向本公司申請訂立保險契約時，中華民國政府氣象機構已發布海上颱風警報。"
            ),
            clause=ClauseRef(31, "二"),
            delay=timedelta(hours=5),
        ),
    )


def test_each_confirmed_workbook_gets_its_own_cell_in_the_order_given(tmp_path: Path) -> None:
    workbook, store = import_draft(tmp_path)
    confirm(workbook)
    other = tmp_path / "享暢行.new.xlsx"
    import_product(
        FIXTURE,
        product="享暢行",
        wording=Wording.NEW,
        workbook=other,
        store=store,
        models=ScriptedModels(extractions=EXTRACTIONS),
    )
    review(other, {"Conditions!H5": 6})  # Threshold (hours)
    confirm(other)
    models = ScriptedModels(facts=delayed_by(timedelta(hours=5)), judgements=NOTHING_APPLIES)

    matrix = judge_scenario(SCENARIO, [other, workbook], store=store, models=models)

    assert [(cell.product, cell.wording, cell.verdict) for cell in matrix.cells] == [
        ("享暢行", Wording.NEW, Verdict.NOT_PAID),
        ("享樂遊", Wording.NEW, Verdict.PAID),
    ]


def test_nothing_is_judged_while_any_workbook_has_a_problem(tmp_path: Path) -> None:
    workbook, store = import_draft(tmp_path)
    confirm(workbook)
    unconfirmed = tmp_path / "享暢行.new.xlsx"
    import_product(
        FIXTURE,
        product="享暢行",
        wording=Wording.NEW,
        workbook=unconfirmed,
        store=store,
        models=ScriptedModels(extractions=EXTRACTIONS),
    )
    # Facts are scripted, but nothing may be asked of the models.
    models = ScriptedModels(facts=delayed_by(timedelta(hours=5)))

    with pytest.raises(CannotJudge) as refused:
        judge_scenario(SCENARIO, [workbook, unconfirmed], store=store, models=models)

    assert {
        path: [str(problem) for problem in problems]
        for path, problems in refused.value.problems.items()
    } == {
        unconfirmed: [
            "Conditions!B1: Confirmed by is missing",
            "Conditions!B2: Confirmed on is missing",
        ]
    }
    assert models.scenarios == []
