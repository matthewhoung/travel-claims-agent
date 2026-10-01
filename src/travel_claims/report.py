"""How a Verdict matrix is shown: the facts as labelled lines, and the whole matrix in Excel."""

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from travel_claims.judging import VerdictMatrix
from travel_claims.local_models import ArrangedBy, Incident, Replacement, ScenarioFacts

_MATRIX = "Verdict matrix"
_FACTS = "Facts"
_BREAKDOWN = "Breakdown"
_BREAKDOWN_COLUMNS = (
    "Product",
    "Wording version",
    "Condition key",
    "Incident",
    "Turns on",
    "Reading",
    "Verdict",
    "Reason",
    "Grounds",
    "Clause",
    "Delay period",
    "Steps",
)
_DELAY_COLUMN = _BREAKDOWN_COLUMNS.index("Delay period") + 1
_WIDE_COLUMNS = {"Grounds", "As read from the Scenario"}


def describe_facts(facts: ScenarioFacts) -> list[tuple[str | None, str]]:
    """The facts read from a Scenario, one line each, labelled.

    A line with no label details the labelled line above it, such as an incident's times.
    """
    lines: list[tuple[str | None, str]] = [("Benefits", ", ".join(facts.benefits) or "none stated")]
    for number, incident in enumerate(facts.incidents, start=1):
        lines.append((f"Incident {number}", _incident(incident)))
        lines.extend((None, detail) for detail in _incident_details(incident))
    lines.append(("Cause", facts.cause or "not stated"))
    lines.append(("Policy bought", _time(facts.purchased_at)))
    if facts.policy_period is not None:
        period = f"{_time(facts.policy_period[0])} – {_time(facts.policy_period[1])}"
    elif facts.within_policy_period is not None:
        where = "within" if facts.within_policy_period else "outside"
        period = f"dates not stated; the trip is {where} it"
    else:
        period = "not stated"
    lines.append(("Policy period", period))
    lines.append(("In force at purchase", "; ".join(facts.in_force_at_purchase) or "none stated"))
    if facts.earlier_claims is not None:
        lines.append(("Earlier claims in the policy period", str(facts.earlier_claims)))
    return lines


def write_matrix(path: Path, matrix: VerdictMatrix) -> None:
    """Write the Verdict matrix, the facts read and the per-Condition breakdown.

    Each Cause-ambiguous outcome is followed by a row for each reading of each
    provision it turns on. An existing file is never overwritten.
    """
    if path.exists():
        raise FileExistsError(f"{path} already exists; name a new file for the export")
    book = Workbook()
    verdicts = book.active
    assert verdicts is not None  # a new workbook has one sheet
    verdicts.title = _MATRIX
    verdicts.append(["Scenario", matrix.scenario])
    verdicts["A1"].font = Font(bold=True)
    verdicts["B1"].alignment = Alignment(wrap_text=True, vertical="top")
    verdicts.append([])
    _heading(verdicts, ("Product", "Wording version", "Verdict", "Reason"))
    for cell in matrix.cells:
        verdicts.append([cell.product, str(cell.wording), str(cell.verdict), _text(cell.reason)])
    verdicts.column_dimensions["B"].width = 60

    facts = book.create_sheet(_FACTS)
    _heading(facts, ("Fact", "As read from the Scenario"))
    for label, text in describe_facts(matrix.facts):
        facts.append([label, text])

    breakdown = book.create_sheet(_BREAKDOWN)
    _heading(breakdown, _BREAKDOWN_COLUMNS)
    for cell in matrix.cells:
        where = [cell.product, str(cell.wording)]
        for outcome in cell.outcomes:
            condition = [*where, outcome.condition, outcome.incident]
            breakdown.append(
                [
                    *condition,
                    None,
                    None,
                    str(outcome.verdict),
                    _text(outcome.reason),
                    outcome.grounds,
                    str(outcome.clause),
                    outcome.delay,
                    outcome.steps,
                ]
            )
            if outcome.delay is not None:
                breakdown.cell(breakdown.max_row, _DELAY_COLUMN).number_format = "[h]:mm"
            for provision in outcome.turns_on:
                for reading in provision.readings:
                    breakdown.append(
                        [
                            *condition,
                            f"the {provision.kind} of {provision.clause}",
                            reading.cause,
                            str(reading.verdict),
                            _text(reading.reason),
                            reading.grounds,
                            str(reading.clause),
                        ]
                    )

    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(path)


def _heading(sheet: Worksheet, columns: tuple[str, ...]) -> None:
    sheet.append(list(columns))
    row = sheet.max_row
    for column, heading in enumerate(columns, start=1):
        sheet.cell(row, column).font = Font(bold=True)
        width = 60 if heading in _WIDE_COLUMNS else 18
        sheet.column_dimensions[get_column_letter(column)].width = width
    sheet.freeze_panes = f"A{row + 1}"


def _text(value: object | None) -> str | None:
    return None if value is None else str(value)


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
