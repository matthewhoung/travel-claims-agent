"""Chinese numerals as used in Clause numbers, such as 三十一 in 第三十一條."""

_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_UNITS = {"十": 10, "百": 100}


def parse_numeral(text: str) -> int:
    """Parse a Chinese numeral below one thousand, or Arabic digits."""
    if text.isdigit():
        return int(text)
    total = digit = 0
    for char in text:
        if char in _DIGITS:
            digit = _DIGITS[char]
        else:
            total += (digit or 1) * _UNITS[char]
            digit = 0
    return total + digit


def format_numeral(number: int) -> str:
    """Write a number below one thousand as a Chinese numeral, as in 第三十一條."""
    digits = "零一二三四五六七八九"
    hundreds, rest = divmod(number, 100)
    tens, ones = divmod(rest, 10)
    text = ""
    if hundreds:
        text += digits[hundreds] + "百"
        if rest and tens == 0:
            text += "零"
    if tens:
        # 十 alone stands for 一十 only at the start: 十二, but 一百一十二.
        text += ("" if tens == 1 and not hundreds else digits[tens]) + "十"
    if ones or not number:
        text += digits[ones]
    return text
