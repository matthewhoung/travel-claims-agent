"""The command line: a thin shell over the application interface."""

from datetime import date
from pathlib import Path

import openpyxl
import pytest

from travel_claims.cli import main

import hsiang_le_you
from scripted_models import ScriptedModels

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


def test_import_writes_a_draft_workbook_and_says_how_to_confirm_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workbook = tmp_path / "享樂遊.new.xlsx"
    store = tmp_path / "store"

    main(
        [
            "import",
            str(hsiang_le_you.FIXTURE),
            "--product=享樂遊",
            "--wording=new",
            f"--workbook={workbook}",
            f"--store={store}",
        ],
        models=ScriptedModels(extractions=hsiang_le_you.EXTRACTIONS),
    )

    assert capsys.readouterr().out == (
        "Imported 國泰產物享樂遊海外旅行綜合保險 (pages 13–16) as 享樂遊, new wording.\n"
        "Stored 10 Clauses. Extracted 1 Condition and 3 exclusions into the draft workbook\n"
        f"{workbook}\n"
        "Review it in Excel, and record who confirmed it and when above the Conditions table.\n"
        "Then check it with:\n"
        f"travel-claims load {workbook} --store={store}\n"
    )
    assert workbook.is_file()


def test_load_lists_every_problem_and_the_fields_changed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workbook, store = hsiang_le_you.import_draft(tmp_path)
    load = ["load", str(workbook), f"--store={store.directory}"]

    with pytest.raises(SystemExit) as exit:
        main(load)

    assert exit.value.code == 1
    assert capsys.readouterr().out == (
        "2 problems:\n"
        "Conditions!B1: Confirmed by is missing\n"
        "Conditions!B2: Confirmed on is missing\n"
        "32 fields extracted, 0 changed by the reviewer.\n"
    )

    book = openpyxl.load_workbook(workbook)
    book["Conditions"]["B1"] = "王小明"
    book["Conditions"]["B2"] = date(2026, 10, 1)
    book["Conditions"]["H5"] = 6
    book.save(workbook)
    main(load)

    assert capsys.readouterr().out == (
        "No problems. 享樂遊, new wording: 1 Condition and 3 exclusions,"
        " confirmed by 王小明 on 2026-10-01.\n"
        "32 fields extracted, 1 changed by the reviewer.\n"
    )


def test_import_points_out_a_new_product_name_beside_those_already_stored(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "store"

    def import_as(product: str, wording: str) -> str:
        main(
            [
                "import",
                str(hsiang_le_you.FIXTURE),
                f"--product={product}",
                f"--wording={wording}",
                f"--workbook={tmp_path / f'{product}.{wording}.xlsx'}",
                f"--store={store}",
            ],
            models=ScriptedModels(),
        )
        return capsys.readouterr().out

    first = import_as("享樂遊", "new")
    misspelt = import_as("享樂游", "old")
    same_product = import_as("享樂遊", "old")

    assert "new Product" not in first
    assert (
        "Note: 享樂游 is a new Product. The Clause store already holds 享樂遊; to import"
        " another Wording version of a Product, give its name exactly.\n"
    ) in misspelt
    assert "new Product" not in same_product
