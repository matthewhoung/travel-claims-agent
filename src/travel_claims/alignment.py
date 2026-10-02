"""The Alignment table: the same benefit lined up across Products and Wording versions.

Code builds it from confirmed condition tables, with no model involved, so
the same workbooks always give the same table. Rows are grouped by Benefit:
its Condition parameters, matched by parameter; its Benefit amounts per Plan;
and its exclusions, matched by exclusion type. Each "other" exclusion gets a
row of its own, and the general exclusions, which apply to every Benefit,
come last.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from travel_claims.conditions import (
    ALL,
    EXCLUSION_TYPES,
    Amount,
    Availability,
    Benefit,
    BenefitType,
    Condition,
    Exclusion,
    ExclusionType,
    nt_dollars,
)
from travel_claims.loading import ConditionTable
from travel_claims.policies import Wording
from travel_claims.workbook import CONDITION_COLUMNS, condition_row

# The Condition parameters lined up, in the Conditions sheet's order.
PARAMETERS = tuple(
    heading
    for heading in CONDITION_COLUMNS
    if heading not in ("Condition key", "Product", "Wording version", "Benefit", "Clause reference")
)
BENEFIT_AMOUNT = "Benefit amount"
ABSENT = "absent"


class RowKind(StrEnum):
    PARAMETER = "parameter"
    AMOUNT = "Benefit amount"
    EXCLUSION = "exclusion"
    # An "other" exclusion, which is matched to nothing in other columns.
    OTHER_EXCLUSION = "other exclusion"


@dataclass(frozen=True, order=True)
class Column:
    """One Product in one Wording version."""

    product: str
    wording: Wording

    def __str__(self) -> str:
        return f"{self.product} ({self.wording} wording)"


@dataclass(frozen=True)
class Entry:
    text: str
    # The Clause it rests on, such as 第三十一條 二.
    cites: str
    # Where a published amount comes from.
    source: str | None = None

    def citation(self) -> str:
        """The Clause, and for a published amount its source too."""
        return f"{self.cites}; source: {self.source}" if self.source else self.cites


@dataclass(frozen=True)
class AlignmentRow:
    # None for the general exclusions, which apply to every Benefit.
    benefit: Benefit | None
    kind: RowKind
    # The parameter, the exclusion type, or Benefit amount.
    label: str
    # One per column. A column with several Conditions of the Benefit has an
    # entry for each, named by its Condition key.
    cells: tuple[tuple[Entry, ...], ...]

    def shown(self) -> tuple[str | None, ...]:
        """Each cell's text: an empty cell is absent, except in an "other" exclusion's row,
        which is matched to nothing in other columns."""
        empty = None if self.kind is RowKind.OTHER_EXCLUSION else ABSENT
        return tuple("\n".join(e.text for e in cell) if cell else empty for cell in self.cells)


@dataclass(frozen=True)
class AlignmentTable:
    columns: tuple[Column, ...]
    rows: tuple[AlignmentRow, ...]


def align(tables: Sequence[ConditionTable]) -> AlignmentTable:
    """Line up confirmed condition tables, one column each, ordered by Product and then
    Wording version, old before new."""
    ordered = sorted(tables, key=lambda t: (t.product, list(Wording).index(t.wording)))
    columns = tuple(Column(t.product, t.wording) for t in ordered)
    rows: list[AlignmentRow] = []
    for benefit in Benefit:
        conditions = [[c for c in t.conditions if c.benefit is benefit] for t in ordered]
        if any(conditions):
            rows += _parameters(benefit, conditions)
            rows.append(_amounts(benefit, ordered, conditions))
            rows += _exclusions(benefit, [_applying(t, benefit) for t in ordered])
    rows += _exclusions(None, [[e for e in t.exclusions if ALL in e.applies_to] for t in ordered])
    return AlignmentTable(columns, tuple(rows))


def _parameters(benefit: Benefit, conditions: list[list[Condition]]) -> list[AlignmentRow]:
    """A row per parameter that any column states, each value citing its Condition's Clause."""
    rows = []
    for heading in PARAMETERS:
        values = [[(c, condition_row(c)[heading]) for c in column] for column in conditions]
        if all(value is None for column in values for _, value in column):
            continue
        cells = tuple(
            tuple(
                Entry(
                    _named(c, len(column) > 1, "not stated" if value is None else str(value)),
                    str(c.clause),
                )
                for c, value in column
            )
            for column in values
        )
        rows.append(AlignmentRow(benefit, RowKind.PARAMETER, heading, cells))
    return rows


def _amounts(
    benefit: Benefit, tables: list[ConditionTable], conditions: list[list[Condition]]
) -> AlignmentRow:
    """Each Condition's amounts per Plan, from its own workbook only.

    Each cites the Condition's Clause; a published amount also gives its
    source, and one that is not available says why.
    """
    cells = tuple(
        tuple(_amount(c, amount, len(column) > 1) for c in column for amount in table.amounts_of(c))
        for table, column in zip(tables, conditions, strict=True)
    )
    return AlignmentRow(benefit, RowKind.AMOUNT, BENEFIT_AMOUNT, cells)


def _amount(condition: Condition, amount: Amount, several: bool) -> Entry:
    plan = f"{amount.plan}: " if amount.plan else ""
    if amount.availability is not Availability.PUBLISHED:
        text = f"{plan}not available: {amount.availability}"
        return Entry(_named(condition, several, text), str(condition.clause))
    # Load requires them of a published amount.
    assert amount.benefit_amount is not None and amount.source
    paid = nt_dollars(amount.benefit_amount)
    if condition.benefit_type is BenefitType.PROGRESSIVE:
        paid += " per step"
    elif condition.benefit_type is BenefitType.REIMBURSEMENT:
        paid = f"limit {paid}"
    if amount.max_per_incident is not None:
        paid += f", at most {nt_dollars(amount.max_per_incident)} per incident"
    return Entry(_named(condition, several, plan + paid), str(condition.clause), amount.source)


def _applying(table: ConditionTable, benefit: Benefit) -> list[Exclusion]:
    """The exclusions of a table that apply to a Condition of the Benefit, but not to all."""
    return [
        e
        for e in table.exclusions
        if ALL not in e.applies_to
        and any(e.applies_to_condition(c) for c in table.conditions if c.benefit is benefit)
    ]


def _exclusions(benefit: Benefit | None, exclusions: list[list[Exclusion]]) -> list[AlignmentRow]:
    """A row per exclusion type that any column has, in the Benefit's list order; then a
    row per "other" exclusion. A None Benefit is the general exclusions."""
    listed = EXCLUSION_TYPES.get(benefit, ()) if benefit is not None else ()
    found = {e.type for column in exclusions for e in column} - {ExclusionType.OTHER}
    types = [*listed, *(t for t in ExclusionType if t in found and t not in listed)]
    rows = []
    for exclusion_type in types:
        if exclusion_type not in found:
            continue
        cells = tuple(
            tuple(_exclusion(e) for e in column if e.type is exclusion_type)
            for column in exclusions
        )
        rows.append(AlignmentRow(benefit, RowKind.EXCLUSION, str(exclusion_type), cells))
    others = [[e for e in column if e.type is ExclusionType.OTHER] for column in exclusions]
    return rows + _others(benefit, others)


def _others(benefit: Benefit | None, exclusions: list[list[Exclusion]]) -> list[AlignmentRow]:
    """A row of its own for each exclusion: column by column, in Clause order."""
    rows = []
    for index, column in enumerate(exclusions):
        for e in sorted(column, key=lambda e: (e.clause.number, e.clause.item or "", e.text)):
            cells = tuple((_exclusion(e),) if i == index else () for i in range(len(exclusions)))
            rows.append(AlignmentRow(benefit, RowKind.OTHER_EXCLUSION, str(e.type), cells))
    return rows


def _exclusion(e: Exclusion) -> Entry:
    return Entry(e.text + (e.proviso or ""), str(e.clause))


def _named(condition: Condition, several: bool, text: str) -> str:
    """The text, named by its Condition key when its column has several Conditions."""
    return f"{condition.key}: {text}" if several else text
