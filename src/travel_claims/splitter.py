"""Split the page text of a clause document into policies and Clauses, by rules.

No model is involved. Clause documents follow a fixed heading pattern:
optional chapter (章), optional section (節), Clause (條), then numbered items.
Each policy found also gets a suggested Wording version, read from its
flight-delay exclusions.
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, cast

from travel_claims.numerals import parse_numeral
from travel_claims.policies import Clause, Policy, Wording

# Lines -----------------------------------------------------------------------

# The PDF reader leaves stray spaces beside full-width punctuation, as in 「一、 被保險人」.
_SPACED_PUNCTUATION = re.compile(r"\s*([，。、；：？！「」『』（）〔〕【】《》〈〉])\s*")
# A line that is only a page number, such as 「15」, 「- 3 -」 or 「第1頁/共8頁」.
_PAGE_NUMBER = re.compile(r"^[-－–—\s]*(?:\d+|第\s*\d+\s*頁\s*[/／]?\s*共\s*\d+\s*頁)[-－–—\s]*$")
# Running headers and footers are looked for among this many lines at the top
# and at the bottom of each page.
_EDGE_LINES = 2
# A line at a page edge is a running header or footer when it repeats, page
# numbers aside, on at least this many pages, and on at least half the pages
# with text from its first appearance to its last. A footer printed by only one
# policy of a bundle counts; a line that happens to recur far apart does not.
_MIN_RUNNING_PAGES = 3

# Headings ----------------------------------------------------------------------

_NUMERAL = r"[一二三四五六七八九十百零〇]+|\d+"
_HEADING = re.compile(rf"^第\s*({_NUMERAL})\s*([章節條])(.*)$")
# Body text refers to other Clauses with the same 「第 X 條」 pattern. When such a
# reference opens a line, what follows it reads as a sentence, not a title.
_REFERENCE_CONTINUATIONS = ("之", "及", "或", "至", "與", "有關", "另", "所", "規定", "約定")
# A reference may go on to a part of the Clause, as in 「第三十條第一項」. A
# title may also open with 第, as in 「第二章 第三人責任保險」.
_REFERENCE_TO_PART = re.compile(rf"^第\s*(?:{_NUMERAL})\s*[章節條項款目]")
_SENTENCE_PUNCTUATION = re.compile(r"[，。；]")
# A heading with no separator before its title, or with no title, must follow
# the previous heading's number by at most this much.
_MAX_NUMBERING_STEP = 3
# A heading or title that wraps leaves a short tail on the next line, such as
# 「申領」 after 「第三十三條 特定意外事故身故保險金或喪葬費用保險金的」. Only a
# heading title this long can have reached the end of its line.
_WRAPPED_TITLE = 12
_WRAPPED_TAIL = 8
# A numbered item within a Clause, such as 「一、」, 「(一)」 or 「1.」.
_ITEM = re.compile(r"^(?:[一二三四五六七八九十]+、|[（(][一二三四五六七八九十\d]+[)）]|\d+[.、．])")

# Policy titles -----------------------------------------------------------------

# A policy title names a 保險, 附加條款 or 附約, perhaps followed by a plan
# type, as in 「…附約(甲型)」 or 「…綜合保險-甲型」.
_TITLE_ENDING = re.compile(
    r"(?:保險|附加條款|附約)\s*(?:[（(][^（()）]*[）)]|[-－—]\s*\w{1,4}型)?$"
)
_NOT_IN_TITLE = re.compile(r"[，。；：、]")
# A title can wrap over this many lines. When it does, its first line names the
# insurer, such as 國泰產物 or 和泰產物, or its last line is a short tail.
_TITLE_LINES = 3
_OPENS_WITH_INSURER = re.compile(r"^\w{2,4}產物")
# A policy that begins on a new page may print a short notice above its
# title, such as its filing number (備查文號) and complaints line (申訴電話).
_NOTICE = re.compile(r"文號|申訴電話|https?:")
_MAX_NOTICE_LINES = 12

# Wording version ---------------------------------------------------------------

# The new wording's flight-delay exclusions add a sea typhoon warning issued
# before purchase and widen the strike exclusion to a right to strike already
# obtained. The old wording has neither.
_NEW_WORDING_EXCLUSIONS = ("海上颱風警報", "已取得罷工權")


@dataclass(frozen=True)
class _Line:
    page: int
    text: str


_Kind = Literal["章", "節", "條"]


@dataclass(frozen=True)
class _Heading:
    kind: _Kind
    number: int
    title: str
    # Set off from its title by a space or colon, as headings are and
    # references in body text are not.
    separated: bool


@dataclass
class _ClauseDraft:
    number: int
    heading: str
    chapter: str | None
    section: str | None
    lines: list[_Line] = field(default_factory=list)


@dataclass
class _PolicyDraft:
    name: str | None
    first_page: int
    clauses: list[_ClauseDraft] = field(default_factory=list)


def split_policies(pages: Sequence[str]) -> list[Policy]:
    """Return the policies found in `pages`, the text of a document page by page."""
    policies: list[_PolicyDraft] = []
    # Lines outside any Clause: before the first heading of a policy, or
    # between its first chapter heading and its first Clause.
    loose: list[_Line] = []
    chapter: str | None = None
    section: str | None = None
    last_number = _no_numbers_yet()
    for line in _join_wrapped_headings(_lines(pages)):
        heading = _heading(line.text)
        if heading and not (
            heading.separated or _follows(heading.number, last_number[heading.kind])
        ):
            heading = None
        last_clause = policies[-1].clauses[-1] if policies and policies[-1].clauses else None
        if heading is None:
            (last_clause.lines if last_clause else loose).append(line)
            continue
        if not policies or (heading.number == 1 and heading.kind != "節" and last_clause):
            # Chapter or Clause numbering restarts: a new policy, whose title
            # and preamble were read as the tail of the previous policy.
            policies.append(_new_policy(last_clause.lines if last_clause else loose, line))
            loose = []
            chapter = section = None
            last_number = _no_numbers_yet()
        last_number[heading.kind] = heading.number
        if heading.kind == "章":
            chapter, section = line.text, None
            last_number["節"] = 0
        elif heading.kind == "節":
            section = line.text
        else:
            draft = _ClauseDraft(heading.number, heading.title, chapter, section, [line])
            policies[-1].clauses.append(draft)
    # A title followed by chapter headings and no Clause, as on a table of
    # contents, is not a policy.
    return [_policy(draft) for draft in policies if draft.clauses]


def _no_numbers_yet() -> dict[_Kind, int]:
    return {"章": 0, "節": 0, "條": 0}


def _new_policy(lines_before: list[_Line], first_heading: _Line) -> _PolicyDraft:
    """Start a policy, named from the nearest title line before its first heading.

    The title line and the lines after it are removed from `lines_before`.
    """
    for end in range(len(lines_before) - 1, -1, -1):
        title = _title_ending_at(lines_before, end)
        if title is not None:
            start, name = title
            start = _notice_start(lines_before, start)
            first_page = lines_before[start].page
            del lines_before[start:]
            return _PolicyDraft(name, first_page)
    return _PolicyDraft(None, first_heading.page)


def _notice_start(lines: list[_Line], title: int) -> int:
    """Where the policy titled at `lines[title]` begins, counting a notice above it.

    A notice counts only when it is all that precedes the title on its page,
    so the previous policy's last Clause has ended on an earlier page.
    """
    top = title
    while top > 0 and lines[top - 1].page == lines[title].page:
        top -= 1
    notice = lines[top:title]
    if top > 0 and len(notice) <= _MAX_NOTICE_LINES and any(_NOTICE.search(l.text) for l in notice):
        return top
    return title


def _title_ending_at(lines: list[_Line], end: int) -> tuple[int, str] | None:
    """The title whose last line is `lines[end]`, with the index of its first line."""
    for start in range(max(0, end - _TITLE_LINES + 1), end + 1):
        parts = [line.text for line in lines[start : end + 1]]
        could_be_title = start == end or (
            (
                _OPENS_WITH_INSURER.match(parts[0])
                or (len(parts) == 2 and _is_wrapped_tail(parts[1]))
            )
            and all(_may_be_in_title(part) and not re.search(r"[\s\d]", part) for part in parts)
        )
        if could_be_title and _is_title("".join(parts)):
            return start, "".join(parts)
    return None


def _join_wrapped_headings(lines: list[_Line]) -> list[_Line]:
    """Rejoin each heading whose title wrapped onto the next line."""
    joined: list[_Line] = []
    for line in lines:
        heading = _heading(joined[-1].text) if joined else None
        if heading and len(heading.title) >= _WRAPPED_TITLE and _is_wrapped_tail(line.text):
            joined[-1] = _Line(joined[-1].page, joined[-1].text + line.text)
        else:
            joined.append(line)
    return joined


def _is_wrapped_tail(text: str) -> bool:
    return len(text) <= _WRAPPED_TAIL and _may_be_in_title(text)


def _lines(pages: Sequence[str]) -> list[_Line]:
    """The lines of every page, without page numbers, running headers and footers."""
    texts = [[_normalise(text) for text in page.split("\n") if text.strip()] for page in pages]
    running = _running_lines(texts)
    lines = []
    for number, page in enumerate(texts, start=1):
        start, end = 0, len(page)
        while start < end and _is_furniture(page[start], running):
            start += 1
        while end > start and _is_furniture(page[end - 1], running):
            end -= 1
        lines += [_Line(number, text) for text in page[start:end]]
    return lines


def _normalise(text: str) -> str:
    # NFC turns CJK compatibility ideographs, which some PDFs use for common
    # characters such as 不, into ordinary ones. Unlike NFKC it leaves
    # full-width punctuation alone.
    text = unicodedata.normalize("NFC", text)
    return _SPACED_PUNCTUATION.sub(r"\1", text.strip())


def _running_lines(pages: list[list[str]]) -> set[str]:
    found_on: dict[str, list[int]] = {}
    for number, page in enumerate(pages):
        for line in {_mask_digits(text) for text in page[:_EDGE_LINES] + page[-_EDGE_LINES:]}:
            found_on.setdefault(line, []).append(number)
    running = set()
    for line, numbers in found_on.items():
        with_text = sum(1 for page in pages[numbers[0] : numbers[-1] + 1] if page)
        if len(numbers) >= _MIN_RUNNING_PAGES and len(numbers) * 2 >= with_text:
            running.add(line)
    return running


def _is_furniture(text: str, running: set[str]) -> bool:
    return bool(_PAGE_NUMBER.match(text)) or _mask_digits(text) in running


def _mask_digits(text: str) -> str:
    return re.sub(r"\d+", "#", text)


def _heading(text: str) -> _Heading | None:
    """Read `text` as a chapter or Clause heading, unless it is a reference."""
    match = _HEADING.match(text)
    if match is None:
        return None
    rest = match.group(3)
    title = rest.lstrip(" \t\u3000：:").strip()
    if (
        title.startswith(_REFERENCE_CONTINUATIONS)
        or _REFERENCE_TO_PART.match(title)
        or _SENTENCE_PUNCTUATION.search(title)
    ):
        return None
    separated = bool(title) and title != rest
    kind = cast(_Kind, match.group(2))  # _HEADING matches only 章, 節 and 條
    return _Heading(kind, parse_numeral(match.group(1)), title, separated)


def _follows(number: int, last: int) -> bool:
    return number == 1 or last < number <= last + _MAX_NUMBERING_STEP


def _is_title(text: str) -> bool:
    """A policy title, such as 國泰產物享樂遊海外旅行綜合保險."""
    return bool(_TITLE_ENDING.search(text)) and _may_be_in_title(text)


def _may_be_in_title(text: str) -> bool:
    return (
        not _NOT_IN_TITLE.search(text)
        and not _ITEM.match(text)
        and not text.startswith(("※", "【"))
        and _heading(text) is None
    )


def _policy(draft: _PolicyDraft) -> Policy:
    clauses = tuple(_clause(clause) for clause in draft.clauses)
    return Policy(
        name=draft.name,
        pages=(draft.first_page, clauses[-1].pages[1]),
        suggested_wording=_suggest_wording(draft.clauses),
        clauses=clauses,
    )


def _suggest_wording(clauses: list[_ClauseDraft]) -> Wording | None:
    exclusions = [
        "".join(line.text for line in clause.lines)
        for clause in clauses
        if ("不保" in clause.heading or "除外" in clause.heading)
        and "班機延誤" in f"{clause.chapter or ''}{clause.section or ''}{clause.heading}"
    ]
    if not exclusions:
        return None
    if any(all(term in text for term in _NEW_WORDING_EXCLUSIONS) for text in exclusions):
        return Wording.NEW
    return Wording.OLD


def _clause(draft: _ClauseDraft) -> Clause:
    return Clause(
        number=draft.number,
        heading=draft.heading,
        chapter=draft.chapter,
        text="\n".join(line.text for line in draft.lines[1:]),
        pages=(draft.lines[0].page, draft.lines[-1].page),
    )
