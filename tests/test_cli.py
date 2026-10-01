"""The command line: a thin shell over the application interface."""

from pathlib import Path

import pytest

from travel_claims.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_list_policies_prints_each_policy_with_its_pages_wording_and_clauses(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["list-policies", str(FIXTURES / "cathay-new-flight-delay.txt")])

    assert capsys.readouterr().out == (
        "1. 國泰產物享樂遊海外旅行綜合保險\n"
        "   pages 13–16, suggested wording: new\n"
        "   4 Clauses: 第一條, 第三十條–第三十二條\n"
    )


def test_list_policies_says_when_no_title_or_wording_was_found(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["list-policies", str(FIXTURES / "fubon-old-bundle-boundary.txt")])

    assert capsys.readouterr().out == (
        "1. (no title found)\n"
        "   page 34, no suggested wording (no flight-delay exclusions)\n"
        "   1 Clause: 第三十八條\n"
        "2. 富邦產物安心個人旅行綜合保險-甲型\n"
        "   page 35, no suggested wording (no flight-delay exclusions)\n"
        "   1 Clause: 第一條\n"
    )
