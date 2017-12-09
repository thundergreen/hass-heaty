"""
Utility functions that are used everywhere inside Heaty.
"""

import re


ALL_WEEKDAYS = set(range(1, 8))
RANGE_PATTERN = re.compile(r"^(\d+)\-(\d+)$")
TIME_PATTERN = re.compile(r"^([01]\d|2[0123])\:([012345]\d)$")


def expand_range_string(range_string):
    """Expands strings of the form '1,2-4,9,11-12 to set(1,2,3,4,9,11,12).
       Any whitespace is ignored."""

    numbers = set()
    for part in "".join(range_string.split()).split(","):
        match = RANGE_PATTERN.match(part)
        if match is not None:
            for i in range(int(match.group(1)), int(match.group(2)) + 1):
                numbers.add(i)
        else:
            numbers.add(int(part))
    return numbers

def parse_temp(temp):
    """Converts the given value to a valid temperature of type float or "off".
       If conversion is not possible, None is returned."""

    if isinstance(temp, str):
        if temp.lower() == "off":
            return "off"
        temp = temp.strip()
    try:
        return float(temp)
    except (ValueError, TypeError):
        return
