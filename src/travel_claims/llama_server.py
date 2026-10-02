"""The real local-models adapter: llama-server in router mode, on 127.0.0.1.

Every request names one model, so the router (started with --models-max 1)
keeps one model on the GPU. Every request is deterministic: temperature 0, a
fixed seed, the one slot, no reuse of a cached prompt, and no thinking. Every
answer is constrained to a JSON schema made for the request, so it parses into
the port's types. Retrieval is not served yet: indexing does nothing and no
related Clause is found.
"""

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Self

from travel_claims.conditions import (
    BENEFIT_NAMES,
    COVERAGE_REQUIREMENTS,
    EXCLUSION_TYPES,
    Benefit,
    BenefitType,
    ClauseRef,
    ExclusionType,
)
from travel_claims.local_models import (
    UNDATED,
    UNDATED_DAYS,
    ArrangedBy,
    ClauseRole,
    ExtractedCondition,
    ExtractedExclusion,
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
from travel_claims.report import describe_facts

SEED = 42
DEFAULT_PORT = 8080
DEFAULT_MODEL = "qwen3.5-9b"
# The other Clauses of a chapter go into the prompt, nearest first, up to this
# many characters, so that the prompt fits the 8k context.
_CONTEXT_CHARACTERS = 4000
_MOST_TOKENS = 3000
# Times in the policy are Taiwan time (中原標準時間). A Scenario's times are read so.
TAIPEI = timezone(timedelta(hours=8))


def configured_models(env_file: Path = Path(".env")) -> "LlamaServerModels":
    """The adapter as .env configures it, the environment taking precedence."""
    return LlamaServerModels.from_env(_read_env(env_file) | dict(os.environ))


def _read_env(path: Path) -> dict[str, str]:
    """The KEY=value lines of a .env file, as the shell would read these simple ones."""
    if not path.is_file():
        return {}
    settings = {}
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.lstrip().startswith("#"):
            settings[key.strip()] = os.path.expandvars(value.strip().strip("'\""))
    return settings


class MalformedAnswer(Exception):
    """The model's answer was cut off or does not fit the schema it was constrained to."""


class LlamaServerModels:
    """The local models, served by llama-server's OpenAI-compatible API."""

    def __init__(
        self,
        *,
        port: int = DEFAULT_PORT,
        model: str = DEFAULT_MODEL,
        year: int | None = None,
        timeout: float = 600,
    ) -> None:
        self.base = f"http://127.0.0.1:{port}"
        self.model = model
        # The year of a date a Scenario gives without one.
        self.year = year or datetime.now(TAIPEI).year
        self.timeout = timeout

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Self:
        """Configured as in .env: LLAMA_PORT, and LLM_MODEL, a section of models.ini."""
        return cls(
            port=int(env.get("LLAMA_PORT", DEFAULT_PORT)), model=env.get("LLM_MODEL", DEFAULT_MODEL)
        )

    # Extracting from a Clause ------------------------------------------------------

    def extract(self, request: ExtractionRequest) -> Extraction:
        role = request.role
        return self._ask(
            "an extraction",
            _extraction,
            _EXTRACT_SYSTEM
            + _ROLE_INSTRUCTIONS[role].format(
                benefit=request.benefit,
                types="\n".join(
                    f"  - {t}: {_TYPE_DESCRIPTIONS[t]}" for t in _exclusion_types(request.benefit)
                ),
            ),
            _clause_prompt(request.clause, request.context),
            f"extraction_{role.name.lower()}",
            _extraction_schema(role, request.benefit),
        )

    # The facts of a Scenario --------------------------------------------------------

    def extract_facts(self, scenario: str) -> ScenarioFacts:
        return self._ask(
            "Scenario facts",
            _facts,
            _FACTS_SYSTEM.format(
                year=self.year,
                benefits="\n".join(f"  - {b}: {name}" for name, b in BENEFIT_NAMES.items()),
            ),
            f"The Scenario:\n{scenario}",
            "scenario_facts",
            _FACTS_SCHEMA,
        )

    # Judging one provision ----------------------------------------------------------

    def judge(self, request: JudgementRequest) -> Judgement:
        provision = request.provision
        return self._ask(
            "a judgement",
            _judgement,
            _JUDGE_SYSTEM.format(
                kind=provision.kind,
                default=_default(provision),
                answers=_ANSWER_MEANINGS[provision.kind]
                + (
                    _TURNS_ON_CAUSE_MEANING.format(unmet=_answers(provision)[1])
                    if provision.concerns_cause
                    else ""
                ),
            ),
            _judgement_prompt(request),
            "judgement",
            _judgement_schema(provision),
        )

    # Retrieval (not served yet) -----------------------------------------------------

    def index(self, product: str, wording: Wording, clauses: Sequence[Clause]) -> None:
        pass

    def find_related(self, product: str, wording: Wording, facts: ScenarioFacts) -> tuple[int, ...]:
        return ()

    # The API ------------------------------------------------------------------------

    def _ask[T](
        self,
        what: str,
        read: Callable[[dict[str, Any]], T],
        system: str,
        user: str,
        name: str,
        schema: dict[str, Any],
    ) -> T:
        """One request, its answer read into the port's types by `read`."""
        answer = self._chat(system, user, name, schema)
        try:
            return read(answer)
        except (KeyError, TypeError, ValueError) as error:
            raise MalformedAnswer(f"{what} that does not fit its schema: {answer}") from error

    def _chat(self, system: str, user: str, name: str, schema: dict[str, Any]) -> dict[str, Any]:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # A bound on the answer, in case decoding loops.
            "max_tokens": _MOST_TOKENS,
            "temperature": 0,
            "seed": SEED,
            "id_slot": 0,
            "cache_prompt": False,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": name, "strict": True, "schema": schema},
            },
        }
        request = urllib.request.Request(
            f"{self.base}/v1/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                reply = json.load(response)
        except urllib.error.HTTPError as error:
            raise ConnectionError(
                f"llama-server refused the request: {error}: {error.read().decode(errors='replace')}"
            ) from error
        except urllib.error.URLError as error:
            raise ConnectionError(
                f"llama-server is not reachable at {self.base}; start it with "
                f"scripts/serve_models.sh: {error.reason}"
            ) from error
        choice = reply["choices"][0]
        content = choice["message"]["content"]
        if choice.get("finish_reason") != "stop":
            raise MalformedAnswer(
                f"the answer was cut off ({choice.get('finish_reason')}): {content}"
            )
        try:
            answer = json.loads(content)
        except json.JSONDecodeError as error:
            raise MalformedAnswer(f"the answer is not JSON: {content}") from error
        if not isinstance(answer, dict):
            raise MalformedAnswer(f"the answer is not a JSON object: {content}")
        return answer


# Prompts ----------------------------------------------------------------------------

_EXTRACT_SYSTEM = """\
You read one Clause (條) of a Taiwanese travel insurance policy and extract what \
it states, as JSON. Report only what the Clause text states; never add what it \
does not say. Copy Chinese text verbatim, but join lines that the PDF layout \
broke in the middle of a sentence, so that no line break is left inside a \
sentence. Numbered items are written 一、 二、 三、 and cited by their numeral \
alone, such as 二.

"""

_EXCLUSION_RULES = """\
List each exclusion as its own entry: one per numbered item.
- text: the item's text verbatim, without its number and without its proviso.
- proviso: the sentence of the item that makes an exception to it, usually \
starting 但 and ending 不在此限, verbatim; null if there is none.
- concerns_cause: true when whether the exclusion applies can depend on how \
the Cause of an incident is classified (why it happened), such as the \
insured's own reason, a wilful act, or force majeure (不可抗力); false when it \
turns only on facts such as dates, times, warnings, documents or who did what.
- type: the type that fits the exclusion, from this list; other if none fits.
{types}
- item: the item's numeral, such as 二; null if the Clause has no numbered items.
"""

# What each exclusion type is, in the words of the reference clauses.
_TYPE_DESCRIPTIONS = {
    ExclusionType.OWN_REASON: "被保險人因本身事由而未搭乘預定之班機或錯過轉接班機",
    ExclusionType.TYPHOON_WARNING: "投保時中華民國政府氣象機構已發布海上颱風警報",
    ExclusionType.STRIKE: "投保時已發生、已宣布或已預告罷工或工運活動，或已取得罷工權",
    ExclusionType.LATE_CHECK_IN: "被保險人抵達機場時已逾辦理登機之時間",
    ExclusionType.FIRST_REPLACEMENT_NOT_TAKEN: "被保險人未搭乘航空業者所提供之第一班替代交通工具",
    ExclusionType.SELF_ARRANGED_ELSEWHERE: "被保險人自行安排替代班機之目的地與原班機不同",
    ExclusionType.AIRLINE_INSOLVENCY: "航空業者破產、清算或債務不履行",
    ExclusionType.OTHER: "any other exclusion",
}

_ROLE_INSTRUCTIONS = {
    ClauseRole.BENEFIT_COVER: """\
This is the cover Clause (承保範圍) of the {benefit} benefit. List each \
Condition it states: a covered event that on its own decides one payout. Most \
cover Clauses state one Condition. A rule for measuring a delay, or for what \
counts as one incident, belongs to a Condition and is not a Condition itself.
- label: null when the Clause states one Condition, as most do. Only when it \
states several, a short English label telling each apart, such as "strike".
- covered_event: the covered event, condensed in Chinese from the Clause's own words.
- coverage_requirements: for each requirement, whether the Clause states it.
- coverage_window: null when the event is covered within the policy period \
(保險期間內), as most are; otherwise the other window the Clause states, such as \
a number of days before departure.
- threshold_hours: the least delay, in hours, that is paid; null if none.
- benefit_type: progressive fixed amount when a fixed amount is paid for each \
full step of hours; one-off fixed amount when a fixed amount is paid once; \
reimbursement when costs are reimbursed.
- step_hours: the hours of one step of a progressive benefit; null otherwise.
- max_claims_per_period: the most payments in the policy period; null if not stated.
- eligible_costs and cost_maximums: for a reimbursement, the costs it pays \
and their maximums; empty and null otherwise.
- item: null when the Clause's opening paragraphs state the Condition, as \
most do. Only when a numbered item (一、 二、) itself states a covered event, \
that item's numeral. Items that measure a delay or define one incident do not \
state a Condition.
List no exclusions unless this Clause itself excludes something.
""",
    ClauseRole.BENEFIT_EXCLUSIONS: "This Clause lists the exclusions (不保事項) of the "
    "{benefit} benefit.\n" + _EXCLUSION_RULES,
    ClauseRole.GENERAL_EXCLUSIONS: "This Clause lists the general exclusions "
    "(共同不保事項), which apply to every benefit.\n" + _EXCLUSION_RULES,
    ClauseRole.DEFINITIONS: """\
This Clause defines terms (用詞定義). List only what a definition expressly \
leaves out of cover or out of the term, such as a sentence starting 但不包含, as \
exclusions; most definitions leave nothing out, and then the list is empty.
"""
    + _EXCLUSION_RULES,
    ClauseRole.POLICY_PERIOD: """\
This Clause states the policy period (保險期間), or how it is extended. \
policy_period: what the Clause says, in one sentence of its own words; null if \
it says nothing about the policy period.
""",
}


_FACTS_SYSTEM = """\
You read a Scenario, a travel incident described in Traditional Chinese, into \
facts, as JSON. Report only what the Scenario states: a fact it does not state \
is null, false or empty. Never compute or estimate a time or a delay.
- benefits: the benefits the Scenario touches, from this list:
{benefits}
- incidents: one per incident, such as a delay of the outbound flight. leg is \
outbound (去程) or return (回程); transport is how the insured travelled, such \
as flight or ferry. scheduled_departure is the booked flight's; \
actual_departure is when the booked flight itself left; cancelled is whether \
it was cancelled. replacements: each replacement flight offered or taken, in \
order of departure, with who arranged it (insured only when the Scenario \
says the insured booked or bought it, as in 自行安排 or 自行購票; airline when it \
says the airline offered or arranged it, or when the flight is simply the next \
one after the airline's; otherwise null), whether the insured took it, and for one the insured arranged, when it was arranged, \
its destination and whether it flies to Taiwan. missed_connection: whether a \
connecting flight was missed. stated_delay_minutes: the delay in minutes, only \
when the Scenario states a delay without departure times.
- cause: why the incident happened, in the Scenario's words.
- purchased_at: when the policy was bought. policy_period: its start and end. \
within_policy_period: true or false only when the Scenario says the trip is \
within (保險期間內) or outside the policy period without giving its dates.
- in_force_at_purchase: warnings or strikes the Scenario says were in force \
when the policy was bought, such as 海上颱風警報.
- earlier_claims: claims already paid in the policy period, if stated.
A time is a date, a day and a time of day. date: YYYY-MM-DD when the Scenario \
gives the date, with the year {year} if it gives none; otherwise null, and day \
is the number of days after the booked flight's day (0 the same day, 1 the \
next day, as in 隔天). time: HH:MM on a 24-hour clock, or null if not stated.
"""


_JUDGE_SYSTEM = """\
You judge one provision of a Taiwanese travel insurance policy against the \
facts read from a Scenario, as JSON. The provision is a {kind}. Judge only \
this provision's own words. The Clause is given for context: its other items \
are other provisions, judged separately. Answer in three steps.
1. about: the matter the provision's own words turn on, in a few words, such \
as "a relative's death before departure" or "an illness known at purchase".
2. mentioned: whether the facts say anything about that matter. The Scenario \
states everything that happened, so what it does not mention did not happen, \
and then the answer is "{default}".
3. Only when it is mentioned: your reasoning in one or two short sentences; \
fits, whether the facts fit the provision's own words; then the answer that \
follows from it:
- yes or no:
{answers}\
- the facts leave it open: "needs a fact". The facts mention the matter but \
leave out the fact that decides it, such as a typhoon with no word on whether \
a warning was in force at purchase. Name that fact. How the stated Cause is \
classified is never a missing fact.
- the Clause leaves it open: "not settled". The Clause text does not settle \
the situation; say what it leaves unaddressed.
Read the facts this way:
- The booked flight (預定之班機, 預定搭乘班機) is the one the insured booked \
first, never a replacement flight. When the booked flight is delayed or \
cancelled and replaced, the insured not boarding it is the airline's doing, \
not the insured's. When the facts list no replacement flight, none was \
offered. Every flight in the facts is a scheduled flight the insured \
travelled on as a passenger, unless they say otherwise.
- "In force at purchase" lists what was in force when the policy was applied \
for (投保時, 申請訂立保險契約時); when it lists none, nothing was.
- Code has already measured the delay and found it meets the threshold, and \
that the trip is within the policy period. Take hours, thresholds and dates \
as met; never ask for a time or a duration.
"""

_ANSWER_MEANINGS = {
    ProvisionKind.COVERED_EVENT: '- "within" or "outside": whether the incident is the '
    "kind of event the covered event describes, such as a delay of a scheduled flight "
    "and not of a ferry. The hours and dates it names are already met.\n",
    ProvisionKind.COVERAGE_REQUIREMENT: '- "within" or "outside": whether the facts meet '
    "the coverage requirement.\n",
    ProvisionKind.EXCLUSION: '- "applies" or "does not apply": whether the exclusion '
    "applies to the facts. Its proviso, the exception after it starting 但, is a separate "
    "provision judged on its own: ignore it entirely, as if the exclusion ended before "
    "it. When the facts fit the exclusion's words, it applies, even if its exception "
    "might lift it; a fact only the exception needs is never missing here.\n",
    ProvisionKind.PROVISO: '- "applies" or "does not apply": whether the proviso, the '
    "exception to its exclusion, applies to the facts.\n",
}

_TURNS_ON_CAUSE_MEANING = """\
This provision may turn on how the Cause is classified. After "mentioned", give:
- cause_term: the term in the provision's own words that classifies why the \
event it describes happened, such as 不可抗力 (force majeure), 本身事由 (the \
insured's own reason) or 故意 (wilful); null when its own words name none.
When there is a term, then give your reasoning, and:
- other_words_fit: whether the facts fit the provision's words apart from the \
term. For 「因不可抗力致無法出發」, that is whether the insured could not depart. \
If not, the answer is "{unmet}".
- event_cause: what caused that event, as the facts tell it.
- classification: whether that cause is plainly within the term, plainly \
outside it, or unclear. Plain cases are few: an airline delaying, cancelling \
or replacing a flight is plainly not the insured's own reason; the insured \
oversleeping plainly is. Whether an outside event, such as a road closure, \
the weather or an illness, counts as force majeure (不可抗力) is never plain: \
the Clauses do not define it, and that classification is for the person \
reading the Verdict, not for you. When it is unclear, the answer is "turns on \
the Cause": list each plausible classification, in a few Chinese words such \
as 不可抗力 and 非不可抗力, and whether the provision is met under it.
"""


# What each coverage requirement means, in the Clauses' words.
_REQUIREMENT_DESCRIPTIONS = {
    "scheduled flight": "the delayed flight is a scheduled flight (定期航班)",
    "as a passenger": "the insured travels as a passenger (以乘客身分)",
}


def _judgement_prompt(request: JudgementRequest) -> str:
    provision = request.provision
    text = provision.text
    if provision.kind is ProvisionKind.COVERAGE_REQUIREMENT:
        text = _REQUIREMENT_DESCRIPTIONS.get(text, text)
    facts = "\n".join(
        f"{label}: {text}" if label else f"  {text}"
        for label, text in describe_facts(request.facts)
    )
    clauses = "\n\n".join(_cited(c) for c in request.clauses)
    return (
        f"The provision, the {provision.kind} of {provision.clause}:\n{text}\n\n"
        f"The Clauses:\n{clauses}\n\n"
        f"The facts read from the Scenario:\n{facts}"
    )


def _clause_prompt(clause: Clause, context: Sequence[Clause]) -> str:
    parts = [f"The Clause:\n{_cited(clause)}"]
    nearby = _nearest(clause, context)
    if nearby:
        parts.append(
            "Other Clauses of the same chapter, for context only:\n"
            + "\n\n".join(_cited(c) for c in nearby)
        )
    return "\n\n".join(parts)


def _cited(clause: Clause) -> str:
    return f"{ClauseRef(clause.number)} {clause.heading}\n{clause.text}"


def _nearest(clause: Clause, context: Sequence[Clause]) -> list[Clause]:
    """The context Clauses nearest `clause` by number, within the budget, in Clause order."""
    chosen: list[Clause] = []
    used = 0
    for other in sorted(context, key=lambda c: (abs(c.number - clause.number), c.number)):
        size = len(_cited(other))
        if used + size > _CONTEXT_CHARACTERS:
            break
        chosen.append(other)
        used += size
    return sorted(chosen, key=lambda c: c.number)


# Schemas ----------------------------------------------------------------------------


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def _array(items: dict[str, Any], most: int) -> dict[str, Any]:
    # A bound on every list: greedy decoding can otherwise repeat an entry until
    # the answer is cut off.
    return {"type": "array", "items": items, "maxItems": most}


_TEXT = {"type": "string"}
_MOST_CONDITIONS = 10
_MOST_EXCLUSIONS = 20
_MOST_COSTS = 10
_MOST_INCIDENTS = 10
_MOST_REPLACEMENTS = 10
_MOST_IN_FORCE = 10
_ITEM = _nullable({"type": "string", "pattern": "^[一二三四五六七八九十]+$"})


def _moment_schema() -> dict[str, Any]:
    return _nullable(
        _object(
            {
                "date": _nullable({"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"}),
                "day": {"type": "integer", "minimum": 0, "maximum": UNDATED_DAYS},
                "time": _nullable({"type": "string", "pattern": "^[0-9]{2}:[0-9]{2}$"}),
            }
        )
    )


def _choice(values: Sequence[str]) -> dict[str, Any]:
    return _nullable({"enum": list(values)})


_MOMENT = _moment_schema()
_FACTS_SCHEMA = _object(
    {
        "benefits": _array({"enum": [str(b) for b in Benefit]}, len(Benefit)),
        "incidents": _array(
            _object(
                {
                    "leg": _choice(list(Leg)),
                    "airport": _nullable(_TEXT),
                    "transport": _nullable(_TEXT),
                    "scheduled_departure": _MOMENT,
                    "actual_departure": _MOMENT,
                    "cancelled": {"type": "boolean"},
                    "replacements": _array(
                        _object(
                            {
                                "departure": _MOMENT,
                                "arranged_by": _choice(list(ArrangedBy)),
                                "taken": _nullable({"type": "boolean"}),
                                "arranged_at": _MOMENT,
                                "destination": _nullable(_TEXT),
                                "returns_to_taiwan": _nullable({"type": "boolean"}),
                            }
                        ),
                        _MOST_REPLACEMENTS,
                    ),
                    "missed_connection": {"type": "boolean"},
                    "stated_delay_minutes": _nullable({"type": "integer", "minimum": 0}),
                }
            ),
            _MOST_INCIDENTS,
        ),
        "cause": _nullable(_TEXT),
        "purchased_at": _MOMENT,
        "policy_period": _nullable(_object({"start": _MOMENT, "end": _MOMENT})),
        "within_policy_period": _nullable({"type": "boolean"}),
        "in_force_at_purchase": _array(_TEXT, _MOST_IN_FORCE),
        "earlier_claims": _nullable({"type": "integer", "minimum": 0}),
    }
)


def _judgement_schema(provision: Provision) -> dict[str, Any]:
    """One branch per answer the provision allows; turning on the Cause only if it concerns it.

    A matter the facts do not mention allows only the default answer: what the
    Scenario does not mention did not happen.
    """
    met, unmet = _answers(provision)
    about = {"type": "string", "maxLength": 200}
    reasoning = {"type": "string", "maxLength": 400}

    def branch(cause: dict[str, Any], **answer: dict[str, Any]) -> dict[str, Any]:
        return _object(
            {
                "about": about,
                "mentioned": {"const": True},
                **cause,
                "reasoning": reasoning,
                **answer,
            }
        )

    unmentioned = _object(
        {"about": about, "mentioned": {"const": False}, "answer": {"const": _default(provision)}}
    )
    # Whether the facts fit the provision's words decides the answer.
    settling = [
        {"fits": {"const": "yes"}, "answer": {"const": met}},
        {"fits": {"const": "no"}, "answer": {"const": unmet}},
        {
            "fits": {"const": "the facts leave it open"},
            "answer": {"const": "needs a fact"},
            "fact": _TEXT,
        },
        {
            "fits": {"const": "the Clause leaves it open"},
            "answer": {"const": "not settled"},
            "unaddressed": _TEXT,
        },
    ]
    if not provision.concerns_cause:
        return {"anyOf": [unmentioned, *(branch({}, **answer) for answer in settling)]}
    # A provision that concerns the Cause first names the term in its own words
    # that classifies the Cause. If it names one, the rest of its words must fit
    # the facts before the Cause is classified; only an unclear classification
    # turns on the Cause, and it must.
    term = {"type": "string", "pattern": "^[^A-Za-z()（）]+$"}
    no_term = {"cause_term": {"type": "null"}}
    reading = _object({"cause": term, "met": {"type": "boolean"}})

    def with_term(fits: bool, **rest: dict[str, Any]) -> dict[str, Any]:
        return _object(
            {
                "about": about,
                "mentioned": {"const": True},
                "cause_term": term,
                "reasoning": reasoning,
                "other_words_fit": {"const": fits},
                **({"event_cause": _TEXT} if fits else {}),
                **rest,
            }
        )

    return {
        "anyOf": [
            unmentioned,
            *(branch(no_term, **answer) for answer in settling),
            with_term(False, answer={"const": unmet}),
            # The provision is met when the Cause is what its term names.
            with_term(True, classification={"const": "plainly within"}, answer={"const": met}),
            with_term(True, classification={"const": "plainly outside"}, answer={"const": unmet}),
            with_term(
                True,
                classification={"const": "unclear"},
                answer={"const": "turns on the Cause"},
                readings={"type": "array", "items": reading, "minItems": 2, "maxItems": 4},
            ),
        ]
    }


def _answers(provision: Provision) -> tuple[str, str]:
    """The answers that settle a provision: met, then not met."""
    return ("applies", "does not apply") if _excludes(provision) else ("within", "outside")


def _default(provision: Provision) -> str:
    """The answer for a matter the facts do not mention: an exclusion or proviso does
    not apply, and a covered event or requirement is met, as the facts read by default."""
    met, unmet = _answers(provision)
    return unmet if _excludes(provision) else met


def _excludes(provision: Provision) -> bool:
    """Whether the provision is an exclusion, or a proviso, which applies to its exclusion."""
    return provision.kind in (ProvisionKind.EXCLUSION, ProvisionKind.PROVISO)


def _exclusion_types(benefit: Benefit | None) -> list[ExclusionType]:
    """A Benefit's own exclusion types, then other; only other for a general Clause."""
    own = EXCLUSION_TYPES.get(benefit, ()) if benefit is not None else ()
    return [*own, ExclusionType.OTHER]


def _extraction_schema(role: ClauseRole, benefit: Benefit | None) -> dict[str, Any]:
    if role is ClauseRole.POLICY_PERIOD:
        return _object({"policy_period": _nullable(_TEXT)})
    types = _exclusion_types(benefit)
    exclusions = _array(
        _object(
            {
                "type": {"enum": [str(t) for t in types]},
                "text": _TEXT,
                "proviso": _nullable(_TEXT),
                "concerns_cause": {"type": "boolean"},
                "item": _ITEM,
            }
        ),
        _MOST_EXCLUSIONS,
    )
    if role is not ClauseRole.BENEFIT_COVER:
        return _object({"exclusions": exclusions})
    assert benefit is not None  # a cover Clause belongs to a Benefit
    hours = _nullable({"type": "number"})
    condition = _object(
        {
            "label": _nullable(_TEXT),
            "covered_event": _TEXT,
            # One yes or no for each requirement on the Benefit's list.
            "coverage_requirements": _object(
                {r: {"type": "boolean"} for r in COVERAGE_REQUIREMENTS.get(benefit, ())}
            ),
            "coverage_window": _nullable(_TEXT),
            "threshold_hours": hours,
            "benefit_type": {"enum": [str(t) for t in BenefitType]},
            "step_hours": hours,
            "max_claims_per_period": _nullable({"type": "integer"}),
            "eligible_costs": _array(_TEXT, _MOST_COSTS),
            "cost_maximums": _nullable(_TEXT),
            "item": _ITEM,
        }
    )
    return _object({"conditions": _array(condition, _MOST_CONDITIONS), "exclusions": exclusions})


# Reading answers --------------------------------------------------------------------


def _extraction(answer: dict[str, Any]) -> Extraction:
    return Extraction(
        conditions=tuple(_condition(c) for c in answer.get("conditions", ())),
        exclusions=tuple(_exclusion(e) for e in answer.get("exclusions", ())),
        policy_period=answer.get("policy_period"),
    )


def _condition(answer: dict[str, Any]) -> ExtractedCondition:
    return ExtractedCondition(
        covered_event=answer["covered_event"],
        coverage_requirements=tuple(
            r for r, stated in answer["coverage_requirements"].items() if stated
        ),
        threshold_hours=answer["threshold_hours"],
        benefit_type=BenefitType(answer["benefit_type"]),
        step_hours=answer["step_hours"],
        max_claims_per_period=answer["max_claims_per_period"],
        label=answer["label"],
        coverage_window=answer["coverage_window"],
        eligible_costs=tuple(answer["eligible_costs"]),
        cost_maximums=answer["cost_maximums"],
        item=answer["item"],
    )


def _exclusion(answer: dict[str, Any]) -> ExtractedExclusion:
    return ExtractedExclusion(
        type=ExclusionType(answer["type"]),
        text=answer["text"],
        concerns_cause=answer["concerns_cause"],
        proviso=answer["proviso"],
        item=answer["item"],
    )


def _facts(answer: dict[str, Any]) -> ScenarioFacts:
    period = answer["policy_period"]
    start = _moment(period["start"], UNDATED) if period else None
    end = _moment(period["end"], UNDATED, end_of_day=True) if period else None
    return ScenarioFacts(
        benefits=tuple(Benefit(b) for b in answer["benefits"]),
        incidents=tuple(_incident(i) for i in answer["incidents"]),
        cause=answer["cause"],
        purchased_at=_moment(answer["purchased_at"], UNDATED),
        policy_period=(start, end) if start is not None and end is not None else None,
        within_policy_period=answer["within_policy_period"],
        in_force_at_purchase=tuple(answer["in_force_at_purchase"]),
        earlier_claims=answer["earlier_claims"],
    )


def _incident(answer: dict[str, Any]) -> Incident:
    # Undated times count their days from the booked flight's day.
    scheduled = answer["scheduled_departure"]
    day = date.fromisoformat(scheduled["date"]) if scheduled and scheduled["date"] else UNDATED
    minutes = answer["stated_delay_minutes"]
    return Incident(
        leg=_optional(Leg, answer["leg"]),
        airport=answer["airport"],
        transport=answer["transport"],
        scheduled_departure=_moment(scheduled, day),
        actual_departure=_moment(answer["actual_departure"], day),
        cancelled=answer["cancelled"],
        replacements=tuple(
            Replacement(
                departure=_moment(r["departure"], day),
                arranged_by=_optional(ArrangedBy, r["arranged_by"]),
                taken=r["taken"],
                arranged_at=_moment(r["arranged_at"], day),
                destination=r["destination"],
                returns_to_taiwan=r["returns_to_taiwan"],
            )
            for r in answer["replacements"]
        ),
        missed_connection=answer["missed_connection"],
        stated_delay=None if minutes is None else timedelta(minutes=minutes),
    )


def _moment(
    answer: dict[str, Any] | None, day: date, *, end_of_day: bool = False
) -> datetime | None:
    """A time, in Taiwan time. A day without a time of day is taken whole: from its
    start, or to its last minute for the end of a period."""
    if answer is None:
        return None
    if answer["date"] is None and answer["time"] is None:
        return None
    on = date.fromisoformat(answer["date"]) if answer["date"] else day + timedelta(answer["day"])
    if answer["time"] is not None:
        at = time.fromisoformat(answer["time"])
    else:
        at = time(23, 59) if end_of_day else time(0, 0)
    return datetime.combine(on, at, TAIPEI)


def _optional[E: (Leg, ArrangedBy)](kind: type[E], value: str | None) -> E | None:
    return None if value is None else kind(value)


def _judgement(answer: dict[str, Any]) -> Judgement:
    match answer["answer"]:
        case "applies" | "within":
            return Settled(met=True)
        case "does not apply" | "outside":
            return Settled(met=False)
        case "needs a fact":
            return NeedsFact(answer["fact"])
        case "not settled":
            return NotSettled(answer["unaddressed"])
        case "turns on the Cause":
            return TurnsOnCause(tuple(Reading(r["cause"], r["met"]) for r in answer["readings"]))
    raise ValueError(f"not an answer: {answer['answer']}")
