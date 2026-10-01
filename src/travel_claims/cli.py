"""The command line: a thin shell over the application interface."""

import argparse
import re
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from travel_claims.app import (
    CannotImport,
    CannotJudge,
    import_product,
    judge_scenario,
    list_policies,
    load_workbook,
)
from travel_claims.clause_store import ClauseStore
from travel_claims.conditions import ClauseRef
from travel_claims.judging import VerdictMatrix
from travel_claims.local_models import ArrangedBy, Incident, LocalModels, Replacement
from travel_claims.policies import Policy, Wording

# The Clause store lives here unless --store says otherwise. Workbooks go to
# _WORKBOOKS. Both are git-ignored: they hold the customer's text.
_STORE = Path("store")
_WORKBOOKS = Path("workbooks")


def main(argv: Sequence[str] | None = None, models: LocalModels | None = None) -> None:
    """Run a command. `models` serves the local-models port; tests pass a scripted one."""
    parser = argparse.ArgumentParser(prog="travel-claims")
    commands = parser.add_subparsers(dest="command", required=True)

    listing = commands.add_parser(
        "list-policies",
        help="list the policies in a clause document",
        description="List the policies in a clause document: a PDF, or page text "
        "extracted from one, with a form feed between pages.",
    )
    listing.add_argument("document", type=_file)

    importing = commands.add_parser(
        "import",
        help="import a policy of a clause document as a Product, as a draft workbook",
        description="Import one policy of a clause document as a Product in a Wording "
        "version. The local models extract its Conditions and exclusions into a draft "
        "workbook for review, and its Clauses are stored and indexed.",
    )
    importing.add_argument("document", type=_file)
    importing.add_argument("--product", required=True, help="the Product's name")
    importing.add_argument("--wording", required=True, choices=list(Wording), type=Wording)
    importing.add_argument("--policy", type=int, help="the policy's number in list-policies' list")
    importing.add_argument(
        "--pages", type=_page_range, help="the pages that hold the policy, such as 13-19"
    )
    importing.add_argument("--workbook", type=Path, help="default: workbooks/PRODUCT.WORDING.xlsx")
    importing.add_argument("--store", type=Path, default=_STORE, help="the Clause store")

    loading = commands.add_parser(
        "load",
        help="check a reviewed workbook and list every problem in it",
        description="Validate a reviewed workbook, list every problem at once, and count "
        "the extracted fields the reviewer changed. Exits with status 1 if there is a problem.",
    )
    loading.add_argument("workbook", type=_file)
    loading.add_argument("--store", type=Path, default=_STORE, help="the Clause store")

    judging = commands.add_parser(
        "judge",
        help="judge a Scenario against confirmed workbooks",
        description="Judge a Scenario, described in free text, against each confirmed "
        "workbook, and print the facts read from it and the Verdict matrix. Nothing is "
        "judged while any workbook has a problem; the command then exits with status 1.",
    )
    judging.add_argument("--scenario", required=True, help="the Scenario, in free text")
    judging.add_argument("workbooks", nargs="+", type=_file, metavar="workbook")
    judging.add_argument("--store", type=Path, default=_STORE, help="the Clause store")

    args = parser.parse_args(argv)
    if args.command == "list-policies":
        for index, policy in enumerate(list_policies(args.document), start=1):
            print(_describe(index, policy))
    elif args.command == "import":
        if models is None:
            parser.error("import needs the local models, which are not connected yet")
        _import(args, models, parser)
    elif args.command == "judge":
        if models is None:
            parser.error("judge needs the local models, which are not connected yet")
        _judge(args, models)
    else:
        _load(args)


def _import(args: argparse.Namespace, models: LocalModels, parser: argparse.ArgumentParser) -> None:
    workbook = args.workbook or _WORKBOOKS / f"{args.product}.{args.wording}.xlsx"
    try:
        imported = import_product(
            args.document,
            product=args.product,
            wording=args.wording,
            workbook=workbook,
            store=ClauseStore(args.store),
            models=models,
            policy=args.policy,
            pages=args.pages,
        )
    except CannotImport as error:
        parser.error(str(error))
    policy = imported.policy
    print(
        f"Imported {policy.name or '(no title found)'} ({_pages(policy)}) "
        f"as {args.product}, {args.wording} wording."
    )
    if policy.suggested_wording not in (None, args.wording):
        print(f"Note: its flight-delay exclusions suggest the {policy.suggested_wording} wording.")
    if imported.stored_products and args.product not in imported.stored_products:
        print(
            f"Note: {args.product} is a new Product. The Clause store already holds "
            f"{', '.join(imported.stored_products)}; to import another Wording version of a "
            "Product, give its name exactly."
        )
    print(
        f"Stored {_count(len(policy.clauses), 'Clause')}. "
        f"Extracted {_count(imported.condition_count, 'Condition')} and "
        f"{_count(imported.exclusion_count, 'exclusion')} into the draft workbook"
    )
    print(imported.workbook)
    print("Review it in Excel, and record who confirmed it and when above the Conditions table.")
    print("Then check it with:")
    store = "" if args.store == _STORE else f" --store={args.store}"
    print(f"travel-claims load {imported.workbook}{store}")


def _load(args: argparse.Namespace) -> None:
    loaded = load_workbook(args.workbook, store=ClauseStore(args.store))
    table = loaded.table
    if table is None:
        print(f"{_count(len(loaded.problems), 'problem')}:")
        for problem in loaded.problems:
            print(problem)
    else:
        print(
            f"No problems. {table.product}, {table.wording} wording: "
            f"{_count(len(table.conditions), 'Condition')} and "
            f"{_count(len(table.exclusions), 'exclusion')}, "
            f"confirmed by {table.confirmed_by} on {table.confirmed_on.isoformat()}."
        )
    print(
        f"{loaded.extracted_fields} fields extracted, "
        f"{loaded.changed_fields} changed by the reviewer."
    )
    if table is None:
        sys.exit(1)


def _judge(args: argparse.Namespace, models: LocalModels) -> None:
    try:
        matrix = judge_scenario(
            args.scenario, args.workbooks, store=ClauseStore(args.store), models=models
        )
    except CannotJudge as refused:
        print("Nothing judged: fix these problems first.")
        for workbook, problems in refused.problems.items():
            print(f"{workbook}: {_count(len(problems), 'problem')}")
            for problem in problems:
                print(problem)
        sys.exit(1)
    _print_matrix(matrix)


def _print_matrix(matrix: VerdictMatrix) -> None:
    facts = matrix.facts
    print("Facts read from the Scenario:")
    print(f"  Benefits: {', '.join(facts.benefits) or 'none stated'}")
    for number, incident in enumerate(facts.incidents, start=1):
        print(f"  Incident {number}: {_incident(incident)}")
        for line in _incident_details(incident):
            print(f"    {line}")
    print(f"  Cause: {facts.cause or 'not stated'}")
    period = (
        f"{_time(facts.policy_period[0])} – {_time(facts.policy_period[1])}"
        if facts.policy_period
        else "not stated"
    )
    print(f"  Policy bought {_time(facts.purchased_at)}, policy period {period}")
    print(f"  In force at purchase: {'; '.join(facts.in_force_at_purchase) or 'none stated'}")
    if facts.earlier_claims is not None:
        print(f"  Earlier claims in the policy period: {facts.earlier_claims}")
    for cell in matrix.cells:
        print()
        print(f"{cell.product}, {cell.wording} wording: {cell.verdict}")
        for outcome in cell.outcomes:
            print(
                f"  {outcome.condition}, incident {outcome.incident}: "
                f"{outcome.verdict} ({outcome.clause})"
            )
            print(f"    {outcome.grounds}")


def _incident(incident: Incident) -> str:
    leg = f"{incident.leg} " if incident.leg else ""
    transport = incident.transport or "transport not stated"
    airport = f" from {incident.airport}" if incident.airport else ""
    return f"{leg}{transport}{airport}"


def _incident_details(incident: Incident) -> list[str]:
    times = [f"scheduled departure {_time(incident.scheduled_departure)}"]
    if incident.actual_departure is not None:
        times.append(f"actual departure {_time(incident.actual_departure)}")
    if incident.cancelled:
        times.append("cancelled")
    if incident.missed_connection:
        times.append("connection missed")
    if incident.stated_delay is not None:
        hours = incident.stated_delay.total_seconds() / 3600
        times.append(f"delay stated as {hours:g} hours")
    return [", ".join(times), *(_replacement(r) for r in incident.replacements)]


def _replacement(replacement: Replacement) -> str:
    parts = [f"replacement departing {_time(replacement.departure)}"]
    if replacement.arranged_by is ArrangedBy.INSURED:
        arranged = "arranged by the insured"
        if replacement.arranged_at is not None:
            arranged += f" at {_time(replacement.arranged_at)}"
        parts.append(arranged)
    elif replacement.arranged_by is ArrangedBy.AIRLINE:
        parts.append("arranged by the airline")
    if replacement.destination:
        home = {True: " (Taiwan)", False: " (not Taiwan)", None: ""}
        parts.append(f"to {replacement.destination}{home[replacement.returns_to_taiwan]}")
    if replacement.taken is not None:
        parts.append("taken" if replacement.taken else "not taken")
    return ", ".join(parts)


def _time(moment: datetime | None) -> str:
    return "not stated" if moment is None else moment.strftime("%Y-%m-%d %H:%M")


def _file(text: str) -> Path:
    path = Path(text)
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"no such file: {text}")
    return path


def _page_range(text: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)(?:\s*[-–]\s*(\d+))?", text.strip())
    if match is None:
        raise argparse.ArgumentTypeError(f"not a page range, such as 13-19: {text}")
    first = int(match.group(1))
    return first, int(match.group(2) or first)


def _describe(index: int, policy: Policy) -> str:
    wording = (
        f"suggested wording: {policy.suggested_wording}"
        if policy.suggested_wording
        else "no suggested wording (no flight-delay exclusions)"
    )
    clauses = f"{_count(len(policy.clauses), 'Clause')}: {_clause_ranges(policy.clause_numbers)}"
    prefix = f"{index}. "
    indent = " " * len(prefix)
    return (
        f"{prefix}{policy.name or '(no title found)'}\n"
        f"{indent}{_pages(policy)}, {wording}\n{indent}{clauses}"
    )


def _pages(policy: Policy) -> str:
    first, last = policy.pages
    return f"page {first}" if first == last else f"pages {first}–{last}"


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}{'' if number == 1 else 's'}"


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
    return str(ClauseRef(number))
