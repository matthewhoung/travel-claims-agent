"""Build the Alignment table: the same benefit lined up across Products and Wording versions.

Each test imports 享樂遊 in the old and the new wording with scripted
extraction, confirms both workbooks, and builds the table from them. The new
wording is scripted with its widened strike exclusion and with baggage delay,
which is aligned but not judged; the old-wording fixture has no baggage Clauses.
"""

from pathlib import Path

import openpyxl
import pytest

from travel_claims.alignment import AlignmentRow, AlignmentTable, Column, Entry, RowKind
from travel_claims.app import (
    CannotAlign,
    build_alignment_table,
    export_alignment_table,
)
from travel_claims.clause_store import ClauseStore
from travel_claims.conditions import Benefit
from travel_claims.local_models import Extraction
from travel_claims.policies import Wording

from hsiang_le_you import (
    BAGGAGE_DELAY,
    EXTRACTIONS,
    FIRST_REPLACEMENT,
    OLD_STRIKE,
    PROVISO,
    RETURN_HOME,
    STRIKE,
    TYPHOON,
    WILFUL_ACT,
    cathay_century_flight_delay,
    confirm,
    enter_amounts,
    import_draft,
    review,
)
from scripted_models import ScriptedModels

NEW_EXTRACTIONS = EXTRACTIONS | {
    31: Extraction(exclusions=(TYPHOON, STRIKE, FIRST_REPLACEMENT)),
    36: Extraction(conditions=(BAGGAGE_DELAY,)),
    37: Extraction(exclusions=(RETURN_HOME,)),
}
OLD = Column("享樂遊", Wording.OLD)
NEW = Column("享樂遊", Wording.NEW)
CATHAY_SOURCE = "https://www.cathay-ins.com.tw/cathayins/personal/travel/oversea/"


def both_wordings(tmp_path: Path, *, confirmed: bool = True) -> tuple[Path, Path, ClauseStore]:
    """享樂遊 in the old and the new wording: the two workbooks and the Clause store."""
    old, store = import_draft(tmp_path, wording=Wording.OLD)
    new, _ = import_draft(tmp_path, ScriptedModels(extractions=NEW_EXTRACTIONS))
    if confirmed:
        confirm(old)
        confirm(new)
    return old, new, store


def row(table: AlignmentTable, benefit: Benefit | None, label: str) -> AlignmentRow:
    found = [r for r in table.rows if r.benefit == benefit and r.label == label]
    assert len(found) == 1, f"{len(found)} rows of {benefit} labelled {label}"
    return found[0]


def test_columns_are_each_product_in_each_wording_version(tmp_path: Path) -> None:
    old, new, store = both_wordings(tmp_path)

    table = build_alignment_table([new, old], store=store)

    assert table.columns == (OLD, NEW)


def test_the_old_and_new_strike_exclusions_share_one_row_with_their_own_texts(
    tmp_path: Path,
) -> None:
    old, new, store = both_wordings(tmp_path)

    table = build_alignment_table([old, new], store=store)

    assert row(table, Benefit.FLIGHT_DELAY, "strike at purchase") == AlignmentRow(
        benefit=Benefit.FLIGHT_DELAY,
        kind=RowKind.EXCLUSION,
        label="strike at purchase",
        cells=(
            (Entry(OLD_STRIKE.text, "第三十一條 二"),),
            (Entry(STRIKE.text, "第三十一條 三"),),
        ),
    )


def test_the_typhoon_exclusion_is_shown_as_absent_in_the_old_wording(tmp_path: Path) -> None:
    old, new, store = both_wordings(tmp_path)

    table = build_alignment_table([old, new], store=store)

    typhoon = row(table, Benefit.FLIGHT_DELAY, "typhoon warning at purchase")
    assert typhoon.cells == ((), (Entry(TYPHOON.text, "第三十一條 二"),))
    assert typhoon.shown()[0] == "absent"


def test_an_exclusion_is_shown_with_its_proviso(tmp_path: Path) -> None:
    old, new, store = both_wordings(tmp_path)

    table = build_alignment_table([old, new], store=store)

    assert row(table, Benefit.FLIGHT_DELAY, "first replacement not taken").cells == (
        (Entry(FIRST_REPLACEMENT.text + PROVISO, "第三十一條 四"),),
        (Entry(FIRST_REPLACEMENT.text + PROVISO, "第三十一條 五"),),
    )


def test_each_other_exclusion_gets_its_own_row_and_general_ones_apply_to_all_benefits(
    tmp_path: Path,
) -> None:
    old, new, store = both_wordings(tmp_path)

    table = build_alignment_table([old, new], store=store)

    general = [r for r in table.rows if r.benefit is None]
    assert general == [
        AlignmentRow(
            None, RowKind.OTHER_EXCLUSION, "other", ((Entry(WILFUL_ACT.text, "第四條 二"),), ())
        ),
        AlignmentRow(
            None, RowKind.OTHER_EXCLUSION, "other", ((), (Entry(WILFUL_ACT.text, "第四條 二"),))
        ),
    ]
    # Not matched to anything else, so not called absent.
    assert general[0].shown()[1] is None


def test_general_exclusions_of_a_type_line_up_on_one_row(tmp_path: Path) -> None:
    old, store = import_draft(tmp_path, wording=Wording.OLD)
    new, _ = import_draft(tmp_path)
    # The reviewer types the general wilful-act exclusion in both wordings.
    for workbook in (old, new):
        review(workbook, {"Exclusions!C2": "own reason or missed flight"})
        confirm(workbook)

    table = build_alignment_table([old, new], store=store)

    assert [r for r in table.rows if r.benefit is None] == [
        AlignmentRow(
            None,
            RowKind.EXCLUSION,
            "own reason or missed flight",
            ((Entry(WILFUL_ACT.text, "第四條 二"),), (Entry(WILFUL_ACT.text, "第四條 二"),)),
        )
    ]


def test_condition_parameters_line_up_by_benefit_and_parameter_each_citing_its_clause(
    tmp_path: Path,
) -> None:
    old, new, store = both_wordings(tmp_path)

    table = build_alignment_table([old, new], store=store)

    flight_delay = [r for r in table.rows if r.benefit is Benefit.FLIGHT_DELAY]
    assert [(r.kind, r.label) for r in flight_delay] == [
        (RowKind.PARAMETER, "Covered event"),
        (RowKind.PARAMETER, "Coverage requirements"),
        (RowKind.PARAMETER, "Coverage window"),
        (RowKind.PARAMETER, "Threshold (hours)"),
        (RowKind.PARAMETER, "Delay-period rule"),
        (RowKind.PARAMETER, "Benefit type"),
        (RowKind.PARAMETER, "Step (hours)"),
        (RowKind.PARAMETER, "Maximum claims per period"),
        (RowKind.AMOUNT, "Benefit amount"),
        (RowKind.EXCLUSION, "typhoon warning at purchase"),
        (RowKind.EXCLUSION, "strike at purchase"),
        (RowKind.EXCLUSION, "first replacement not taken"),
    ]
    assert row(table, Benefit.FLIGHT_DELAY, "Delay-period rule").cells == (
        (Entry("old-wording rule", "第三十條"),),
        (Entry("new-wording rule", "第三十條"),),
    )
    # Every entry cites its Clause; a published amount also gives its source.
    assert all(entry.cites for r in table.rows for cell in r.cells for entry in cell)


def test_alignment_only_benefits_appear_with_their_exclusion_types(tmp_path: Path) -> None:
    old, new, store = both_wordings(tmp_path)

    table = build_alignment_table([old, new], store=store)

    assert [r.benefit for r in table.rows if r.benefit is not None] == sorted(
        [r.benefit for r in table.rows if r.benefit is not None], key=list(Benefit).index
    )
    assert row(table, Benefit.BAGGAGE_DELAY, "Threshold (hours)").cells == (
        (),
        (Entry("6", "第三十六條"),),
    )
    assert row(table, Benefit.BAGGAGE_DELAY, "delay on return home").cells == (
        (),
        (Entry(RETURN_HOME.text, "第三十七條 二"),),
    )


def test_a_missing_amount_is_not_available_with_its_reason_and_never_borrowed(
    tmp_path: Path,
) -> None:
    old, new, store = both_wordings(tmp_path)
    # The new wording's amounts are published; the old wording's are not collected.
    enter_amounts(new, cathay_century_flight_delay())

    table = build_alignment_table([old, new], store=store)

    assert row(table, Benefit.FLIGHT_DELAY, "Benefit amount").cells == (
        (Entry("not available: not collected", "第三十條"),),
        (
            Entry(
                "安心型(T5): NT$6,000 per step, at most NT$12,000 per incident",
                "第三十條",
                CATHAY_SOURCE,
            ),
            Entry(
                "海外豪華型(U3): NT$6,000 per step, at most NT$12,000 per incident",
                "第三十條",
                CATHAY_SOURCE,
            ),
        ),
    )


def test_amounts_not_published_are_shown_with_their_reason_per_plan_or_for_all(
    tmp_path: Path,
) -> None:
    old, new, store = both_wordings(tmp_path)
    enter_amounts(old, [("all", None, "not published", None, None, None)])
    enter_amounts(
        new,
        [
            ("baggage delay", "安心型(T5)", "published", 6000, None, CATHAY_SOURCE),
            ("baggage delay", "團體型", "not published", None, None, None),
        ],
    )

    table = build_alignment_table([old, new], store=store)

    assert row(table, Benefit.FLIGHT_DELAY, "Benefit amount").cells == (
        (Entry("not available: not published", "第三十條"),),
        (Entry("not available: not collected", "第三十條"),),
    )
    assert row(table, Benefit.BAGGAGE_DELAY, "Benefit amount").cells == (
        (),
        (
            Entry("安心型(T5): NT$6,000", "第三十六條", CATHAY_SOURCE),
            Entry("團體型: not available: not published", "第三十六條"),
        ),
    )


def test_the_same_workbooks_always_give_an_identical_table(tmp_path: Path) -> None:
    old, new, store = both_wordings(tmp_path)
    enter_amounts(new, cathay_century_flight_delay())

    first = build_alignment_table([old, new], store=store)
    again = build_alignment_table([new, old], store=store)
    export_alignment_table(first, tmp_path / "first.xlsx")
    export_alignment_table(again, tmp_path / "again.xlsx")

    assert first == again
    assert rows(tmp_path / "first.xlsx") == rows(tmp_path / "again.xlsx")


def test_a_workbook_with_problems_is_refused(tmp_path: Path) -> None:
    old, new, store = both_wordings(tmp_path, confirmed=False)
    confirm(old)

    with pytest.raises(CannotAlign) as refused:
        build_alignment_table([old, new], store=store)

    assert [str(p) for p in refused.value.problems[new]] == [
        "Conditions!B1: Confirmed by is missing",
        "Conditions!B2: Confirmed on is missing",
    ]
    assert old not in refused.value.problems


def rows(path: Path) -> list[tuple[object, ...]]:
    book = openpyxl.load_workbook(path)
    return [tuple(r) for r in book["Alignment table"].iter_rows(values_only=True)]


def test_the_alignment_table_exports_to_excel_with_each_cells_citations(tmp_path: Path) -> None:
    old, new, store = both_wordings(tmp_path)
    table = build_alignment_table([old, new], store=store)
    exported = tmp_path / "alignment.xlsx"

    export_alignment_table(table, exported)

    exported_rows = rows(exported)
    assert exported_rows[0] == (
        "Benefit",
        "Row",
        "享樂遊 (old wording)",
        "Cites",
        "享樂遊 (new wording)",
        "Cites",
    )
    assert (
        "flight delay",
        "typhoon warning at purchase",
        "absent",
        None,
        TYPHOON.text,
        "第三十一條 二",
    ) in (exported_rows)
    assert ("all Benefits", "other", WILFUL_ACT.text, "第四條 二", None, None) in exported_rows
    with pytest.raises(FileExistsError):
        export_alignment_table(table, exported)
