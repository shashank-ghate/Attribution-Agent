from __future__ import annotations

import re
import calendar
from datetime import date, datetime

from dateutil import parser as date_parser


ORDINAL_RE = re.compile(r"(?<=\d)(st|nd|rd|th)", re.IGNORECASE)
TYPO_FIXES = {
    "januay": "january",
    "januray": "january",
    "febuary": "february",
    "march 206": "march 2026",
}


def normalize_choice(value: object) -> str:
    return str(value or "").strip().lower()


def normalize_channel(value: object) -> str:
    channel = normalize_choice(value)
    aliases = {"whatsapp": "WhatsApp", "sms": "SMS", "rcs": "RCS"}
    if channel not in aliases:
        raise ValueError(f"Unsupported channel: {value!r}")
    return aliases[channel]


def normalize_campaign_type(value: object) -> str:
    campaign_type = normalize_choice(value)
    aliases = {"overall": "Overall", "online": "Online", "offline": "Offline"}
    if campaign_type not in aliases:
        raise ValueError(f"Unsupported campaign channel type: {value!r}")
    return aliases[campaign_type]


def _clean_date_text(value: str) -> str:
    text = value.lower().strip()
    for wrong, right in TYPO_FIXES.items():
        text = text.replace(wrong, right)
    text = ORDINAL_RE.sub("", text)
    text = re.sub(r"\b(mon|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b", "", text)
    text = re.sub(r"\((?:1\s*day(?:\s*only)?|1\s*day)\)", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ,-–")
    return text


def parse_tracking_range(value: object, campaign_date: date) -> tuple[date, date]:
    """Parse the workbook's human-entered goal ranges, using Column A as context."""
    if isinstance(value, datetime):
        parsed = value.date()
        return parsed, parsed
    if isinstance(value, date):
        return value, value
    if value is None or not str(value).strip():
        return campaign_date, campaign_date

    text = _clean_date_text(str(value))
    # Normalize separators while avoiding hyphens inside ISO dates.
    text = re.sub(r"\s+(?:to|till|until)\s+", " - ", text)
    iso = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?: 00:00:00)?", text)
    if iso:
        parsed = date(*map(int, iso.groups()))
        return parsed, parsed

    parts = [p.strip() for p in re.split(r"\s*[-–]\s*", text) if p.strip()]
    if len(parts) > 2:
        # A numeric dd-mm-yyyy value is a single date.
        try:
            parsed = date_parser.parse(text, dayfirst=True, default=datetime(campaign_date.year, campaign_date.month, campaign_date.day)).date()
            return parsed, parsed
        except (ValueError, OverflowError):
            parts = [parts[0], parts[-1]]

    default = datetime(campaign_date.year, campaign_date.month, campaign_date.day)
    try:
        if len(parts) == 1:
            parsed = date_parser.parse(parts[0], dayfirst=True, default=default).date()
            return parsed, parsed

        left, right = parts[0], parts[-1]
        right_date = date_parser.parse(right, dayfirst=True, default=default).date()
        # If the first half omits its month, inherit the month/year from the end.
        left_default = datetime(right_date.year, right_date.month, min(campaign_date.day, 28))
        left_date = date_parser.parse(left, dayfirst=True, default=left_default).date()
        # Ranges such as "29 - 1 May" start in the preceding month. Column A
        # is the strongest available context for these deliberately abbreviated values.
        if not re.search(r"[a-z]", left) and left_date > right_date:
            if campaign_date.day == left_date.day and campaign_date <= right_date:
                left_date = campaign_date
            else:
                year = right_date.year if right_date.month > 1 else right_date.year - 1
                month = right_date.month - 1 if right_date.month > 1 else 12
                left_date = date(year, month, min(left_date.day, calendar.monthrange(year, month)[1]))
        # Handle Dec-Jan style ranges and year-less ranges crossing a year boundary.
        if left_date > right_date and (left_date - right_date).days > 180:
            if left_date.month == 12 and right_date.month == 1:
                left_date = left_date.replace(year=right_date.year - 1)
            else:
                right_date = right_date.replace(year=left_date.year + 1)
        return left_date, right_date
    except (ValueError, OverflowError, TypeError):
        return campaign_date, campaign_date
