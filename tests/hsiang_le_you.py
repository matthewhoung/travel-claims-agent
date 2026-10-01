"""享樂遊 in the new wording, as the tests import it.

The fixture holds its general provisions and its flight-delay Clauses,
captured from the new-wording bundle. The local models are scripted to
extract the flight-delay Condition, two of its exclusions and one general
exclusion.
"""

from datetime import date
from pathlib import Path

import openpyxl

from travel_claims.app import import_product
from travel_claims.clause_store import ClauseStore
from travel_claims.conditions import BenefitType, ExclusionType
from travel_claims.local_models import ExtractedCondition, ExtractedExclusion, Extraction
from travel_claims.policies import Wording

from scripted_models import ScriptedModels

FIXTURE = Path(__file__).parent / "fixtures" / "cathay-new-general-provisions.txt"

FLIGHT_DELAY = ExtractedCondition(
    covered_event="scheduled flight departs 4 hours or more late",
    coverage_requirements=("scheduled flight", "as a passenger"),
    threshold_hours=4,
    benefit_type=BenefitType.PROGRESSIVE,
    step_hours=4,
    max_claims_per_period=2,
)
TYPHOON = ExtractedExclusion(
    type=ExclusionType.TYPHOON_WARNING,
    text="要保人向本公司申請訂立保險契約時，中華民國政府氣象機構已發布海上颱風警報。",
    concerns_cause=False,
    item="二",
)
FIRST_REPLACEMENT = ExtractedExclusion(
    type=ExclusionType.FIRST_REPLACEMENT_NOT_TAKEN,
    text="被保險人未搭乘航空業者所提供之第一班替代交通工具。",
    concerns_cause=True,
    proviso="但被保險人因不可抗力因素致無法搭乘航空業者所提供之第一班替代交通工具者，不在此限。",
    item="五",
)
WILFUL_ACT = ExtractedExclusion(
    type=ExclusionType.OTHER, text="被保險人故意行為。", concerns_cause=True, item="二"
)

EXTRACTIONS = {
    4: Extraction(exclusions=(WILFUL_ACT,)),
    5: Extraction(policy_period="the dates and times on the policy schedule"),
    30: Extraction(conditions=(FLIGHT_DELAY,)),
    31: Extraction(exclusions=(TYPHOON, FIRST_REPLACEMENT)),
}


def import_draft(directory: Path, models: ScriptedModels | None = None) -> tuple[Path, ClauseStore]:
    """Import 享樂遊 in the new wording; the draft workbook and the Clause store.

    Extraction answers with EXTRACTIONS unless `models` is given.
    """
    workbook = directory / "享樂遊.new.xlsx"
    store = ClauseStore(directory / "store")
    import_product(
        FIXTURE,
        product="享樂遊",
        wording=Wording.NEW,
        workbook=workbook,
        store=store,
        models=models or ScriptedModels(extractions=EXTRACTIONS),
    )
    return workbook, store


def review(workbook: Path, edits: dict[str, str | float | date | None]) -> None:
    """Edit cells as the reviewer does in Excel, such as {"Conditions!H5": 6}."""
    book = openpyxl.load_workbook(workbook)
    for reference, value in edits.items():
        sheet, cell = reference.split("!")
        book[sheet][cell] = value
    book.save(workbook)


def confirm(workbook: Path, by: str = "王小明", on: date = date(2026, 10, 1)) -> None:
    """Record who confirmed the workbook and when, above the Conditions table."""
    review(workbook, {"Conditions!B1": by, "Conditions!B2": on})
