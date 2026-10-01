"""The application interface. The command line and the web page are thin shells over it."""

from os import PathLike
from pathlib import Path

from travel_claims.pdf import read_pages
from travel_claims.policies import Policy
from travel_claims.splitter import split_policies


def list_policies(document: str | PathLike[str]) -> list[Policy]:
    """List the policies a clause document contains, each with its Clauses."""
    return split_policies(_pages(Path(document)))


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
