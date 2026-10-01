"""A scripted fake of the local-models port, the one substitution point in tests."""

from collections.abc import Mapping, Sequence

from travel_claims.local_models import (
    Extraction,
    ExtractionRequest,
    Judgement,
    JudgementRequest,
    ScenarioFacts,
)
from travel_claims.policies import Clause, Wording


class ScriptedModels:
    """Answers with what the test scripted, and records what it was asked.

    Extraction returns the Extraction scripted for a Clause number, and nothing
    for any other Clause. Judgements are scripted by the provision's Clause
    reference, as in 第三十一條 二. Indexing does nothing.
    """

    def __init__(
        self,
        *,
        extractions: Mapping[int, Extraction] | None = None,
        facts: ScenarioFacts | None = None,
        judgements: Mapping[str, Judgement] | None = None,
        related: Sequence[int] = (),
    ) -> None:
        self._extractions = dict(extractions or {})
        self._facts = facts
        self._judgements = dict(judgements or {})
        self._related = tuple(related)
        self.extracted: list[ExtractionRequest] = []
        self.indexed: list[tuple[str, Wording, tuple[int, ...]]] = []

    def extract(self, request: ExtractionRequest) -> Extraction:
        self.extracted.append(request)
        return self._extractions.get(request.clause.number, Extraction())

    def extract_facts(self, scenario: str) -> ScenarioFacts:
        if self._facts is None:
            raise AssertionError("the test scripted no Scenario facts")
        return self._facts

    def judge(self, request: JudgementRequest) -> Judgement:
        reference = str(request.provision.clause)
        if reference not in self._judgements:
            raise AssertionError(f"the test scripted no judgement for {reference}")
        return self._judgements[reference]

    def index(self, product: str, wording: Wording, clauses: Sequence[Clause]) -> None:
        self.indexed.append((product, wording, tuple(clause.number for clause in clauses)))

    def find_related(self, product: str, wording: Wording, facts: ScenarioFacts) -> tuple[int, ...]:
        return self._related
