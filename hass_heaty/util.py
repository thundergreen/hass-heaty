"""
Utility functions that are used everywhere inside Heaty.
"""

import datetime
import re


# set containing numbers 1-7, used as representation of Mon - Sun
ALL_WEEKDAYS = set(range(1, 8))
# regexp pattern matching a range like 3-7 without spaces
RANGE_PATTERN = re.compile(r"^(\d+)\-(\d+)$")
# regexp pattern matching military time format (%H:%M)
TIME_PATTERN = re.compile(r"^([01]\d|2[0123])\:([012345]\d)$")
# strftime-compatible format string for military time
TIME_FORMAT = "%H:%M"
# special return value for temperature expressions
TEMP_EXPR_IGNORE = "ignore"


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

def build_time_expression_env():
    """This function builds and returns an environment usable as globals
       for the evaluation of a time expression."""
    return {
        "IGNORE":   TEMP_EXPR_IGNORE,
        "datetime": datetime,
    }

def eval_temp_expr(temp_expr, extra_env=None):
    """This method evaluates the given temperature expression.
       The evaluation result is returned. The items of the extra_env
       dict are added to the globals available during evaluation.
       The result is either TEMP_EXPR_IGNORE or a valid temperature
       value as returned by parse_temp()."""

    parsed = parse_temp(temp_expr)
    if parsed:
        # not an expression, just return the parsed value
        return parsed

    # this is a dynamic temperature expression, evaluate it
    env = build_time_expression_env()
    if extra_env:
        env.update(extra_env)
    temp = eval(temp_expr, env)

    if temp == TEMP_EXPR_IGNORE:
        # IGNORE is a special case, pass it through
        return temp

    parsed = parse_temp(temp)
    if not parsed:
        raise ValueError("{} is no valid temperature"
                         .format(repr(parsed)))

    return parsed
