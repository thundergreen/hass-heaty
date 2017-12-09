"""
A highly-configurable, comfortable to use Home Assistant / appdaemon app
that controls thermostats based on a schedule while still facilitating
manual intervention at any time.
"""

import datetime

import appdaemon.appapi as appapi

from . import __version__, config, util


__all__ = ["Heaty"]


SCHEDULE_ENTITY_DELAY = 5


class Heaty(appapi.AppDaemon):
    """The Heaty app class for AppDaemon."""

    def __init__(self, *args, **kwargs):
        super(Heaty, self).__init__(*args, **kwargs)
        self.cfg = {}
        self.current_temps = {}
        self.reschedule_timers = {}

    def initialize(self):
        """Parses the configuration, initializes all timers and state
           callbacks and sets temperatures in all rooms according to
           the configured schedule."""

        self.log("--- Heaty v{} initialization started.".format(__version__))

        self.log("--- Parsing the configuration.")
        self.cfg = config.parse_config(self.args)

        self.reschedule_timers = {}

        self.log("--- Getting current temperatures from thermostats.")
        self.current_temps = {}
        for room_name, room in self.cfg["rooms"].items():
            # set placeholder value in case there are no thermostats
            self.current_temps[room_name] = None
            for therm_name, therm in room["thermostats"].items():
                if therm["ignore_updates"]:
                    # don't consider this thermostat for state updates
                    continue
                # fetch initial state from thermostats
                state = self.get_state(therm_name, attribute="all")
                # populate self.current_temps by simulating a state change
                self.thermostat_state_cb(therm_name, "all", state, state,
                                         {"room_name": room_name,
                                          "no_reschedule": True})
                # only consider one thermostat per room
                break

        if self.cfg["debug"]:
            self.log("--- Creating schedule timers.")
        for room_name, room in self.cfg["rooms"].items():
            for slot in room["schedule"]:
                # run 1 second later to guarantee there is no race condition
                daytime = datetime.time(slot[1].hour, slot[1].minute,
                                        slot[1].second + 1)
                if self.cfg["debug"]:
                    self.log("--- [{}] Registering timer at {}."
                             .format(room["friendly_name"], daytime))
                self.run_daily(self.schedule_cb, daytime, room_name=room_name)

        if self.cfg["debug"]:
            self.log("--- Registering state listeners for schedule entities.")
        for entity_name in self.cfg["schedule_entities"]:
            if self.cfg["debug"]:
                self.log("--- Registering state listener for {}, delay {}."
                         .format(entity_name, SCHEDULE_ENTITY_DELAY))
            self.listen_state(self.schedule_entity_state_cb, entity_name,
                              duration=SCHEDULE_ENTITY_DELAY)

        if self.cfg["debug"]:
            self.log("--- Registering thermostat state listeners.")
        for room_name, room in self.cfg["rooms"].items():
            for therm_name, therm in room["thermostats"].items():
                if not therm["ignore_updates"]:
                    if self.cfg["debug"]:
                        self.log("--- [{}] Registering state listener for {}."
                                 .format(room["friendly_name"], therm_name))
                    self.listen_state(self.thermostat_state_cb, therm_name,
                                      attribute="all", room_name=room_name)

        if self.cfg["debug"]:
            self.log("--- Registering master/schedule switch state listeners.")
        master_switch = self.cfg["master_switch"]
        if master_switch:
            if self.cfg["debug"]:
                self.log("--- Registering state listener for {}."
                         .format(master_switch))
            self.listen_state(self.master_switch_cb, master_switch)
        for room_name, room in self.cfg["rooms"].items():
            schedule_switch = room["schedule_switch"]
            if schedule_switch:
                if self.cfg["debug"]:
                    self.log("--- [{}] Registering state listener for {}."
                             .format(room["friendly_name"], schedule_switch))
                self.listen_state(self.schedule_switch_cb, schedule_switch,
                                  room_name=room_name)

        if self.cfg["debug"]:
            self.log("--- Registering window sensor state listeners.")
        for room_name, room in self.cfg["rooms"].items():
            for sensor_name, sensor in room["window_sensors"].items():
                if self.cfg["debug"]:
                    self.log("--- [{}] Registering state listener for {}, "
                             "delay {}.".format(
                                 room["friendly_name"], sensor_name,
                                 sensor["delay"]))
                self.listen_state(self.window_sensor_cb, sensor_name,
                                  duration=sensor["delay"],
                                  room_name=room_name)

        if self.master_switch_enabled():
            self.log("--- Setting initial temperatures where needed.")
            for room_name in self.cfg["rooms"]:
                if not self.check_for_open_window(room_name):
                    self.set_scheduled_temp(room_name)
        else:
            self.log("--- Master switch is off, setting no initial values.")

        self.log("--- Initialization done.")

    def schedule_cb(self, kwargs):
        """Is called whenever a schedule timer fires."""

        room_name = kwargs["room_name"]
        room = self.cfg["rooms"][room_name]

        if self.cfg["debug"]:
            self.log("--- [{}] Schedule timer fired."
                     .format(room["friendly_name"]))

        if room_name in self.reschedule_timers:
            # don't schedule now, wait for the timer instead
            self.log("--- [{}] Not scheduling now due to a running "
                     "re-schedule timer."
                     .format(room["friendly_name"]))
            return

        self.set_scheduled_temp(room_name)

    def reschedule_cb(self, kwargs):
        """Is called whenever a re-schedule timer fires."""
        room_name = kwargs["room_name"]
        room = self.cfg["rooms"][room_name]
        self.log("--- [{}] Re-schedule timer fired."
                 .format(room["friendly_name"]))
        self.cancel_reschedule_timer(room_name)
        self.set_scheduled_temp(room_name)

    def schedule_entity_state_cb(self, entity, attr, old, new, kwargs):
        """Is called when the value of an entity changes that is part
           of a dynamic schedule.
           This method runs set_scheduled_temp for all rooms to refresh
           the temperatures."""
        if self.cfg["debug"]:
            self.log("--- Re-computing temperatures in all rooms.")
        for room_name in self.cfg["rooms"]:
            self.set_scheduled_temp(room_name)

    def thermostat_state_cb(self, entity, attr, old, new, kwargs):
        """Is called when a thermostat's state changes.
           This method fetches the set target temperature from the
           thermostat and sends updates to all other thermostats in
           the room."""

        room_name = kwargs["room_name"]
        room = self.cfg["rooms"][room_name]
        therm = room["thermostats"][entity]

        opmode = new["attributes"].get(therm["opmode_state_attr"])
        if self.cfg["debug"]:
            self.log("--> [{}] {}: attribute {} is {}"
                     .format(room["friendly_name"], entity,
                             therm["opmode_state_attr"], opmode))

        if opmode is None:
            # don't consider this thermostat
            return
        elif opmode == therm["opmode_off"]:
            temp = "off"
            if isinstance(self.current_temps[room_name], (float, int)) and \
               isinstance(therm["min_temp"], (float, int)) and \
               self.current_temps[room_name] + therm["delta"] < \
               therm["min_temp"]:
                # The thermostat reported itself to be off, but the
                # expected temperature is outside the thermostat's
                # supported temperature range anyway. Hence the report
                # means no change and can safely be ignored.
                return
            if self.get_open_windows(room_name):
                # After window has been opened and heating turned off,
                # thermostats usually report to be off, but we don't
                # care to not mess up self.current_temps.
                return
        else:
            temp = new["attributes"].get(therm["temp_state_attr"])
            if self.cfg["debug"]:
                self.log("--> [{}] {}: attribute {} is {}"
                         .format(room["friendly_name"], entity,
                                 therm["temp_state_attr"], temp))
            if temp is None:
                # don't consider this thermostat
                return
            temp = float(temp) - therm["delta"]

        if temp == self.current_temps[room_name]:
            # nothing changed, hence no further actions needed
            return

        self.log("--> [{}] Received target temperature {} from thermostat."
                 .format(room["friendly_name"], repr(temp)))
        if len(room["thermostats"]) > 1 and \
           room["replicate_changes"] and self.master_switch_enabled():
            if self.cfg["debug"]:
                self.log("<-- [{}] Propagating the change to all "
                         "thermostats.".format(room["friendly_name"]))
            self.set_temp(room_name, temp, scheduled=False)
        else:
            # just update the records
            self.current_temps[room_name] = temp

        if any((not self.master_switch_enabled(),
                not self.schedule_switch_enabled(room_name),
                kwargs.get("no_reschedule"))):
            # only re-schedule when in schedule mode and not
            # explicitly disabled
            return

        if temp == self.get_scheduled_temp(room_name):
            # hit scheduled temperature, cancelling the timer and
            # going back to schedule
            self.cancel_reschedule_timer(room_name)
        elif room["reschedule_delay"]:
            self.cancel_reschedule_timer(room_name)
            # delay is expected to be in seconds by AppDaemon, but given
            # to Heaty as minutes
            delay = 60 * room["reschedule_delay"]
            if self.cfg["debug"]:
                self.log("--- [{}] Registering re-schedule timer in "
                         "{} seconds."
                         .format(room["friendly_name"], delay))
            timer = self.run_in(self.reschedule_cb, delay,
                                room_name=room_name)
            self.reschedule_timers[room_name] = timer

    def master_switch_cb(self, entity, attr, old, new, kwargs):
        """Is called when the master switch is toggled.
           If switch is turned on, it also turns on all schedule switches
           based on the value of self.cfg["master_controls_schedule_switches"]
           and sets the scheduled temperatures in all rooms.
           If switch is turned off, all re-schedule timers are cancelled
           and temperature is set to self.cfg["off_temp"] everywhere."""

        self.log("--> Master switch turned {}.".format(new))
        for room_name, room in self.cfg["rooms"].items():
            schedule_switch = room["schedule_switch"]
            if new == "on":
                if schedule_switch and \
                   self.cfg["master_controls_schedule_switches"] and \
                   not self.schedule_switch_enabled(room_name):
                    self.log("<-- [{}] Turning schedule switch on."
                             .format(room["friendly_name"]))
                    # This will automatically invoke a call to
                    # set_scheduled_temp by the schedule_switch_cb.
                    self.turn_on(schedule_switch)
                else:
                    self.set_scheduled_temp(room_name)
            else:
                self.cancel_reschedule_timer(room_name)
                self.set_temp(room_name, self.cfg["off_temp"],
                              scheduled=False)

    def schedule_switch_cb(self, entity, attr, old, new, kwargs):
        """Is called when a room's schedule switch is toggled.
           It either sets the scheduled temperature in the given room
           (when switch is turned on) or cancels an existing re-schedule
           timer otherwise."""

        room_name = kwargs["room_name"]
        room = self.cfg["rooms"][room_name]
        self.log("--> [{}] Schedule switch turned {}."
                 .format(room["friendly_name"], new))

        if not self.master_switch_enabled():
            self.log("--- Master switch is off, doing nothing.")
            return

        if new == "on":
            self.set_scheduled_temp(room_name)
        else:
            self.cancel_reschedule_timer(room_name)

    def window_sensor_cb(self, entity, attr, old, new, kwargs):
        """Is called when a window sensor's state has changed.
           This method handles the window open/closed detection and
           performs actions accordingly."""

        room_name = kwargs["room_name"]
        room = self.cfg["rooms"][room_name]
        sensor = room["window_sensors"][entity]
        action = "opened" if new == "on" or sensor["inverted"] else "closed"
        if self.cfg["debug"]:
            self.log("--> [{}] {}: state is now {}"
                     .format(room["friendly_name"], entity, new))
        self.log("--> [{}] Window {}.".format(room["friendly_name"], action))

        if not self.master_switch_enabled():
            self.log("--- [{}] Master switch is off, ignoring window."
                     .format(room["friendly_name"]))
            return

        if action == "opened":
            # turn heating off, but store the original temperature
            self.check_for_open_window(room_name)
        elif not self.get_open_windows(room_name):
            # all windows closed
            if self.schedule_switch_enabled(room_name) and \
               room_name not in self.reschedule_timers:
                self.set_scheduled_temp(room_name, force_resend=True)
            else:
                # restore temperature from before opening the window
                orig_temp = self.current_temps[room_name]
                # could be None if we don't knew the temperature before
                # opening the window
                if orig_temp is not None:
                    self.set_temp(room_name, orig_temp, scheduled=False)

    def set_temp(self, room_name, target_temp, scheduled=False):
        """Sets the given target temperature for all thermostats in the
           given room. If scheduled is True, disabled master/schedule
           switches prevent setting the temperature."""

        room = self.cfg["rooms"][room_name]

        if scheduled and \
           (not self.master_switch_enabled() or \
           not self.schedule_switch_enabled(room_name)):
            return

        self.log("<-- [{}] Temperature set to {}.  <{}>"
                 .format(room["friendly_name"], target_temp,
                         "scheduled" if scheduled else "manual"))

        self.current_temps[room_name] = target_temp

        for therm_name, therm in room["thermostats"].items():
            if target_temp == "off":
                value = None
                opmode = therm["opmode_off"]
            else:
                value = target_temp + therm["delta"]
                if therm["min_temp"] is not None and \
                   value < therm["min_temp"]:
                    value = None
                    opmode = therm["opmode_off"]
                else:
                    opmode = therm["opmode_heat"]

            if self.cfg["debug"]:
                self.log("<-- [{}] Setting {}: {}={}, {}={}".format(
                    room["friendly_name"], therm_name,
                    therm["temp_service_attr"],
                    value if value is not None else "<unset>",
                    therm["opmode_service_attr"],
                    opmode))

            attrs = {"entity_id": therm_name,
                     therm["opmode_service_attr"]: opmode}
            self.call_service(therm["opmode_service"], **attrs)
            if value is not None:
                attrs = {"entity_id": therm_name,
                         therm["temp_service_attr"]: value}
                self.call_service(therm["temp_service"], **attrs)

    def get_scheduled_temp(self, room_name):
        """Computes and returns the temperature that is configured for
           the current time in the given room. If no temperature could
           be found in the schedule, None is returned."""

        room = self.cfg["rooms"][room_name]
        when = datetime.datetime.now()
        weekday = when.isoweekday()
        current_time = when.time()
        _time = current_time
        checked_weekdays = set()
        found_slots = []
        # sort slots by time in descending order
        slots = list(room["schedule"])
        slots.sort(key=lambda a: a[1], reverse=True)

        while len(checked_weekdays) < len(util.ALL_WEEKDAYS):
            for slot in slots:
                if weekday in slot[0] and slot[1] <= _time:
                    found_slots.append(slot)
            _time = datetime.time(23, 59, 59)
            checked_weekdays.add(weekday)
            # go one day backwards
            weekday = (weekday - 2) % 7 + 1

        for slot in found_slots:
            temp_expr = slot[2]
            # evaluate the temperature expression
            temp = self.eval_temp_expr(temp_expr[0])
            if self.cfg["debug"]:
                self.log("--- [{}] Evaluated temperature expression {} "
                         "to {}."
                         .format(room["friendly_name"], repr(temp_expr[1]),
                                 temp))
            if temp is not None:
                return temp
            # skip this rule
            if self.cfg["debug"]:
                self.log("--- [{}] Skipping this rule."
                         .format(room["friendly_name"]))

    def set_scheduled_temp(self, room_name, force_resend=False):
        """Sets the temperature that is configured for the current time
           in the given room. If the master or schedule switch is
           turned off or a window is open, this won't do anything.
           If force_resend is True, and the temperature didn't
           change, it is sent to the thermostats anyway."""

        if any((not self.master_switch_enabled(),
                not self.schedule_switch_enabled(room_name),
                room_name in self.reschedule_timers,
                self.get_open_windows(room_name))):
            return

        room = self.cfg["rooms"][room_name]

        temp = self.get_scheduled_temp(room_name)
        if temp is not None:
            if self.current_temps[room_name] != temp or force_resend:
                self.set_temp(room_name, temp, scheduled=True)
            elif self.cfg["debug"]:
                self.log("--- [{}] Not setting temperature to {} "
                         "redundantly."
                         .format(room["friendly_name"], temp))

    def eval_temp_expr(self, temp_expr, extra_env=None):
        """This is a wrapper around util.eval_temp_expr that adds the
           app object to the evaluation environment."""
        if extra_env is None:
            extra_env = {}
        extra_env.setdefault("app", self)
        return util.eval_temp_expr(temp_expr, extra_env=extra_env)

    def cancel_reschedule_timer(self, room_name):
        """Cancels the reschedule timer for the given room, if one
           exists. True is returned if a timer has been cancelled,
           False otherwise."""
        try:
            timer = self.reschedule_timers.pop(room_name)
        except KeyError:
            return False
        if self.cfg["debug"]:
            room = self.cfg["rooms"][room_name]
            self.log("--- [{}] Cancelling re-schedule timer."
                     .format(room["friendly_name"]))
        self.cancel_timer(timer)
        return True

    def check_for_open_window(self, room_name):
        """Checks whether a window is open in the given room and,
           if so, turns the heating off there. The value stored in
           self.current_temps[room_name] is restored after the heating
           has been turned off. It returns True if a window is open,
           False otherwise."""

        room = self.cfg["rooms"][room_name]
        if self.get_open_windows(room_name):
            # window is open, turn heating off
            orig_temp = self.current_temps[room_name]
            off_temp = self.cfg["off_temp"]
            if self.current_temps[room_name] != off_temp:
                self.log("<-- [{}] Turning heating off due to an open "
                         "window.".format(room["friendly_name"]))
                self.set_temp(room_name, off_temp, scheduled=False)
            self.current_temps[room_name] = orig_temp
            return True
        return False

    def eval_temp_expr(self, temp_expr):
        """This method evaluates the given temperature expression.
           The evaluation result is returned."""

        parsed = util.parse_temp(temp_expr)
        if parsed:
            # not an expression, just return the parsed value
            return parsed

        # this is a dynamic temperature expression, evaluate it
        env = {"app": self, "now": datetime.datetime.now()}
        env.update(TIME_EXPRESSION_ENV)
        temp = eval(temp_expr, env)

        if temp is None:
            # None is a special case, pass it through
            return

        parsed = util.parse_temp(temp)
        if not parsed:
            raise ValueError("{} is no valid temperature"
                             .format(repr(parsed)))

        return parsed

    def master_switch_enabled(self):
        """Returns the state of the master switch or True if no master
           switch is configured."""
        master_switch = self.cfg["master_switch"]
        if master_switch:
            return self.get_state(master_switch) == "on"
        return True

    def schedule_switch_enabled(self, room_name):
        """Returns the state of the schedule switch for the given room
           or True if no schedule switch is configured."""
        schedule_switch = self.cfg["rooms"][room_name]["schedule_switch"]
        if schedule_switch:
            return self.get_state(schedule_switch) == "on"
        return True

    def get_open_windows(self, room_name):
        """Returns a list of windo sensors in the given room which
           currently report to be open,"""
        open_sensors = []
        sensors = self.cfg["rooms"][room_name]["window_sensors"]
        for sensor_name, sensor in sensors.items():
            if self.get_state(sensor_name) == "on" or sensor["inverted"]:
                open_sensors.append(sensor_name)
        return open_sensors
