"""
Utility functions that are used everywhere inside Heaty.
"""

import datetime
import re


# regexp pattern matching a range like 3-7 without spaces
RANGE_PATTERN = re.compile(r"^(\d+)\-(\d+)$")
# regexp pattern matching military time format (%H:%M)
TIME_PATTERN = re.compile(r"^([01]\d|2[0123])[\:\.]([012345]\d)$")
# strftime-compatible format string for military time
TIME_FORMAT = "%H:%M"


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

def format_time(when, format_str=TIME_FORMAT):
    """Returns a string representing the given datetime.time object.
       If no strftime-compatible format is provided, the default is used."""
    return when.strftime(format_str)

def parse_time_string(time_str):
    """Parses a string of the form %H:%M or %H.%M (military time)
       into a datetime.time object. If the string has an invalid
       format, None is returned."""
    # remove whitespace
    time_str = "".join(time_str.split())
    match = TIME_PATTERN.match(time_str)
    if match:
        return datetime.time(int(match.group(1)), int(match.group(2)))
