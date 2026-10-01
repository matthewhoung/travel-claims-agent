"""What List policies finds in a clause document."""

from dataclasses import dataclass
from enum import StrEnum


class Wording(StrEnum):
    """Which edition of the regulator's reference clauses a text follows."""

    OLD = "old"  # in force from 2022-09-01
    NEW = "new"  # in force from 2026-04-01


@dataclass(frozen=True)
class Clause:
    """A numbered Clause (條), such as 第三十條, with its text."""

    number: int
    heading: str
    chapter: str | None
    text: str
    pages: tuple[int, int]


@dataclass(frozen=True)
class Policy:
    """A policy found in a clause document: a candidate for import as a Product.

    One document can hold several policies, each with its own Clause numbering.
    """

    name: str | None
    pages: tuple[int, int]
    # From the flight-delay exclusions; None when the policy has none. A
    # person confirms the Wording version at import.
    suggested_wording: Wording | None
    clauses: tuple[Clause, ...]

    @property
    def clause_numbers(self) -> tuple[int, ...]:
        return tuple(clause.number for clause in self.clauses)
