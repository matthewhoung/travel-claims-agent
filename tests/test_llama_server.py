"""The real local-models adapter, against a stand-in for llama-server on 127.0.0.1.

The stand-in records each request and answers with the JSON content the test
scripts, so these tests check what the adapter asks of the model and how it
reads the answers, with no GPU. The run on the real model is
scripts/run_hsiang_le_you.py.
"""

import json
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from travel_claims.conditions import (
    COVERED_CAUSES,
    ELIGIBLE_COSTS,
    EXCLUSION_TYPES,
    Benefit,
    BenefitType,
    ClauseRef,
    CostCategory,
    ExclusionType,
)
from travel_claims.llama_server import LlamaServerModels, MalformedAnswer
from travel_claims.local_models import (
    ArrangedBy,
    ClauseRole,
    Cost,
    ExtractedCondition,
    Extraction,
    ExtractionRequest,
    Incident,
    Judgement,
    JudgementRequest,
    Leg,
    NeedsFact,
    NotSettled,
    Provision,
    ProvisionKind,
    Reading,
    Replacement,
    ScenarioFacts,
    Settled,
    TurnsOnCause,
)
from travel_claims.policies import Clause, Wording

import hsiang_le_you

TAIPEI = hsiang_le_you.TAIPEI

COVER = Clause(
    number=30,
    heading="班機延誤保險(定額給付-累進式)承保範圍",
    chapter="第三章 個人海外旅行不便保險",
    text="被保險人於本保險契約保險期間內，以乘客身分預定搭乘之定期航班發生延誤，"
    "致被保險人實際出發時間較預定出發時間延誤四小時以上者……",
    pages=(16, 16),
)
EXCLUSIONS = Clause(
    number=31,
    heading="班機延誤保險(定額給付-累進式)特別不保事項",
    chapter="第三章 個人海外旅行不便保險",
    text="對於下列事項或該事項所致之損失，本公司不負理賠責任：\n"
    "二、要保人向本公司申請訂立保險契約時，中華民國政府氣\n象機構已發布海上颱風警報。",
    pages=(16, 16),
)


class StandIn:
    """Answers each chat request with the next scripted content, and keeps the requests."""

    def __init__(self) -> None:
        # The port the stand-in listens on, once it is serving.
        self.port = 0
        self.requests: list[dict[str, Any]] = []
        self.answers: list[dict[str, Any] | str] = []
        self.finish_reason = "stop"

    @property
    def last(self) -> dict[str, Any]:
        return self.requests[-1]

    def schema(self) -> dict[str, Any]:
        """The JSON schema the last request constrained the answer to."""
        schema: dict[str, Any] = self.last["response_format"]["json_schema"]["schema"]
        return schema

    def prompt(self) -> str:
        return "\n".join(message["content"] for message in self.last["messages"])


@pytest.fixture
def stand_in() -> Iterator[StandIn]:
    state = StandIn()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.requests.append(body)
            answer = state.answers.pop(0)
            content = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
            reply = {
                "choices": [
                    {
                        "finish_reason": state.finish_reason,
                        "message": {"role": "assistant", "content": content},
                    }
                ]
            }
            data = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.port = server.server_address[1]
    yield state
    server.shutdown()
    thread.join()


def models_for(stand_in: StandIn) -> LlamaServerModels:
    return LlamaServerModels(port=stand_in.port, model="qwen3.5-9b")


def test_every_request_is_deterministic_and_constrained_to_a_json_schema(
    stand_in: StandIn,
) -> None:
    stand_in.answers.append({"exclusions": []})

    models_for(stand_in).extract(
        ExtractionRequest(EXCLUSIONS, ClauseRole.BENEFIT_EXCLUSIONS, Benefit.FLIGHT_DELAY, ())
    )

    request = stand_in.last
    assert request["model"] == "qwen3.5-9b"
    assert request["temperature"] == 0
    assert request["seed"] == 42
    assert request["id_slot"] == 0
    assert request["cache_prompt"] is False
    assert request["chat_template_kwargs"] == {"enable_thinking": False}
    assert request["response_format"]["type"] == "json_schema"


def test_a_cover_clause_is_read_into_conditions_with_the_benefits_own_lists(
    stand_in: StandIn,
) -> None:
    stand_in.answers.append(
        {
            "conditions": [
                {
                    "label": None,
                    "covered_event": "定期航班延誤四小時以上",
                    "coverage_requirements": {"scheduled flight": True, "as a passenger": True},
                    "coverage_window": None,
                    "window_days": None,
                    "threshold_hours": 4,
                    "benefit_type": "progressive fixed amount",
                    "step_hours": 4,
                    "max_claims_per_period": 2,
                    "eligible_costs": [],
                    "cost_maximums": None,
                    "item": None,
                }
            ],
            "exclusions": [],
            "caps_period_total": False,
        }
    )
    context = (EXCLUSIONS,)

    extraction = models_for(stand_in).extract(
        ExtractionRequest(COVER, ClauseRole.BENEFIT_COVER, Benefit.FLIGHT_DELAY, context)
    )

    assert extraction == Extraction(
        conditions=(
            ExtractedCondition(
                covered_event="定期航班延誤四小時以上",
                coverage_requirements=("scheduled flight", "as a passenger"),
                threshold_hours=4,
                benefit_type=BenefitType.PROGRESSIVE,
                step_hours=4,
                max_claims_per_period=2,
            ),
        )
    )
    condition = stand_in.schema()["properties"]["conditions"]["items"]["properties"]
    assert list(condition["coverage_requirements"]["properties"]) == [
        "scheduled flight",
        "as a passenger",
    ]
    assert condition["benefit_type"]["enum"] == list(BenefitType)
    # The Clause and the rest of its chapter are in the prompt.
    assert COVER.text in stand_in.prompt()
    assert "第三十一條" in stand_in.prompt()


def test_a_trip_cancellation_cover_clause_offers_its_covered_causes_window_and_eligible_costs(
    stand_in: StandIn,
) -> None:
    cover = Clause(
        number=27,
        heading="旅程取消保險(實支實付)承保範圍",
        chapter="第三章 個人海外旅行不便保險",
        text="被保險人於特定期間內因下列情事致其必須取消預定之全部旅程……\n"
        "一、被保險人、被保險人之配偶或三親等內親屬死亡或病危者。",
        pages=(15, 15),
    )
    causes = COVERED_CAUSES[Benefit.TRIP_CANCELLATION]
    stand_in.answers.append(
        {
            "conditions": [
                {
                    "label": "relative's death",
                    "covered_event": "因親屬死亡或病危必須取消預定之全部旅程",
                    "coverage_requirements": {cause: cause == causes[0] for cause in causes},
                    "coverage_window": "自預定海外旅程開始前二十日起至海外旅行期間開始時止",
                    "window_days": 20,
                    "threshold_hours": None,
                    "benefit_type": "reimbursement",
                    "step_hours": None,
                    "max_claims_per_period": None,
                    "eligible_costs": ["tour fee", "lodging"],
                    "cost_maximums": None,
                    "item": "一",
                }
            ],
            "exclusions": [],
            "caps_period_total": True,
        }
    )

    extraction = models_for(stand_in).extract(
        ExtractionRequest(cover, ClauseRole.BENEFIT_COVER, Benefit.TRIP_CANCELLATION, ())
    )

    assert extraction == Extraction(
        conditions=(
            ExtractedCondition(
                covered_event="因親屬死亡或病危必須取消預定之全部旅程",
                coverage_requirements=(causes[0],),
                threshold_hours=None,
                benefit_type=BenefitType.REIMBURSEMENT,
                step_hours=None,
                max_claims_per_period=None,
                label="relative's death",
                coverage_window="自預定海外旅程開始前二十日起至海外旅行期間開始時止",
                window_days=20,
                eligible_costs=("tour fee", "lodging"),
                item="一",
            ),
        ),
        caps_period_total=True,
    )
    schema = stand_in.schema()["properties"]
    condition = schema["conditions"]["items"]["properties"]
    assert list(condition["coverage_requirements"]["properties"]) == list(causes)
    assert condition["eligible_costs"]["items"]["enum"] == list(
        ELIGIBLE_COSTS[Benefit.TRIP_CANCELLATION]
    )
    assert schema["caps_period_total"] == {"type": "boolean"}
    # Each covered cause is described in the Clauses' words.
    assert f"  - {causes[0]}: 被保險人、配偶或三親等內親屬死亡或病危" in stand_in.prompt()


def test_an_exclusions_clause_is_offered_its_benefits_own_exclusion_types(
    stand_in: StandIn,
) -> None:
    baggage_loss = Clause(
        number=41,
        heading="行李損失保險(定額給付)特別不保事項",
        chapter="第三章 個人海外旅行不便保險",
        text="對於下列事項或該事項所致之損失，本公司不負理賠責任：\n"
        "八、非因竊盜、強盜與搶奪之不明原因遺失。",
        pages=(17, 17),
    )
    stand_in.answers.append(
        {
            "exclusions": [
                {
                    "type": "unexplained loss",
                    "text": "非因竊盜、強盜與搶奪之不明原因遺失。",
                    "proviso": None,
                    "concerns_cause": True,
                    "item": "八",
                }
            ]
        }
    )

    extraction = models_for(stand_in).extract(
        ExtractionRequest(baggage_loss, ClauseRole.BENEFIT_EXCLUSIONS, Benefit.BAGGAGE_LOSS, ())
    )

    assert extraction.exclusions[0].type is ExclusionType.UNEXPLAINED_LOSS
    exclusion = stand_in.schema()["properties"]["exclusions"]["items"]["properties"]
    offered = [*EXCLUSION_TYPES[Benefit.BAGGAGE_LOSS], ExclusionType.OTHER]
    assert exclusion["type"]["enum"] == offered
    # Each described in the prompt.
    assert "  - unexplained loss: 非因竊盜、強盜與搶奪之不明原因遺失" in stand_in.prompt()


def moment(time: str | None, date: str | None = None, day: int = 0) -> dict[str, Any]:
    return {"date": date, "day": day, "time": time}


def incident(**fields: Any) -> dict[str, Any]:
    return {
        "leg": None,
        "airport": None,
        "transport": None,
        "scheduled_departure": None,
        "actual_departure": None,
        "cancelled": False,
        "replacements": [],
        "missed_connection": False,
        "stated_delay_minutes": None,
        "event": None,
        "event_day": None,
        "during_trip": None,
        "costs": [],
    } | fields


def facts(**fields: Any) -> dict[str, Any]:
    return {
        "benefits": ["flight delay"],
        "incidents": [],
        "cause": None,
        "purchased_at": None,
        "policy_period": None,
        "within_policy_period": None,
        "in_force_at_purchase": [],
        "earlier_claims": None,
    } | fields


def test_a_scenario_with_times_but_no_dates_keeps_the_times_on_one_undated_day(
    stand_in: StandIn,
) -> None:
    replacement = {"arranged_by": "airline", "arranged_at": None, "destination": None}
    stand_in.answers.append(
        facts(
            incidents=[
                incident(
                    leg="outbound",
                    transport="flight",
                    scheduled_departure=moment("10:00"),
                    replacements=[
                        replacement
                        | {"departure": moment("15:00"), "taken": False, "returns_to_taiwan": None},
                        replacement
                        | {
                            "departure": moment("08:00", day=1),
                            "taken": True,
                            "returns_to_taiwan": None,
                        },
                    ],
                )
            ],
            cause="機場聯外道路封閉",
            within_policy_period=True,
        )
    )
    scenario = "保險期間內，去程班機原定 10:00 起飛……"

    read = models_for(stand_in).extract_facts(scenario)

    scheduled = read.incidents[0].scheduled_departure
    assert scheduled is not None
    assert read == ScenarioFacts(
        benefits=(Benefit.FLIGHT_DELAY,),
        incidents=(
            Incident(
                leg=Leg.OUTBOUND,
                airport=None,
                transport="flight",
                scheduled_departure=scheduled,
                replacements=(
                    Replacement(
                        departure=scheduled + timedelta(hours=5),
                        arranged_by=ArrangedBy.AIRLINE,
                        taken=False,
                    ),
                    Replacement(
                        departure=scheduled + timedelta(hours=22),
                        arranged_by=ArrangedBy.AIRLINE,
                        taken=True,
                    ),
                ),
            ),
        ),
        cause="機場聯外道路封閉",
        within_policy_period=True,
    )
    assert (scheduled.hour, scheduled.minute, scheduled.utcoffset()) == (10, 0, timedelta(hours=8))
    assert scenario in stand_in.prompt()
    assert stand_in.schema()["properties"]["benefits"]["items"]["enum"] == list(Benefit)


def test_a_trip_event_is_read_with_its_day_from_departure_and_the_costs_named(
    stand_in: StandIn,
) -> None:
    stand_in.answers.append(
        facts(
            benefits=["trip change"],
            incidents=[
                incident(
                    event="當地航空公司地勤罷工",
                    event_day=3,
                    during_trip=True,
                    costs=[
                        {"text": "多住一晚的飯店費用", "category": "lodging"},
                        {"text": "多出來的餐費", "category": "meals"},
                    ],
                )
            ],
        )
    )

    read = models_for(stand_in).extract_facts("旅程第四天遇到罷工……")

    assert read.incidents == (
        Incident(
            leg=None,
            airport=None,
            transport=None,
            event="當地航空公司地勤罷工",
            event_day=3,
            during_trip=True,
            costs=(
                Cost("多住一晚的飯店費用", CostCategory.LODGING),
                Cost("多出來的餐費", CostCategory.MEALS),
            ),
        ),
    )
    cost = stand_in.schema()["properties"]["incidents"]["items"]["properties"]["costs"]["items"]
    assert cost["properties"]["category"]["enum"] == list(CostCategory)


def test_dated_facts_are_read_in_taiwan_time_and_a_stated_delay_in_minutes(
    stand_in: StandIn,
) -> None:
    stand_in.answers.append(
        facts(
            incidents=[incident(leg="return", airport="成田國際機場", stated_delay_minutes=390)],
            cause="颱風",
            purchased_at=moment("12:00", "2026-07-01"),
            policy_period={
                "start": moment("00:00", "2026-07-10"),
                "end": moment("23:59", "2026-07-14"),
            },
            in_force_at_purchase=["海上颱風警報"],
            earlier_claims=1,
        )
    )

    read = models_for(stand_in).extract_facts("投保時海上颱風警報已發布……")

    assert read == ScenarioFacts(
        benefits=(Benefit.FLIGHT_DELAY,),
        incidents=(
            Incident(
                leg=Leg.RETURN,
                airport="成田國際機場",
                transport=None,
                stated_delay=timedelta(hours=6, minutes=30),
            ),
        ),
        cause="颱風",
        purchased_at=datetime(2026, 7, 1, 12, 0, tzinfo=TAIPEI),
        policy_period=(
            datetime(2026, 7, 10, 0, 0, tzinfo=TAIPEI),
            datetime(2026, 7, 14, 23, 59, tzinfo=TAIPEI),
        ),
        in_force_at_purchase=("海上颱風警報",),
        earlier_claims=1,
    )


TYPHOON = Provision(
    ProvisionKind.EXCLUSION,
    "要保人向本公司申請訂立保險契約時，中華民國政府氣象機構已發布海上颱風警報。",
    ClauseRef(31, "二"),
    concerns_cause=False,
)
PROVISO = Provision(
    ProvisionKind.PROVISO,
    "但被保險人因不可抗力因素致無法搭乘航空業者所提供之第一班替代交通工具者，不在此限。",
    ClauseRef(31, "五"),
    concerns_cause=True,
)
TYPHOON_FACTS = ScenarioFacts(
    benefits=(Benefit.FLIGHT_DELAY,),
    incidents=(Incident(leg=Leg.OUTBOUND, airport=None, transport="flight"),),
    cause="颱風",
    in_force_at_purchase=("海上颱風警報",),
)


def judge(stand_in: StandIn, provision: Provision, answer: dict[str, Any]) -> Judgement:
    stand_in.answers.append(answer)
    return models_for(stand_in).judge(JudgementRequest(provision, TYPHOON_FACTS, (EXCLUSIONS,)))


def answers_offered(stand_in: StandIn) -> set[str]:
    return {branch["properties"]["answer"]["const"] for branch in stand_in.schema()["anyOf"]}


def test_an_exclusion_is_judged_with_its_clause_and_the_facts_read(stand_in: StandIn) -> None:
    judgement = judge(stand_in, TYPHOON, {"reasoning": "投保時已發布", "answer": "applies"})

    assert judgement == Settled(met=True)
    assert TYPHOON.text in stand_in.prompt()
    assert EXCLUSIONS.text in stand_in.prompt()
    assert "海上颱風警報" in stand_in.prompt()


def test_only_a_provision_that_concerns_the_cause_may_be_answered_as_turning_on_it(
    stand_in: StandIn,
) -> None:
    judge(stand_in, TYPHOON, {"reasoning": "", "answer": "does not apply"})
    assert answers_offered(stand_in) == {"applies", "does not apply", "needs a fact", "not settled"}

    judgement = judge(
        stand_in,
        PROVISO,
        {
            "reasoning": "道路封閉是否屬不可抗力",
            "answer": "turns on the Cause",
            "readings": [{"cause": "不可抗力", "met": True}, {"cause": "非不可抗力", "met": False}],
        },
    )
    assert "turns on the Cause" in answers_offered(stand_in)
    assert judgement == TurnsOnCause((Reading("不可抗力", True), Reading("非不可抗力", False)))


def test_a_covered_event_is_answered_within_or_outside(stand_in: StandIn) -> None:
    event = Provision(ProvisionKind.COVERED_EVENT, "定期航班延誤四小時以上", ClauseRef(30), False)

    assert judge(stand_in, event, {"reasoning": "", "answer": "outside"}) == Settled(met=False)
    assert answers_offered(stand_in) == {"within", "outside", "needs a fact", "not settled"}


def test_a_judgement_can_name_a_missing_fact_or_what_the_clauses_leave_unaddressed(
    stand_in: StandIn,
) -> None:
    missing = judge(
        stand_in,
        TYPHOON,
        {"reasoning": "", "answer": "needs a fact", "fact": "投保時是否已發布警報"},
    )
    silent = judge(
        stand_in, TYPHOON, {"reasoning": "", "answer": "not settled", "unaddressed": "陸上颱風警報"}
    )

    assert missing == NeedsFact("投保時是否已發布警報")
    assert silent == NotSettled("陸上颱風警報")


def test_an_answer_cut_off_by_the_length_limit_is_refused(stand_in: StandIn) -> None:
    stand_in.finish_reason = "length"

    with pytest.raises(MalformedAnswer, match="cut off"):
        judge(stand_in, TYPHOON, {"reasoning": "", "answer": "applies"})


def test_retrieval_is_not_served_yet(stand_in: StandIn) -> None:
    models = models_for(stand_in)

    models.index("享樂遊", Wording.NEW, (COVER, EXCLUSIONS))

    assert models.find_related("享樂遊", Wording.NEW, TYPHOON_FACTS) == ()
    assert stand_in.requests == []


def branches_where(stand_in: StandIn, field: str, value: object) -> set[str]:
    """The answers the last schema allows once `field` is answered `value`."""
    return {
        branch["properties"]["answer"]["const"]
        for branch in stand_in.schema()["anyOf"]
        if branch["properties"].get(field, {}).get("const") == value
    }


def test_a_matter_the_facts_do_not_mention_did_not_happen(stand_in: StandIn) -> None:
    event = Provision(ProvisionKind.COVERED_EVENT, "定期航班延誤四小時以上", ClauseRef(30), False)

    judge(stand_in, TYPHOON, {"about": "", "mentioned": False, "answer": "does not apply"})
    assert branches_where(stand_in, "mentioned", False) == {"does not apply"}
    judge(stand_in, PROVISO, {"about": "", "mentioned": False, "answer": "does not apply"})
    assert branches_where(stand_in, "mentioned", False) == {"does not apply"}
    judge(stand_in, event, {"about": "", "mentioned": False, "answer": "within"})
    assert branches_where(stand_in, "mentioned", False) == {"within"}


def test_only_an_unclear_classification_of_the_cause_turns_on_it(stand_in: StandIn) -> None:
    judge(stand_in, PROVISO, {"answer": "applies"})

    assert branches_where(stand_in, "classification", "unclear") == {"turns on the Cause"}
    assert branches_where(stand_in, "classification", "plainly within") == {"applies"}
    assert branches_where(stand_in, "classification", "plainly outside") == {"does not apply"}
    # Words that do not fit the facts settle the provision before the Cause is classified.
    assert branches_where(stand_in, "other_words_fit", False) == {"does not apply"}
