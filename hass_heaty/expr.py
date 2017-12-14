"""
Module containing functionality to evaluate temperature expressions.
"""

import datetime
import functools


__all__ = ["Add", "Break", "Ignore", "Result", "Temp"]


class AddibleMixin:
    """Mixin that makes a temperature expression result addible."""
    pass

class ResultBase:
    """Holds the result of a temperature expression."""

    def __init__(self, temp):
        self.temp = Temp(temp)

    def __eq__(self, other):
        return type(self) is type(other) and self.temp == other.temp


class Result(ResultBase, AddibleMixin):
    """Final result of a temperature expression."""

    def __repr__(self):
        return "{}".format(self.temp)

class Add(ResultBase, AddibleMixin):
    """Result of a temperature expression that is intended to be added
       to the result of a consequent expression."""

    def __add__(self, other):
        if not isinstance(other, AddibleMixin):
            raise TypeError("can't add {} and {}"
                            .format(repr(type(self)), repr(type(other))))

        if self.temp == "off" or other.temp == "off":
            return type(other)(self.temp)

        return type(other)(self.temp + other.temp)

    def __repr__(self):
        return "Add({})".format(self.temp)

class Break(ResultBase):
    """Result of a temperature expression that should abort scheduling and
       leave the temperature unchanged."""

    def __init__(self):
        # pylint: disable=super-init-not-called
        self.temp = None

    def __repr__(self):
        return "Break()"

class Ignore(ResultBase):
    """Result of a temperature expression which should be ignored."""

    def __init__(self):
        # pylint: disable=super-init-not-called
        self.temp = None

    def __repr__(self):
        return "Ignore()"


@functools.total_ordering
class Temp:
    """A class holding a temperature value."""

    def __init__(self, value):
        if isinstance(value, Temp):
            # just copy the value over
            value = value.value
        parsed = self.parse_temp(value)
        if parsed is None:
            raise ValueError("{} is no valid temperature"
                             .format(repr(value)))
        self.value = parsed

    def __add__(self, other):
        if isinstance(other, (float, int)):
            if not other:
                # +0 changes nothing
                return Temp(self.value)
            other = Temp(other)

        if type(self) is not type(other):
            raise TypeError("can't add {} and {}"
                            .format(repr(type(self)), repr(type(other))))

        if self.is_off() or other.is_off():
            return Temp("off")
        return Temp(self.value + other.value)

    def __sub__(self, other):
        if isinstance(other, (float, int)):
            if not other:
                # -0 changes nothing
                return Temp(self.value)
            other *= -1

        if type(self) is not type(other):
            raise TypeError("can't subtract {} and {}"
                            .format(repr(type(self)), repr(type(other))))

        if self.is_off() or other.is_off():
            return Temp("off")
        return Temp(self.value - other.value)

    def __eq__(self, other):
        return type(self) is type(other) and self.value == other.value

    def __lt__(self, other):
        if isinstance(other, (float, int)):
            other = Temp(other)

        if type(self) is not type(other):
            raise TypeError("can't compare {} and {}"
                            .format(repr(type(self)), repr(type(other))))

        if not self.is_off() and other.is_off():
            return False
        if self.is_off() and not other.is_off() or \
           self.value < other.value:
            return True
        return False

    def __repr__(self):
        if self.is_off():
            return "OFF"
        return repr(self.value)

    def is_off(self):
        """Returns True if this temperature is "off", False otherwise."""
        return isinstance(self.value, str) and self.value == "off"

    @staticmethod
    def parse_temp(value):
        """Converts the given value to a valid temperature of type float or "off".
           If value is a string, all whitespace is removed first.
           If conversion is not possible, None is returned."""

        if isinstance(value, str):
            value = "".join(value.split())
            if value.lower() == "off":
                return "off"

        try:
            return float(value)
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

    if not isinstance(result, ResultBase):
        result = Result(result)

    return result