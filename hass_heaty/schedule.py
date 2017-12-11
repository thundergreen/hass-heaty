"""
This module implements the Schedule and Rule classes.
"""

import datetime

from . import util


class Rule:
    """A rule that can be added to a schedule."""

    def __init__(self, temp_expr, start_time=None, end_time=None,
                 end_plus_days=0, constraints=None):
        if start_time is None:
            # make it midnight
            start_time = datetime.time(0, 0)
        self.start_time = start_time
        if end_time is None:
            # make it midnight (00:00 of the next day)
            end_time = datetime.time(0, 0)
            end_plus_days += 1
        self.end_time = end_time
        self.end_plus_days = end_plus_days
        if constraints is None:
            constraints = {}
        self.constraints = constraints

        if isinstance(temp_expr, str):
            temp_expr = temp_expr.strip()
        self.temp_expr_raw = temp_expr
        temp = util.parse_temp(temp_expr)
        if temp is None:
            # this is a temperature expression, precompile it
            self.temp_expr = compile(temp_expr, "temp_expr", "eval")
        else:
            self.temp_expr = temp_expr

    def check_constraints(self, date):
        """Checks all constraints of this rule against the given date."""
        year, week, weekday = date.isocalendar()
        for constraint, allowed_values in self.constraints.items():
            if allowed_values is None:
                # ignore this one, since None is not iterable
                continue
            if constraint == "years" and year not in allowed_values:
                return False
            if constraint == "months" and date.year not in allowed_values:
                return False
            if constraint == "days" and date.day not in allowed_values:
                return False
            if constraint == "week" and week not in allowed_values:
                return False
            if constraint == "weekday" and weekday not in allowed_values:
                return False
        return True


class Schedule:
    """Holds the schedule for a room with all its rules."""

    def __init__(self):
        self.rules = []

    def get_rules(self, when):
        """Returns an iterator over all rules of the schedule that are
           valid for the given datetime object, keeping the order from
           the rules list."""

        _time = when.time()
        for rule in self.rules:
            days_back = -1
            found_start_day = False
            while days_back < rule.end_plus_days:
                days_back += 1
                # starts with days=0 (meaning the current date)
                _date = when.date() - datetime.timedelta(days=days_back)

                found_start_day = found_start_day or \
                                  rule.check_constraints(_date)
                if not found_start_day:
                    # try next day
                    continue

                # in first loop run, rule has to start today and not
                # later than now (rule start <= when.time())
                if days_back == 0 and rule.start_time > _time:
                    # maybe there is a next day to try out
                    continue

                # in last loop run, rule is going to end today and that
                # has to be later than now (rule end > when.time())
                if days_back == rule.end_plus_days and rule.end_time <= _time:
                    # rule finally disqualified
                    break

                # rule matches!
                yield rule
                break