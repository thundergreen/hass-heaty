"""
Module containing functionality to evaluate temperature expressions.
"""

import copy
import datetime


__all__ = ["Add", "Ignore", "Result"]


# special return values for temperature expressions
class Result:
    """Holds the result of a temperature expression."""

    def __init__(self, temp):
        parsed = parse_temp(temp)
        if not parsed:
            raise ValueError("{} is no valid temperature"
                             .format(repr(parsed)))
        self.temp = parsed

    def __eq__(self, other):
        return type(self) is type(other) and self.temp == other.temp

    def __repr__(self):
        return "{}".format(self.temp)

class Add(Result):
    """Result of a temperature expression that is intended to be added
       to the result of a consequent expression."""

    def __add__(self, other):
        if not isinstance(other, Result):
            raise TypeError("can't add {} and {}"
                            .format(repr(type(self)), repr(type(other))))

        if isinstance(other, Ignore):
            return Add(self.temp)

        if self.temp == "off" or other.temp == "off":
            return Result(self.temp)

        if isinstance(other, Add):
            return Add(self.temp + other.temp)

        return Result(self.temp + other.temp)

    def __repr__(self):
        return "Add({})".format(self.temp)

class Ignore(Result):
    """Result of a temperature expression which should be ignored."""

    def __init__(self):
        # pylint: disable=super-init-not-called
        self.temp = None

    def __add__(self, other):
        if not isinstance(other, Result):
            raise TypeError("can't add {} and {}"
                            .format(repr(type(self)), repr(type(other))))

        return copy.deepcopy(other)

    def __repr__(self):
        return "Ignore()"


def parse_temp(temp):
    """Converts the given value to a valid temperature of type float or "off".
       If value is a string, all whitespace is removed first.
       If conversion is not possible, None is returned."""

    if isinstance(temp, str):
        temp = "".join(temp.split())
        if temp.lower() == "off":
            return "off"
        temp = temp.strip()
    try:
        return float(temp)
    except (ValueError, TypeError):
        return

def build_time_expression_env():
    """This function builds and returns an environment usable as globals
       for the evaluation of a time expression. It will add all members
       of this module's __all__ to the environment."""
    env = {"datetime": datetime}
    for name in __all__:
        env[name] = globals()[name]
    return env

def eval_temp_expr(temp_expr, extra_env=None):
    """This method evaluates the given temperature expression.
       The evaluation result is returned. The items of the extra_env
       dict are added to the globals available during evaluation.
       The result is an instance of Result."""

    try:
        return Result(temp_expr)
    except ValueError:
        # it's an expression, not a simple temperature value
        pass

    env = build_time_expression_env()
    if extra_env:
        env.update(extra_env)
    result = eval(temp_expr, env)

    if not isinstance(result, Result):
        result = Result(result)

    return result
