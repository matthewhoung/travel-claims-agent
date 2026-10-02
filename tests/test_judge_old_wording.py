"""Judge a Scenario against 享樂遊 in both Wording versions: two cells side by side.

The old wording measures a flight delay to the next replacement flight when
force majeure prevented the insured from taking the first, as the proviso of
its first-replacement exclusion (第三十一條 四) does. Code takes both readings
from that proviso's judgement, so the delay period itself can turn on how the
Cause is classified.
"""

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

from travel_claims.app import judge_scenario
from travel_claims.clause_store import ClauseStore
from travel_claims.conditions import Benefit, ClauseRef
from travel_claims.judging import (
    Cell,
    ConditionOutcome,
    ReadingOutcome,
    Reason,
    TurningProvision,
    Verdict,
)
from travel_claims.local_models import (
    ArrangedBy,
    Incident,
    Judgement,
    Leg,
    NeedsFact,
    ProvisionKind,
    Replacement,
    ScenarioFacts,
    Settled,
)
from travel_claims.policies import Wording

from hsiang_le_you import (
    FORCE_MAJEURE,
    NOTHING_APPLIES,
    OLD_FIRST_REPLACEMENT,
    OLD_STRIKE,
    POLICY_PERIOD,
    PROVISO,
    ROAD_CLOSURE,
    TAIPEI,
    TYPHOON,
    confirm,
    import_draft,
    road_closure,
)
from scripted_models import ScriptedModels

SCHEDULED = datetime(2026, 7, 10, 10, 0, tzinfo=TAIPEI)
DELAY_PERIOD_RULE: Final = "delay-period rule"
FORCE_MAJEURE_RULE = (
    "the delay runs to the next replacement flight if force majeure prevented the insured "
    "from taking the first"
)
# The first replacement flight was not taken; the proviso of 第三十一條 四 turns on the Cause.
FIRST_NOT_TAKEN: dict[str, Judgement] = NOTHING_APPLIES | {
    "第三十一條 四": Settled(met=True),
    "第三十一條 五": Settled(met=True),
    PROVISO: FORCE_MAJEURE,
}


def old_and_new(directory: Path) -> tuple[list[Path], ClauseStore]:
    """享樂遊 in the old and the new wording, confirmed, with one Clause store."""
    new, store = import_draft(directory)
    old, _ = import_draft(directory, wording=Wording.OLD)
    for workbook in (old, new):
        confirm(workbook)
    return [old, new], store


def first_replacement_missed(first: timedelta, next: timedelta) -> ScenarioFacts:
    """The outbound flight is delayed; the insured misses the airline's first
    replacement, `first` after the scheduled departure, and takes the next."""
    return ScenarioFacts(
        benefits=(Benefit.FLIGHT_DELAY,),
        incidents=(
            Incident(
                leg=Leg.OUTBOUND,
                airport="桃園國際機場",
                transport="flight",
                scheduled_departure=SCHEDULED,
                replacements=(
                    Replacement(SCHEDULED + first, ArrangedBy.AIRLINE, taken=False),
                    Replacement(SCHEDULED + next, ArrangedBy.AIRLINE, taken=True),
                ),
            ),
        ),
        cause="機場聯外道路封閉",
        within_policy_period=True,
    )


def test_the_typhoon_scenario_is_paid_in_the_old_wording_and_not_in_the_new(
    tmp_path: Path,
) -> None:
    # The README's Scenario: the old wording has no typhoon-warning exclusion.
    scenario = "投保時海上颱風警報已發布。保險期間內，去程班機因颱風延誤 6 小時。"
    facts = ScenarioFacts(
        benefits=(Benefit.FLIGHT_DELAY,),
        incidents=(
            Incident(
                leg=Leg.OUTBOUND, airport=None, transport="flight", stated_delay=timedelta(hours=6)
            ),
        ),
        cause="颱風",
        within_policy_period=True,
        in_force_at_purchase=("海上颱風警報",),
    )
    workbooks, store = old_and_new(tmp_path)
    models = ScriptedModels(
        facts=facts,
        judgements=NOTHING_APPLIES
        | {TYPHOON.text: Settled(met=True), OLD_STRIKE.text: Settled(met=False)},
    )

    matrix = judge_scenario(scenario, workbooks, store=store, models=models)

    assert matrix.cells == (
        Cell(
            product="享樂遊",
            wording=Wording.OLD,
            verdict=Verdict.PAID,
            outcomes=(
                ConditionOutcome(
                    condition="flight delay",
                    incident=1,
                    verdict=Verdict.PAID,
                    grounds="a delay of 6 h 0 min: 1 full step of 4 hours",
                    clause=ClauseRef(30),
                    delay=timedelta(hours=6),
                    steps=1,
                ),
            ),
        ),
        Cell(
            product="享樂遊",
            wording=Wording.NEW,
            verdict=Verdict.NOT_PAID,
            outcomes=(
                ConditionOutcome(
                    condition="flight delay",
                    incident=1,
                    verdict=Verdict.NOT_PAID,
                    grounds=f"the exclusion applies: {TYPHOON.text}",
                    clause=ClauseRef(31, "二"),
                    delay=timedelta(hours=6),
                ),
            ),
        ),
    )
    # Each cell is judged on its own Wording version's 第三十條.
    covered_event = [r for r in models.judged if r.provision.kind is ProvisionKind.COVERED_EVENT]
    assert ["次一班替代班機" in r.clauses[0].text for r in covered_event] == [True, False]


def test_a_delay_that_reaches_the_threshold_only_under_force_majeure_is_cause_ambiguous(
    tmp_path: Path,
) -> None:
    # 3 hours to the first replacement flight, 6 to the next.
    workbooks, store = old_and_new(tmp_path)
    models = ScriptedModels(
        facts=first_replacement_missed(timedelta(hours=3), timedelta(hours=6)),
        judgements=FIRST_NOT_TAKEN,
    )

    old, new = judge_scenario(ROAD_CLOSURE, workbooks, store=store, models=models).cells

    readings = (
        ReadingOutcome(
            cause="不可抗力",
            verdict=Verdict.PAID,
            grounds="a delay of 6 h 0 min: 1 full step of 4 hours",
            clause=ClauseRef(30),
            delay=timedelta(hours=6),
        ),
        ReadingOutcome(
            cause="非不可抗力",
            verdict=Verdict.NOT_PAID,
            grounds="a delay of 3 h 0 min, under the threshold of 4 hours",
            clause=ClauseRef(30),
            delay=timedelta(hours=3),
        ),
    )
    assert (old.verdict, old.reason) == (Verdict.UNDETERMINED, Reason.CAUSE_AMBIGUOUS)
    assert old.outcomes == (
        ConditionOutcome(
            condition="flight delay",
            incident=1,
            verdict=Verdict.UNDETERMINED,
            reason=Reason.CAUSE_AMBIGUOUS,
            grounds=(
                "turns on how the Cause is classified, under the delay-period rule: "
                f"{FORCE_MAJEURE_RULE}; the proviso: {PROVISO}"
            ),
            clause=ClauseRef(30),
            turns_on=(
                TurningProvision(DELAY_PERIOD_RULE, FORCE_MAJEURE_RULE, ClauseRef(30), readings),
                TurningProvision(ProvisionKind.PROVISO, PROVISO, ClauseRef(31, "四"), readings),
            ),
        ),
    )
    # The new wording measures to the first replacement flight whatever the Cause.
    assert new.verdict is Verdict.NOT_PAID
    assert new.outcomes[0].grounds == "a delay of 3 h 0 min, under the threshold of 4 hours"


def test_the_road_closure_scenario_in_the_old_wording_measures_each_reading_on_its_own(
    tmp_path: Path,
) -> None:
    # 5 hours to the first replacement flight, 10 to the next: the threshold
    # is met either way, but the steps paid and the exclusion are not.
    workbooks, store = old_and_new(tmp_path)
    models = ScriptedModels(facts=road_closure(), judgements=FIRST_NOT_TAKEN)

    old, _ = judge_scenario(ROAD_CLOSURE, workbooks, store=store, models=models).cells

    [outcome] = old.outcomes
    assert (outcome.reason, outcome.clause, outcome.delay) == (
        Reason.CAUSE_AMBIGUOUS,
        ClauseRef(30),
        None,
    )
    assert [(p.kind, str(p.clause)) for p in outcome.turns_on] == [
        (DELAY_PERIOD_RULE, "第三十條"),
        (ProvisionKind.PROVISO, "第三十一條 四"),
    ]
    assert outcome.turns_on[1].readings == (
        ReadingOutcome(
            cause="不可抗力",
            verdict=Verdict.PAID,
            grounds="a delay of 10 h 0 min: 2 full steps of 4 hours",
            clause=ClauseRef(30),
            delay=timedelta(hours=10),
        ),
        ReadingOutcome(
            cause="非不可抗力",
            verdict=Verdict.NOT_PAID,
            grounds=f"the exclusion applies: {OLD_FIRST_REPLACEMENT.text}",
            clause=ClauseRef(31, "四"),
            delay=timedelta(hours=5),
        ),
    )


def test_a_proviso_that_applies_measures_the_delay_to_the_next_replacement_flight(
    tmp_path: Path,
) -> None:
    workbooks, store = old_and_new(tmp_path)
    models = ScriptedModels(
        facts=first_replacement_missed(timedelta(hours=3), timedelta(hours=6)),
        judgements=FIRST_NOT_TAKEN | {PROVISO: Settled(met=True)},
    )

    old, _ = judge_scenario(ROAD_CLOSURE, workbooks, store=store, models=models).cells

    assert old.outcomes == (
        ConditionOutcome(
            condition="flight delay",
            incident=1,
            verdict=Verdict.PAID,
            grounds="a delay of 6 h 0 min: 1 full step of 4 hours",
            clause=ClauseRef(30),
            delay=timedelta(hours=6),
            steps=1,
        ),
    )


def test_a_proviso_that_needs_a_fact_leaves_the_delay_and_the_outcome_undetermined(
    tmp_path: Path,
) -> None:
    workbooks, store = old_and_new(tmp_path)
    models = ScriptedModels(
        facts=first_replacement_missed(timedelta(hours=3), timedelta(hours=6)),
        judgements=FIRST_NOT_TAKEN | {PROVISO: NeedsFact("why the insured missed the flight")},
    )

    old, _ = judge_scenario(ROAD_CLOSURE, workbooks, store=store, models=models).cells

    assert (old.outcomes[0].reason, old.outcomes[0].delay) == (Reason.MISSING_FACT, None)
    assert old.outcomes[0].grounds == (
        "the proviso needs a fact the Scenario does not state: why the insured missed the flight"
    )


def test_a_delay_under_the_threshold_under_every_reading_is_not_paid_without_judging(
    tmp_path: Path,
) -> None:
    workbooks, store = old_and_new(tmp_path)
    # No judgement is scripted: nothing is judged.
    models = ScriptedModels(facts=first_replacement_missed(timedelta(hours=1), timedelta(hours=3)))

    old, _ = judge_scenario(ROAD_CLOSURE, workbooks, store=store, models=models).cells

    assert old.outcomes == (
        ConditionOutcome(
            condition="flight delay",
            incident=1,
            verdict=Verdict.NOT_PAID,
            grounds=(
                "a delay of 1 h 0 min, or 3 h 0 min if force majeure prevented taking the "
                "first replacement flight, under the threshold of 4 hours"
            ),
            clause=ClauseRef(30),
        ),
    )


def cancelled_return_flight(arranged_at: datetime, *, to: str, home: bool) -> ScenarioFacts:
    """The return flight from 成田 is cancelled with no replacement from the
    airline; the insured arranges one leaving the next afternoon."""
    scheduled = datetime(2026, 7, 14, 20, 0, tzinfo=TAIPEI)
    own = Replacement(
        departure=datetime(2026, 7, 15, 14, 0, tzinfo=TAIPEI),
        arranged_by=ArrangedBy.INSURED,
        taken=True,
        arranged_at=arranged_at,
        destination=to,
        returns_to_taiwan=home,
    )
    return ScenarioFacts(
        benefits=(Benefit.FLIGHT_DELAY,),
        incidents=(
            Incident(
                leg=Leg.RETURN,
                airport="成田國際機場",
                transport="flight",
                scheduled_departure=scheduled,
                cancelled=True,
                replacements=(own,),
            ),
        ),
        cause="颱風",
        policy_period=POLICY_PERIOD,
    )


def test_a_replacement_the_insured_arranged_counts_in_the_old_wording_only_within_the_period(
    tmp_path: Path,
) -> None:
    workbooks, store = old_and_new(tmp_path)

    def verdicts(facts: ScenarioFacts) -> list[tuple[Wording, Verdict, str]]:
        models = ScriptedModels(facts=facts, judgements=NOTHING_APPLIES)
        matrix = judge_scenario(ROAD_CLOSURE, workbooks, store=store, models=models)
        return [(c.wording, c.verdict, c.outcomes[0].grounds) for c in matrix.cells]

    # Arranged within the policy period, to 首爾: it counts in both wordings.
    within = cancelled_return_flight(
        datetime(2026, 7, 14, 21, 0, tzinfo=TAIPEI), to="首爾", home=False
    )
    assert verdicts(within) == [
        (Wording.OLD, Verdict.PAID, "a delay of 18 h 0 min: 4 full steps of 4 hours"),
        (Wording.NEW, Verdict.PAID, "a delay of 18 h 0 min: 4 full steps of 4 hours"),
    ]
    # Arranged after it ended, home to 桃園: only the new wording counts it.
    after = cancelled_return_flight(
        datetime(2026, 7, 15, 9, 0, tzinfo=TAIPEI), to="桃園", home=True
    )
    assert verdicts(after) == [
        (
            Wording.OLD,
            Verdict.NOT_PAID,
            (
                "no replacement flight counts toward the delay period: the one the insured "
                "arranged after the policy period ended does not count"
            ),
        ),
        (Wording.NEW, Verdict.PAID, "a delay of 18 h 0 min: 4 full steps of 4 hours"),
    ]


def test_under_force_majeure_the_delay_still_ends_when_the_booked_flight_departs(
    tmp_path: Path,
) -> None:
    # The first replacement, at 3 hours, is missed; the booked flight itself
    # leaves at 5 hours, before the next replacement at 6.
    workbooks, store = old_and_new(tmp_path)
    missed = first_replacement_missed(timedelta(hours=3), timedelta(hours=6))
    incident = replace(missed.incidents[0], actual_departure=SCHEDULED + timedelta(hours=5))
    models = ScriptedModels(
        facts=replace(missed, incidents=(incident,)),
        judgements=FIRST_NOT_TAKEN | {PROVISO: Settled(met=True)},
    )

    old, _ = judge_scenario(ROAD_CLOSURE, workbooks, store=store, models=models).cells

    assert old.outcomes[0].delay == timedelta(hours=5)
