"""
Utility functions that are used everywhere inside Heaty.
"""

import datetime
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

def build_time_expression_env():
    """This function builds and returns an environment usable as globals
       for the evaluation of a time expression."""
    return {
        "datetime": datetime,
        "now": datetime.datetime.now(),
    }

def eval_temp_expr(temp_expr, extra_env=None):
    """This method evaluates the given temperature expression.
       The evaluation result is returned. The items of the extra_env
       dict are added to the globals available during evaluation."""

    parsed = parse_temp(temp_expr)
    if parsed:
        # not an expression, just return the parsed value
        return parsed

    # this is a dynamic temperature expression, evaluate it
    env = build_time_expression_env()
    if extra_env:
        env.update(extra_env)
    temp = eval(temp_expr, env)

    if temp is None:
        # None is a special case, pass it through
        return

    parsed = parse_temp(temp)
    if not parsed:
        raise ValueError("{} is no valid temperature"
                         .format(repr(parsed)))

    return parsed
