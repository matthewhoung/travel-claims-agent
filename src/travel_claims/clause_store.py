"""The local Clause store: the Clauses of every imported Product, per Wording version.

A Clause is identified by its Product, its Wording version and its number
together, so numbers that restart inside a bundle or repeat across Wording
versions never collide. Clause references in a workbook are checked against
the store, and judging reads Clause text from it.
"""

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from os import PathLike
from pathlib import Path

from travel_claims.policies import Clause, Wording

_SCHEMA = """
CREATE TABLE IF NOT EXISTS clauses (
    product TEXT NOT NULL,
    wording TEXT NOT NULL,
    number INTEGER NOT NULL,
    chapter TEXT,
    heading TEXT NOT NULL,
    text TEXT NOT NULL,
    first_page INTEGER NOT NULL,
    last_page INTEGER NOT NULL,
    PRIMARY KEY (product, wording, number)
)
"""


class ClauseStore:
    """A SQLite file in a directory on this machine."""

    def __init__(self, directory: str | PathLike[str]) -> None:
        self.directory = Path(directory)

    def replace(self, product: str, wording: Wording, clauses: Sequence[Clause]) -> None:
        """Store the Clauses of a Product in a Wording version, in place of any stored before."""
        with self._connection() as db, db:
            db.execute("DELETE FROM clauses WHERE product = ? AND wording = ?", (product, wording))
            db.executemany(
                "INSERT INTO clauses VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (product, wording, c.number, c.chapter, c.heading, c.text, *c.pages)
                    for c in clauses
                ],
            )

    def clauses(self, product: str, wording: Wording) -> list[Clause]:
        """The stored Clauses of a Product in a Wording version, in Clause order."""
        with self._connection() as db:
            rows = db.execute(
                "SELECT number, heading, chapter, text, first_page, last_page FROM clauses"
                " WHERE product = ? AND wording = ? ORDER BY number",
                (product, wording),
            ).fetchall()
        return [
            Clause(number, heading, chapter, text, (first, last))
            for number, heading, chapter, text, first, last in rows
        ]

    def products(self) -> list[str]:
        """The names of the Products stored, in any Wording version."""
        with self._connection() as db:
            return [
                name for (name,) in db.execute("SELECT DISTINCT product FROM clauses ORDER BY 1")
            ]

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.directory.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.directory / "clauses.sqlite")) as db:
            db.execute(_SCHEMA)
            yield db
