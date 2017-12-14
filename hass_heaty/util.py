"""
Utility functions that are used everywhere inside Heaty.
"""

import datetime
import re


# regexp pattern matching a range like 3-7 without spaces
RANGE_PATTERN = re.compile(r"^(\d+)\-(\d+)$")
# regexp pattern matching military time format (%H:%M)
TIME_PATTERN = re.compile(r"^([01]\d|2[0123])[\:\.]([012345]\d)$")
# matches any character that is not allowed in Python variable names
INVALID_VAR_NAME_CHAR_PATTERN = re.compile(r"[^a-zA-Z_]")
# strftime-compatible format string for military time
TIME_FORMAT = "%H:%M"


def escape_var_name(name):
    """Converts the given string to a valid Python variable name.
       All unsupported characters are replaced by "_". If name would
       start with a digit, "_" is put infront."""
    name = INVALID_VAR_NAME_CHAR_PATTERN.sub("_", name)
    digits = tuple([str(i) for i in range(10)])
    if name.startswith(digits):
        name = "_" + name
    return name

def expand_range_string(range_string):
    """Expands strings of the form '1,2-4,9,11-12 to set(1,2,3,4,9,11,12).
       Any whitespace is ignored. If a float or int is given instead of a
       string, a set containing only that, converted to int, is returned."""

    if isinstance(range_string, (float, int)):
        return set([int(range_string)])

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
