"""List policies: the policies a clause document contains, found by heading rules.

Fixtures are page text captured from the PDF reader (scripts/capture_fixture.py),
trimmed by deleting whole lines. Every page separator is kept, so page numbers
match the original PDF.
"""

import re
from pathlib import Path

from travel_claims.app import list_policies
from travel_claims.policies import Clause, Policy, Wording

FIXTURES = Path(__file__).parent / "fixtures"


def clause(policy: Policy, number: int) -> Clause:
    return next(c for c in policy.clauses if c.number == number)


def test_a_policy_is_listed_with_its_name_pages_and_clause_numbers() -> None:
    policies = list_policies(FIXTURES / "shinkong-old-opening.txt")

    assert len(policies) == 1
    policy = policies[0]
    assert policy.name == "新光產物個人海外旅行不便綜合保險"
    assert policy.pages == (1, 1)
    assert policy.clause_numbers == (1, 2)


def test_a_new_policy_starts_where_clause_numbering_restarts() -> None:
    policies = list_policies(FIXTURES / "cathay-new-bundle-openings.txt")

    assert [(p.name, p.pages, p.clause_numbers) for p in policies] == [
        ("國泰產物享樂遊海外旅行綜合保險", (13, 19), (1, 2, 82)),
        ("國泰產物享暢行海外旅行綜合保險", (20, 20), (1, 2)),
    ]


def test_a_new_policy_starts_where_chapters_restart() -> None:
    # Trimmed so that 享暢行's first chapter opens with 第二條: only the chapter
    # numbering restarts.
    policies = list_policies(FIXTURES / "cathay-new-chapter-restart.txt")

    assert [(p.name, p.clause_numbers) for p in policies] == [
        ("國泰產物享樂遊海外旅行綜合保險", (1, 2, 82)),
        ("國泰產物享暢行海外旅行綜合保險", (2,)),
    ]
    assert policies[1].clauses[0].chapter == "第一章 共同條款"


def test_references_to_other_clauses_in_body_text_are_not_headings() -> None:
    hsiang_le_you, hsiang_chang_hsing = list_policies(FIXTURES / "cathay-new-cross-references.txt")

    clauses = {clause.number: clause for clause in hsiang_le_you.clauses}
    assert tuple(clauses) == (1, 3, 73, 74)
    assert "第二十條至二十四條規定及相關法令定之。" in clauses[3].text
    assert "第七十八條之急難事故時" in clauses[73].text
    # Headings written without a space after 條 are still headings.
    assert [(c.number, c.heading) for c in hsiang_chang_hsing.clauses] == [
        (1, "保險契約之構成"),
        (23, "特別不保事項"),
        (24, "理賠文件"),
        (25, "抗辯與訴訟"),
    ]


def test_running_footers_and_page_numbers_are_removed_from_clause_text() -> None:
    [shinkong] = list_policies(FIXTURES / "shinkong-old-flight-delay.txt")
    exclusions = clause(shinkong, 23)
    assert exclusions.pages == (1, 2)
    assert "保單條款" not in exclusions.text
    assert "三、被保險人抵達機場時，已逾其預定搭乘班機辦理登機之時間。\n四、" in exclusions.text
    assert shinkong.pages == (1, 2)

    [cathay] = list_policies(FIXTURES / "cathay-new-flight-delay.txt")
    delay = clause(cathay, 30)
    assert delay.pages == (15, 16)
    assert "15" not in delay.text


def test_a_running_footer_on_only_some_of_the_pages_is_removed() -> None:
    # As in a bundle where one policy prints its own footer: the footer is on
    # pages 1 to 3 only, while pages 4 to 8 carry other text.
    shinkong = list_policies(FIXTURES / "shinkong-old-footer-on-some-pages.txt")[0]

    assert "保單條款" not in clause(shinkong, 23).text


def test_spacing_around_full_width_punctuation_is_normalised() -> None:
    [cathay] = list_policies(FIXTURES / "cathay-new-flight-delay.txt")
    exclusions = clause(cathay, 31)

    assert "\n一、被保險人因本身事由而未搭乘預定之班機或錯過轉接班" in exclusions.text
    assert "\n二、要保人向本公司申請訂立保險契約時，" in exclusions.text


def test_the_wording_version_is_suggested_from_the_flight_delay_exclusions() -> None:
    # The new wording excludes a sea typhoon warning issued before purchase
    # and widens the strike exclusion to a right to strike already obtained.
    [cathay] = list_policies(FIXTURES / "cathay-new-flight-delay.txt")
    assert cathay.suggested_wording is Wording.NEW

    [shinkong] = list_policies(FIXTURES / "shinkong-old-flight-delay.txt")
    assert shinkong.suggested_wording is Wording.OLD

    [travel_accident] = list_policies(FIXTURES / "cathay-new-travel-accident.txt")
    assert travel_accident.name == "國泰產物新旅行平安保障保險"
    assert travel_accident.suggested_wording is None


def test_compatibility_ideographs_from_the_pdf_read_as_ordinary_characters() -> None:
    # Some PDFs encode characters such as 不 as CJK compatibility ideographs,
    # which look the same but do not match ordinary text.
    [chung_kuo] = list_policies(FIXTURES / "chungkuo-old-flight-delay.txt")

    assert chung_kuo.name == "兆豐產物新個人海外旅行不便保險"
    assert clause(chung_kuo, 21).heading == "特別不保事項"
    assert chung_kuo.suggested_wording is Wording.OLD


def test_headings_and_titles_broken_across_lines_are_recognised() -> None:
    travel_accident, medical = list_policies(FIXTURES / "cathay-new-broken-headings.txt")

    application = clause(travel_accident, 33)
    assert application.heading == "特定意外事故身故保險金或喪葬費用保險金的申領"
    assert application.text.startswith("受益人申領「特定意外事故身故保險金或喪葬費用保險金」時")
    assert medical.name == "國泰產物新旅行平安保障傷害醫療及重大燒燙傷保險"

    [rider] = list_policies(FIXTURES / "cathay-new-rider-title.txt")
    assert rider.name == "國泰產物享樂遊海外旅行綜合保險班機延誤取代或免檢附部分理賠文件附加條款"


def test_a_title_may_end_with_a_plan_type() -> None:
    _, comprehensive = list_policies(FIXTURES / "fubon-old-bundle-boundary.txt")

    assert comprehensive.name == "富邦產物安心個人旅行綜合保險-甲型"
    assert comprehensive.pages == (35, 35)


def test_a_notice_above_the_title_at_the_top_of_a_page_belongs_to_the_new_policy() -> None:
    # Page 35 opens with the next policy's filing number and complaints line,
    # printed above its title; the previous policy ends on page 34.
    inconvenience, _ = list_policies(FIXTURES / "fubon-old-bundle-boundary.txt")

    assert inconvenience.pages == (34, 34)
    assert (
        clause(inconvenience, 38).text
        == "被保險人向本公司申請理賠時，應檢具下列文件：\n一、理賠申請書。"
    )


def test_page_text_may_separate_pages_with_bare_form_feeds(tmp_path: Path) -> None:
    # pdftotext ends each page with a form feed and no line break.
    fixture = (FIXTURES / "cathay-new-flight-delay.txt").read_text(encoding="utf-8")
    document = tmp_path / "pages.txt"
    document.write_text("\f".join(re.split(r"\n?\f\n?", fixture)), encoding="utf-8")

    [cathay] = list_policies(document)

    assert cathay.pages == (13, 16)
    assert cathay.clause_numbers == (1, 30, 31, 32)
