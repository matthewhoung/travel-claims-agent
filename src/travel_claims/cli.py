"""The command line: a thin shell over the application interface."""

import argparse
from collections.abc import Sequence
from pathlib import Path

from travel_claims.app import list_policies
from travel_claims.numerals import format_numeral
from travel_claims.policies import Policy


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="travel-claims")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser(
        "list-policies",
        help="list the policies in a clause document",
        description="List the policies in a clause document: a PDF, or page text "
        "extracted from one, with a form feed between pages.",
    )
    listing.add_argument("document", type=Path)
    args = parser.parse_args(argv)

    if not args.document.is_file():
        parser.error(f"no such file: {args.document}")
    for index, policy in enumerate(list_policies(args.document), start=1):
        print(_describe(index, policy))


def _describe(index: int, policy: Policy) -> str:
    first, last = policy.pages
    pages = f"page {first}" if first == last else f"pages {first}–{last}"
    wording = (
        f"suggested wording: {policy.suggested_wording}"
        if policy.suggested_wording
        else "no suggested wording (no flight-delay exclusions)"
    )
    count = len(policy.clauses)
    clauses = f"{count} Clause{'' if count == 1 else 's'}: {_clause_ranges(policy.clause_numbers)}"
    prefix = f"{index}. "
    indent = " " * len(prefix)
    return f"{prefix}{policy.name or '(no title found)'}\n{indent}{pages}, {wording}\n{indent}{clauses}"


def _clause_ranges(numbers: Sequence[int]) -> str:
    """Runs of consecutive Clause numbers, as in 第一條, 第三十條–第三十二條."""
    runs: list[list[int]] = []
    for number in numbers:
        if runs and number == runs[-1][-1] + 1:
            runs[-1].append(number)
        else:
            runs.append([number])
    return ", ".join(
        _label(run[0]) if len(run) == 1 else f"{_label(run[0])}–{_label(run[-1])}" for run in runs
    )


def _label(number: int) -> str:
    return f"第{format_numeral(number)}條"
