"""The application interface. The command line and the web page are thin shells over it."""

from collections.abc import Sequence
from dataclasses import dataclass
from os import PathLike
from pathlib import Path

from travel_claims.clause_store import ClauseStore
from travel_claims.extraction import draft_table
from travel_claims.judging import VerdictMatrix, judge
from travel_claims.loading import ConditionTable, Loaded, Problem, load
from travel_claims.local_models import LocalModels
from travel_claims.pdf import read_pages
from travel_claims.policies import Policy, Wording
from travel_claims.splitter import split_policies
from travel_claims.workbook import write_draft


class CannotImport(Exception):
    """The document, the choice of policy or the workbook named does not allow an import."""


class CannotJudge(Exception):
    """A workbook given has problems, so no Verdict is given from it (ADR 0001)."""

    def __init__(self, problems: dict[Path, tuple[Problem, ...]]) -> None:
        self.problems = problems
        count = sum(len(found) for found in problems.values())
        super().__init__(
            f"{count} problem{'' if count == 1 else 's'} in "
            + ", ".join(str(path) for path in problems)
        )


@dataclass(frozen=True)
class Imported:
    policy: Policy
    workbook: Path
    condition_count: int
    exclusion_count: int
    # The Products the Clause store held before this import, in any Wording
    # version. A name not among them starts a new Product.
    stored_products: tuple[str, ...]


def list_policies(document: str | PathLike[str]) -> list[Policy]:
    """List the policies a clause document contains, each with its Clauses."""
    return split_policies(_pages(Path(document)))


def import_product(
    document: str | PathLike[str],
    *,
    product: str,
    wording: Wording,
    workbook: str | PathLike[str],
    store: ClauseStore,
    models: LocalModels,
    policy: int | None = None,
    pages: tuple[int, int] | None = None,
) -> Imported:
    """Import one policy of a document as a Product in a Wording version, as a draft workbook.

    The policy is chosen by its number in List policies' list, or by a page
    range that holds it; with both, the number counts within the range. The
    policy's Clauses go to the Clause store, replacing any stored for the same
    Product and Wording version, and are indexed for retrieval. An existing
    workbook is never overwritten: a re-import makes a fresh draft.
    """
    path = Path(workbook)
    if path.exists():
        raise CannotImport(f"{path} already exists; name a new workbook for the draft")
    chosen = _choose(_pages(Path(document)), policy, pages)
    stored_products = tuple(store.products())
    store.replace(product, wording, chosen.clauses)
    conditions, exclusions = draft_table(product, wording, chosen.clauses, models)
    models.index(product, wording, chosen.clauses)
    write_draft(path, product, wording, conditions, exclusions)
    return Imported(chosen, path, len(conditions), len(exclusions), stored_products)


def load_workbook(workbook: str | PathLike[str], *, store: ClauseStore) -> Loaded:
    """Validate a workbook and list every problem in it.

    Clause references are checked against the Clauses stored at import.
    """
    return load(Path(workbook), store)


def judge_scenario(
    scenario: str,
    workbooks: Sequence[str | PathLike[str]],
    *,
    store: ClauseStore,
    models: LocalModels,
) -> VerdictMatrix:
    """Judge a Scenario, described in free text, against each confirmed workbook.

    Every workbook is validated as Load does first; if any has a problem,
    nothing is judged. Clause text comes from the Clause store.
    """
    tables: list[ConditionTable] = []
    problems: dict[Path, tuple[Problem, ...]] = {}
    for workbook in workbooks:
        loaded = load(Path(workbook), store)
        if loaded.table is None:
            problems[Path(workbook)] = loaded.problems
        else:
            tables.append(loaded.table)
    if problems:
        raise CannotJudge(problems)
    return judge(scenario, tables, store, models)


def _choose(pages: list[str], number: int | None, page_range: tuple[int, int] | None) -> Policy:
    where = "the document holds"
    if page_range is not None:
        first, last = page_range
        if not 1 <= first <= last <= len(pages):
            raise CannotImport(
                f"pages {first}–{last} are not in the document, which has {len(pages)} pages"
            )
        # Blank pages outside the range keep page numbers as in the document.
        pages = [text if first <= n <= last else "" for n, text in enumerate(pages, start=1)]
        where = f"pages {first}–{last} hold"
    policies = split_policies(pages)
    if not policies:
        raise CannotImport(f"{where} no policy")
    if number is None:
        if len(policies) > 1:
            raise CannotImport(
                f"{where} {len(policies)} policies; choose one by its number in the list"
            )
        return policies[0]
    if not 1 <= number <= len(policies):
        raise CannotImport(f"there is no policy {number}; {where} {len(policies)}")
    return policies[number - 1]


def _pages(path: Path) -> list[str]:
    """The text of each page of a document.

    A document is a PDF, or the page text already extracted from one: a UTF-8
    file with a form feed between pages. The form feed may sit on a line of its
    own, as scripts/capture_fixture.py writes it, or end a page's last line, as
    pdftotext writes it.
    """
    with path.open("rb") as file:
        is_pdf = file.read(5) == b"%PDF-"
    if is_pdf:
        return read_pages(path)
    return [page.strip("\n") for page in path.read_text(encoding="utf-8").split("\f")]
