"""Export a Verdict matrix to Excel, with the facts read and the per-Condition breakdown."""

from datetime import timedelta
from pathlib import Path

import openpyxl
import pytest

from travel_claims.app import export_verdict_matrix, judge_scenario
from travel_claims.conditions import Benefit, CostCategory
from travel_claims.local_models import Cost, Incident, ScenarioFacts, Settled

from hsiang_le_you import (
    FORCE_MAJEURE,
    NOTHING_APPLIES,
    PROVISO,
    ROAD_CLOSURE,
    TRIP_EXTRACTIONS,
    cathay_century_flight_delay,
    cathay_century_trip_change,
    confirm,
    delayed_by,
    enter_amounts,
    import_draft,
    road_closure,
)
from scripted_models import ScriptedModels


def rows(path: Path, sheet: str) -> list[tuple[object, ...]]:
    book = openpyxl.load_workbook(path)
    return [tuple(row) for row in book[sheet].iter_rows(values_only=True)]


def test_the_verdict_matrix_exports_with_its_facts_and_breakdown(tmp_path: Path) -> None:
    workbook, store = import_draft(tmp_path)
    confirm(workbook)
    models = ScriptedModels(
        facts=road_closure(),
        judgements=NOTHING_APPLIES | {"第三十一條 五": Settled(met=True), PROVISO: FORCE_MAJEURE},
    )
    matrix = judge_scenario(ROAD_CLOSURE, [workbook], store=store, models=models)
    exported = tmp_path / "verdicts.xlsx"

    export_verdict_matrix(matrix, exported)

    assert rows(exported, "Verdict matrix") == [
        ("Scenario", ROAD_CLOSURE, None, None),
        (None, None, None, None),
        ("Product", "Wording version", "Verdict", "Reason"),
        ("享樂遊", "new", "undetermined", "Cause ambiguous"),
    ]
    assert rows(exported, "Facts") == [
        ("Fact", "As read from the Scenario"),
        ("Benefits", "flight delay"),
        ("Incident 1", "outbound flight"),
        (None, "scheduled departure 2026-07-10 10:00"),
        (None, "replacement departing 2026-07-10 15:00, arranged by the airline, not taken"),
        (None, "replacement departing 2026-07-10 20:00, arranged by the airline, taken"),
        ("Cause", "機場聯外道路封閉"),
        ("Policy bought", "not stated"),
        ("Policy period", "dates not stated; the trip is within it"),
        ("In force at purchase", "none stated"),
    ]
    first_replacement = "被保險人未搭乘航空業者所提供之第一班替代交通工具。"
    assert rows(exported, "Breakdown") == [
        (
            "Product",
            "Wording version",
            "Condition key",
            "Incident",
            "Turns on",
            "Reading",
            "Verdict",
            "Reason",
            "Grounds",
            "Clause",
            "Delay period",
            "Steps",
            "Eligible costs",
            "Costs named",
        ),
        (
            "享樂遊",
            "new",
            "flight delay",
            1,
            None,
            None,
            "undetermined",
            "Cause ambiguous",
            f"turns on how the Cause is classified, under the proviso: {PROVISO}",
            "第三十一條 五",
            timedelta(hours=5),
            None,
            None,
            None,
        ),
        (
            "享樂遊",
            "new",
            "flight delay",
            1,
            "the proviso of 第三十一條 五",
            "不可抗力",
            "paid",
            None,
            "a delay of 5 h 0 min: 1 full step of 4 hours",
            "第三十條",
            timedelta(hours=5),
            None,
            None,
            None,
        ),
        (
            "享樂遊",
            "new",
            "flight delay",
            1,
            "the proviso of 第三十一條 五",
            "非不可抗力",
            "not paid",
            None,
            f"the exclusion applies: {first_replacement}",
            "第三十一條 五",
            timedelta(hours=5),
            None,
            None,
            None,
        ),
    ]


def test_the_export_carries_the_amount_per_plan_of_each_paid_outcome(tmp_path: Path) -> None:
    workbook, store = import_draft(tmp_path)
    confirm(workbook)
    enter_amounts(workbook, cathay_century_flight_delay())
    models = ScriptedModels(facts=delayed_by(timedelta(hours=12)), judgements=NOTHING_APPLIES)
    matrix = judge_scenario("班機延誤十二小時。", [workbook], store=store, models=models)
    exported = tmp_path / "verdicts.xlsx"

    export_verdict_matrix(matrix, exported)

    source = "https://www.cathay-ins.com.tw/cathayins/personal/travel/oversea/"
    assert rows(exported, "Amounts") == [
        (
            "Product",
            "Wording version",
            "Condition key",
            "Incident",
            "Plan",
            "Benefit amount",
            "Steps",
            "Total",
            "Source",
        ),
        ("享樂遊", "new", "flight delay", 1, "安心型(T5)", 6000, 3, 12000, source),
        ("享樂遊", "new", "flight delay", 1, "海外豪華型(U3)", 6000, 3, 12000, source),
    ]


def test_an_export_never_overwrites_a_file(tmp_path: Path) -> None:
    workbook, store = import_draft(tmp_path)
    confirm(workbook)
    matrix = judge_scenario(
        ROAD_CLOSURE,
        [workbook],
        store=store,
        models=ScriptedModels(facts=road_closure(), judgements=NOTHING_APPLIES),
    )

    with pytest.raises(FileExistsError):
        export_verdict_matrix(matrix, path=workbook)

    assert openpyxl.load_workbook(workbook).sheetnames[0] == "Conditions"


def test_the_export_carries_named_costs_and_the_benefits_not_supported(tmp_path: Path) -> None:
    workbook, store = import_draft(tmp_path, ScriptedModels(extractions=TRIP_EXTRACTIONS))
    confirm(workbook)
    enter_amounts(workbook, cathay_century_trip_change("trip change / strike"))
    facts = ScenarioFacts(
        benefits=(Benefit.TRIP_CHANGE, Benefit.BAGGAGE_DELAY),
        incidents=(
            Incident(
                leg=None,
                airport=None,
                transport=None,
                event="當地航空公司地勤罷工",
                event_day=3,
                costs=(
                    Cost("多住一晚的飯店費用", CostCategory.LODGING),
                    Cost("多出來的餐費", CostCategory.MEALS),
                ),
            ),
        ),
        cause="罷工",
    )
    judgements = {
        "第三十三條 一": Settled(met=True),
        "第三十三條 三": Settled(met=False),
        "第三十四條 二": Settled(met=False),
        "第三十四條 六": Settled(met=False),
        "第四條 二": Settled(met=False),
    }
    matrix = judge_scenario(
        "旅途中遇到罷工……",
        [workbook],
        store=store,
        models=ScriptedModels(facts=facts, judgements=judgements),
    )
    exported = tmp_path / "verdicts.xlsx"

    export_verdict_matrix(matrix, exported)

    assert rows(exported, "Verdict matrix") == [
        ("Scenario", "旅途中遇到罷工……", None, None),
        ("Not supported", "baggage delay", None, None),
        (None, None, None, None),
        ("Product", "Wording version", "Verdict", "Reason"),
        ("享樂遊", "new", "paid", None),
    ]
    assert rows(exported, "Facts")[1:4] == [
        ("Benefits", "trip change, baggage delay"),
        ("Incident 1", "當地航空公司地勤罷工"),
        (None, "3 days after departure"),
    ]
    assert rows(exported, "Facts")[4:6] == [
        (None, "cost: 多住一晚的飯店費用 (lodging)"),
        (None, "cost: 多出來的餐費 (meals)"),
    ]
    paid = rows(exported, "Breakdown")[1]
    assert paid[2:] == (
        "trip change / strike",
        1,
        None,
        None,
        "paid",
        None,
        "reimburses transport, lodging",
        "第三十三條 一",
        None,
        None,
        "transport; lodging",
        (
            "多住一晚的飯店費用 (lodging): eligible, 第三十三條 一\n"
            "多出來的餐費 (meals): not eligible, 第三十三條 一"
        ),
    )
    source = "https://www.cathay-ins.com.tw/cathayins/personal/travel/oversea/"
    assert rows(exported, "Amounts")[1:] == [
        ("享樂遊", "new", "trip change / strike", 1, "安心型(T5)", 60000, None, None, source),
        ("享樂遊", "new", "trip change / strike", 1, "海外豪華型(U3)", 120000, None, None, source),
    ]


def test_a_scenario_with_no_supported_benefit_exports_only_that_notice(tmp_path: Path) -> None:
    workbook, store = import_draft(tmp_path)
    confirm(workbook)
    facts = ScenarioFacts(benefits=(Benefit.BAGGAGE_LOSS,), incidents=())
    matrix = judge_scenario(
        "行李遺失。", [workbook], store=store, models=ScriptedModels(facts=facts)
    )
    exported = tmp_path / "verdicts.xlsx"

    export_verdict_matrix(matrix, exported)

    assert rows(exported, "Verdict matrix") == [
        ("Scenario", "行李遺失。"),
        ("Not supported", "baggage loss"),
    ]
