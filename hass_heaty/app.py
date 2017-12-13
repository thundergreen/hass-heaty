"""
A highly-configurable, comfortable to use Home Assistant / appdaemon app
that controls thermostats based on a schedule while still facilitating
manual intervention at any time.
"""

import datetime
import importlib

import appdaemon.appapi as appapi

from . import __version__, config, util


__all__ = ["Heaty"]


class Heaty(appapi.AppDaemon):
    """The Heaty app class for AppDaemon."""

    # pylint: disable=too-many-public-methods

    def __init__(self, *args, **kwargs):
        super(Heaty, self).__init__(*args, **kwargs)
        self.cfg = None
        self.temp_expression_modules = {}
        self.current_temps = {}
        self.reschedule_timers = {}

    def initialize(self):
        """Parses the configuration, initializes all timers, state and
           event callbacks and sets temperatures in all rooms according
           to the configured schedules."""

        # pylint: disable=too-many-branches,too-many-locals,too-many-statements

        self.log("--- Heaty v{} initialization started.".format(__version__))

        self.log("--- Parsing the configuration.")
        self.cfg = config.parse_config(self.args)

        heaty_id = self.cfg["heaty_id"]
        heaty_id_kwargs = {}
        if heaty_id:
            self.log("--- Heaty id is: {}".format(repr(heaty_id)))
            heaty_id_kwargs["heaty_id"] = heaty_id

        if self.cfg["debug"]:
            self.log("--- Importing modules for temperature expressions.")
        for mod_name, mod_data in self.cfg["temp_expression_modules"].items():
            as_name = mod_data.get("as", mod_name)
            if self.cfg["debug"]:
                self.log("--- Importing module {} as {}."
                         .format(repr(mod_name), repr(as_name)))
            try:
                mod = importlib.import_module(mod_name)
            except Exception as err:  # pylint: disable=broad-except
                self.log("!!! Error while importing module {}: {}"
                         .format(repr(mod_name), repr(err)))
                self.log("!!! Module won't be available.")
            else:
                self.temp_expression_modules[as_name] = mod

        self.log("--- Getting current temperatures from thermostats.")
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
            self.log("--- Registering event listener for heaty_reschedule.")
        self.listen_event(self.reschedule_event_cb, "heaty_reschedule",
                          **heaty_id_kwargs)

        if self.cfg["debug"]:
            self.log("--- Registering event listener for heaty_set_temp.")
        self.listen_event(self.set_temp_event_cb, "heaty_set_temp",
                          **heaty_id_kwargs)

        if self.cfg["debug"]:
            self.log("--- Creating schedule timers.")
        for room_name, room in self.cfg["rooms"].items():
            times = set()
            for rule in room["schedule"].unfold():
                for _time in (rule.start_time, rule.end_time):
                    # run 1 second later to avoid race condition, probably
                    # not needed, but it doesn't hurt either
                    _time = datetime.datetime.combine(
                        datetime.date.today(), _time
                    )
                    _time += datetime.timedelta(seconds=1)
                    _time = _time.time()
                    # we collect the times in a set first to avoid registering
                    # multiple timers for the same time
                    times.add(_time)
            for _time in times:
                if self.cfg["debug"]:
                    self.log("--- [{}] Registering timer at {}."
                             .format(room["friendly_name"], _time))
                self.run_daily(self.schedule_cb, _time, room_name=room_name)

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

    def reschedule_timer_cb(self, kwargs):
        """Is called whenever a re-schedule timer fires."""
        room_name = kwargs["room_name"]
        room = self.cfg["rooms"][room_name]
        self.log("--- [{}] Re-schedule timer fired."
                 .format(room["friendly_name"]))
        try:
            del self.reschedule_timers[room_name]
        except KeyError:
            pass
        self.set_scheduled_temp(room_name)

    def reschedule_event_cb(self, event, data, kwargs):
        """This callback executes when a heaty_reschedule event is received.
           data may contain a "room_name", which limits the re-scheduling
           to the given room."""

        room_name = data.get("room_name")
        if room_name:
            if room_name not in self.cfg["rooms"]:
                self.log("!!! [{}] Ignoring heaty_reschedule event for "
                         "unknown room.".format(room_name))
                return
            room_names = [room_name]
        else:
            room_names = self.cfg["rooms"].keys()

        for room_name in room_names:
            room = self.cfg["rooms"][room_name]

            if not self.master_switch_enabled() or \
               not self.schedule_switch_enabled(room_name):
                self.log("--- [{}] Ignoring re-schedule event because "
                         "master or schedule switch is off.")
                continue

            self.log("--- [{}] Re-schedule event received."
                     .format(room["friendly_name"]))
            # delay for 6 seconds to avoid re-scheduling multiple
            # times if multiple events come in shortly
            self.update_reschedule_timer(room_name, reschedule_delay=0.1,
                                         force=True)

    def set_temp_event_cb(self, event, data, kwargs):
        """This callback executes when a heaty_set_temp event is received.
           data must contain a "room_name" and a "temp", which may also
           be a temperature expression. "force_resend" is optional and
           False by default. If it is set to True, the temperature is
           re-sent to the thermostats even if it hasn't changed due to
           Heaty's records."""

        try:
            room_name = data["room_name"]
            temp_expr = data["temp"]
            reschedule_delay = data.get("reschedule_delay")
            if not isinstance(reschedule_delay, (type(None), float, int)):
                raise TypeError()
            if isinstance(reschedule_delay, (float, int)) and \
               reschedule_delay < 0:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            self.log("!!! Ignoring heaty_set_temp event with invalid data: {}"
                     "room.".format(repr(data)))
            return

        if room_name not in self.cfg["rooms"]:
            self.log("!!! [{}] Ignoring heaty_set_temp event for unknown "
                     "room.".format(room_name))
            return

        if not self.cfg["untrusted_temp_expressions"] and \
           util.parse_temp(temp_expr) is None:
            self.log("!!! [{}] Ignoring heaty_set_temp event with an "
                     "untrusted temperature expression. "
                     "(untrusted_temp_expressions = false)".format(room_name))
            return

        room = self.cfg["rooms"][room_name]
        self.log("--- [{}] heaty_set_temp event received, temperature: {}"
                 .format(room["friendly_name"], repr(temp_expr)))

        self.set_manual_temp(room_name, temp_expr,
                             force_resend=bool(data.get("force_resend")),
                             reschedule_delay=reschedule_delay)

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
            self.log("<-- [{}] Propagating the change to all thermostats "
                     "in the room.".format(room["friendly_name"]))
            self.set_temp(room_name, temp, scheduled=False)
        else:
            # just update the records
            self.current_temps[room_name] = temp

        if not kwargs.get("no_reschedule"):
            # only re-schedule when in schedule mode and not
            # explicitly disabled
            self.update_reschedule_timer(room_name)

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
           be found in the schedule (e.g. all rules evaluate to IGNORE),
           None is returned."""

        room = self.cfg["rooms"][room_name]

        for rule in room["schedule"].get_matching_rules(self.datetime()):
            temp = self.eval_temp_expr(rule.temp_expr)
            if self.cfg["debug"]:
                self.log("--- [{}] Evaluated temperature expression {} "
                         "to {}."
                         .format(room["friendly_name"],
                                 repr(rule.temp_expr_raw), temp))

            if temp in (None, util.TEMP_EXPR_IGNORE):
                # skip this rule
                if self.cfg["debug"]:
                    self.log("--- [{}] Skipping this rule."
                             .format(room["friendly_name"]))
                continue

            return temp

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
        if temp is None:
            if self.cfg["debug"]:
                self.log("--- [{}] No suitable temperature found in schedule."
                         .format(room["friendly_name"]))
            return

        if self.current_temps[room_name] != temp or force_resend:
            self.set_temp(room_name, temp, scheduled=True)
        elif self.cfg["debug"]:
            self.log("--- [{}] Not setting temperature to {} "
                     "redundantly."
                     .format(room["friendly_name"], temp))

    def set_manual_temp(self, room_name, temp_expr, force_resend=False,
                        reschedule_delay=None):
        """Sets the temperature in the given room. If the master switch
           is turned off or a window is open, this won't do anything.
           If force_resend is True, and the temperature didn't
           change, it is sent to the thermostats anyway.
           An existing re-schedule timer is cancelled and a new one is
           started if re-schedule timers are configured. reschedule_delay,
           if given, overwrites the value configured for the room."""

        if not self.master_switch_enabled() or \
           self.get_open_windows(room_name):
            return

        room = self.cfg["rooms"][room_name]
        temp = self.eval_temp_expr(temp_expr)
        if self.cfg["debug"]:
            self.log("--- [{}] Evaluated temperature expression {} "
                     "to {}."
                     .format(room["friendly_name"], repr(temp_expr),
                             repr(temp)))

        if temp in (None, util.TEMP_EXPR_IGNORE):
            self.log("--- [{}] Ignoring temperature expression."
                     .format(room["friendly_name"]))
            return

        if self.current_temps[room_name] != temp or force_resend:
            self.set_temp(room_name, temp, scheduled=False)
        elif self.cfg["debug"]:
            self.log("--- [{}] Not setting temperature to {} "
                     "redundantly."
                     .format(room["friendly_name"], temp))

        self.update_reschedule_timer(room_name,
                                     reschedule_delay=reschedule_delay)

    def eval_temp_expr(self, temp_expr, extra_env=None):
        """This is a wrapper around util.eval_temp_expr that adds the
           app object and some helpers to the evaluation environment,
           as well as all configured temp_expression_modules.
           It also catches and logs any exception which is raised
           during evaluation. In this case, None is returned."""

        if extra_env is None:
            extra_env = {}

        extra_env.setdefault("app", self)
        # use date/time provided by appdaemon to support time-traveling
        now = self.datetime()
        extra_env.setdefault("now", now)
        extra_env.setdefault("date", now.date())
        extra_env.setdefault("time", now.time())

        extra_env.update(self.temp_expression_modules)

        try:
            return util.eval_temp_expr(temp_expr, extra_env=extra_env)
        except Exception as err:  # pylint: disable=broad-except
            self.log("!!! Error while evaluating temperature expression: {}"
                     .format(repr(err)))

    def update_reschedule_timer(self, room_name, reschedule_delay=None,
                                force=False):
        """This method cancels an existing re-schedule timer first.
           Then, it checks if either force is set or the current
           temperature in the given room differs from the scheduled
           temperature. If so, a new timer is created according to
           the room's settings. reschedule_delay, if given, overwrites
           the value configured for the room."""

        self.cancel_reschedule_timer(room_name)

        if not self.master_switch_enabled() or \
           not self.schedule_switch_enabled(room_name):
            return

        room = self.cfg["rooms"][room_name]

        self.cancel_reschedule_timer(room_name)

        if reschedule_delay is None:
            reschedule_delay = room["reschedule_delay"]

        temp = self.current_temps.get(room_name)
        if not reschedule_delay or \
           (not force and temp == self.get_scheduled_temp(room_name)):
            return

        delta = datetime.timedelta(minutes=reschedule_delay)
        when = self.datetime() + delta
        self.log("--- [{}] Re-scheduling not before {} ({})."
                 .format(room["friendly_name"],
                         util.format_time(when.time()), delta))
        timer = self.run_at(self.reschedule_timer_cb, when,
                            room_name=room_name)
        self.reschedule_timers[room_name] = timer

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
