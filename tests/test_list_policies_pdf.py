"""List policies on the full clause PDFs, including two-column reading order.

The PDFs are not in the repository (data/SOURCES.md lists where each comes
from), so these tests run only when they are present locally.
"""

import re
from functools import cache
from pathlib import Path

import pytest

from travel_claims.app import list_policies
from travel_claims.pdf import read_pages
from travel_claims.policies import Clause, Policy, Wording

CLAUSES = Path(__file__).parents[1] / "data" / "clauses"
CATHAY_NEW = CLAUSES / "cathay" / "travel-bundle.new-wording.pdf"
CATHAY_OLD = CLAUSES / "cathay" / "travel-bundle.old-wording.pdf"
FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_SOURCES = {
    "cathay-new-": "cathay/travel-bundle.new-wording.pdf",
    "cathay-old-": "cathay/travel-bundle.old-wording.pdf",
    "chungkuo-old-": "chungkuo/overseas-inconvenience.old-wording.pdf",
    "fubon-old-": "fubon/travel-bundle.old-wording.pdf",
    "shinkong-old-": "shinkong/overseas-inconvenience.old-wording.pdf",
}


@cache
def policies_in(path: Path) -> list[Policy]:
    return list_policies(path)


@cache
def pages_of(path: Path) -> list[str]:
    return read_pages(path)


def present(path: Path) -> Path:
    if not path.exists():
        pytest.skip(f"{path.relative_to(CLAUSES.parent)} is not present; see data/SOURCES.md")
    return path


def policy_named(path: Path, name: str) -> Policy:
    return next(p for p in policies_in(present(path)) if p.name == name)


def clause(policy: Policy, number: int) -> Clause:
    return next(c for c in policy.clauses if c.number == number)


def test_the_cathay_new_bundle_lists_hsiang_le_you_and_hsiang_chang_hsing_apart() -> None:
    hsiang_le_you = policy_named(CATHAY_NEW, "國泰產物享樂遊海外旅行綜合保險")
    hsiang_chang_hsing = policy_named(CATHAY_NEW, "國泰產物享暢行海外旅行綜合保險")

    assert hsiang_le_you.pages == (13, 19)
    assert hsiang_chang_hsing.pages == (20, 26)
    assert clause(hsiang_le_you, 30).heading == "班機延誤保險(定額給付-累進式)承保範圍"
    assert clause(hsiang_chang_hsing, 30).heading == "班機延誤保險(實支實付)承保範圍"
    assert hsiang_le_you.suggested_wording is Wording.NEW
    assert hsiang_chang_hsing.suggested_wording is Wording.NEW


def test_a_clause_running_from_the_left_column_into_the_right_is_whole_and_in_order() -> None:
    # On page 16, 第三十三條 fills the bottom of the left column and ends at the
    # top of the right column, above 第三十四條.
    hsiang_le_you = policy_named(CATHAY_NEW, "國泰產物享樂遊海外旅行綜合保險")
    trip_change = clause(hsiang_le_you, 33)

    assert trip_change.text.startswith("被保險人於海外旅行期間內，因下列事故致被保險人必須更")
    assert re.search(r"合計新臺幣\s*2,000\s*元為限。\s*前二項所列費用僅限於", trip_change.text)
    assert trip_change.text.endswith("保險金額為\n限。")
    assert clause(hsiang_le_you, 34).heading.endswith("特別不保事項")


def test_the_cathay_old_bundle_lists_each_policy_and_rider_and_not_its_contents_page() -> None:
    policies = policies_in(present(CATHAY_OLD))

    travel_accident = "國泰產物新旅行平安保障保險"
    medical = "國泰產物新旅行平安保障傷害醫療及重大燒燙傷保險"
    hsiang_le_you = "國泰產物享樂遊海外旅行綜合保險"
    assert [(p.name, p.pages, p.parents if p.is_rider else None) for p in policies] == [
        (travel_accident, (2, 18), None),
        (medical, (19, 24), None),
        (f"{travel_accident}恐怖主義行為保險給付附加條款", (25, 25), (travel_accident,)),
        # The 附約 names its parents in its first Clause: 附加於…或…
        ("國泰產物新海外突發疾病醫療健康保險附約 (甲型)", (26, 30), (travel_accident, medical)),
        ("國泰產物新海外突發疾病醫療健康保險附約 (乙型)", (32, 36), (travel_accident, medical)),
        (hsiang_le_you, (37, 54), None),
        (f"{hsiang_le_you}寵物寄宿延長補償保險金附加條款", (55, 56), (hsiang_le_you,)),
        ("國泰產物傷害保險恐怖主義行為保險限額給付附加條款", (57, 58), ()),
        (f"{hsiang_le_you}班機延誤取代或免檢附部分理賠文件附加條款", (59, 59), (hsiang_le_you,)),
    ]


@pytest.mark.parametrize(
    ("document", "name", "pages", "wording"),
    [
        (
            "cathay/travel-bundle.old-wording.pdf",
            "國泰產物享樂遊海外旅行綜合保險",
            (37, 54),
            Wording.OLD,
        ),
        (
            "fubon/overseas-inconvenience.new-wording.pdf",
            "富邦產物個人海外旅行不便保險",
            (1, 12),
            Wording.NEW,
        ),
        (
            "fubon/travel-bundle.old-wording.pdf",
            "富邦產物個人海外旅行不便保險",
            (24, 34),
            Wording.OLD,
        ),
        (
            "shinkong/inconvenience-online.new-wording.pdf",
            "新光產物個人海外旅行不便綜合保險(A)",
            (1, 3),
            Wording.NEW,
        ),
        (
            "shinkong/travel-comprehensive-overseas.new-wording.pdf",
            "新光產物個人海外旅行不便綜合保險(A)",
            (1, 3),
            Wording.NEW,
        ),
        (
            "shinkong/overseas-inconvenience.old-wording.pdf",
            "新光產物個人海外旅行不便綜合保險",
            (1, 3),
            Wording.OLD,
        ),
    ],
)
def test_each_product_in_the_proof_of_concept_is_listed_with_its_wording(
    document: str, name: str, pages: tuple[int, int], wording: Wording
) -> None:
    policy = policy_named(CLAUSES / document, name)

    assert policy.pages == pages
    assert policy.suggested_wording is wording


@pytest.mark.parametrize("fixture", sorted(FIXTURES.glob("*.txt")), ids=lambda path: path.name)
def test_each_fixture_is_an_excerpt_of_what_the_reader_makes_of_its_pdf(fixture: Path) -> None:
    # This checks the fixtures, not the code: spec #1 asks for fixtures captured
    # from the PDF reader's own output, so it compares them with read_pages,
    # the reader that List policies and scripts/capture_fixture.py both use.
    # Fixtures are trimmed by deleting whole lines only. If the reader changes,
    # recapture them.
    source = next(pdf for prefix, pdf in FIXTURE_SOURCES.items() if fixture.name.startswith(prefix))
    read = pages_of(present(CLAUSES / source))
    excerpt = fixture.read_text(encoding="utf-8").split("\f")

    assert len(excerpt) == len(read)
    for kept, page in zip(excerpt, read, strict=True):
        remaining = iter(page.split("\n"))
        assert all(line in remaining for line in kept.strip("\n").split("\n") if line)
