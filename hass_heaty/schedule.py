"""
This module implements the Schedule and Rule classes as well as some
related constants.
"""

import datetime

from . import util


MIN_RETROSPECT = datetime.timedelta(days=1)
RETROSPECT = datetime.timedelta(days=7)
REBUILD_INTERVAL = datetime.timedelta(days=1)


class Rule:
    """A rule that can be added to a schedule."""

    def __init__(self, temp_expr, start_time=None, end_time=None,
                 constraints=None):
        if start_time is None:
            # make it midnight
            start_time = datetime.time(0, 0)
        self.start_time = start_time
        self.end_time = end_time
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

    def __init__(self, retrospect=None):
        self.rules = []
        self._slots = []
        self._last_build = None
        if retrospect is None:
            retrospect = RETROSPECT
        if retrospect < MIN_RETROSPECT:
            raise ValueError("minimum retrospect is {}."
                             .format(MIN_RETROSPECT))
        self.retrospect = retrospect

    def _build_slots(self, when=None, force=False):
        if when is None:
            when = datetime.datetime.now()

        if not force and self._last_build is not None and \
           when - self._last_build < REBUILD_INTERVAL:
            # nothing to do
            return self._slots

        slots = []
        current_date = when.date()
        # add REBUILD_INTERVAL to ensure that even at the end of a
        # schedule's lifecycle enough buffer is available
        end_date = current_date - self.retrospect - REBUILD_INTERVAL

        while current_date >= end_date:
            for rule in self.rules:
                if rule.check_constraints(current_date):
                    slot = (
                        datetime.datetime.combine(
                            current_date, rule.start_time
                        ),
                        datetime.datetime.combine(
                            current_date, rule.end_time
                        ) if rule.end_time is not None else None,
                        rule,
                    )
                    slots.append(slot)
            current_date = current_date - datetime.timedelta(days=1)

        # sort slots from latest to oldest
        slots.sort(key=lambda slot: slot[0], reverse=True)

        self._slots = slots
        self._last_build = when
        return slots

    def get_slots(self, when):
        """Returns an iterable of slots sorted from latest to oldest.
           It is guaranteed that no slot is starting later than the
           provided datetime requests. Slots that have ended are
           sorted out. The iterable may be empty."""

        slots = self._build_slots(when=when)
        return filter(lambda slot: slot[0] <= when and
                      (slot[1] is None or slot[1] > when),
                      slots)
