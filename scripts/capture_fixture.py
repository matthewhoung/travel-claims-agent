"""Print pages of a clause PDF as the PDF reader sees them, for test fixtures.

Usage: uv run python scripts/capture_fixture.py PDF FIRST [LAST] > tests/fixtures/NAME.txt

Pages are separated by a line holding only a form feed, the page-text format
that tests and the command line read. Trim the output by deleting whole lines
only, so the fixture keeps the reader's artefacts.
"""

import sys

from travel_claims.pdf import read_pages


def main() -> None:
    path, first = sys.argv[1], int(sys.argv[2])
    last = int(sys.argv[3]) if len(sys.argv) > 3 else first
    pages = read_pages(path)[first - 1 : last]
    sys.stdout.write("\n\f\n".join(pages) + "\n")


if __name__ == "__main__":
    main()
