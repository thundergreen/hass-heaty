import datetime
import re

try:
    import appdaemon.appapi as appapi
except ImportError:
    # Handle imports by setup.py to be able to fetch requirements.
    class appapi:
        AppDaemon = object


__all__ = ["Heaty"]
__version__ = "0.1.8"


TIME_EXPRESSION_MODULES = {
        "datetime": datetime,
    }

DEFAULT_OPMODE_HEAT = "Heat"
DEFAULT_OPMODE_OFF = "Off"
DEFAULT_OPMODE_SERVICE = "climate/set_operation_mode"
DEFAULT_OPMODE_SERVICE_ATTR = "operation_mode"
DEFAULT_OPMODE_STATE_ATTR = "operation_mode"
DEFAULT_TEMP_SERVICE = "climate/set_temperature"
DEFAULT_TEMP_SERVICE_ATTR = "temperature"
DEFAULT_TEMP_STATE_ATTR = "temperature"
DEFAULT_SCHEDULE_ENTITY_DELAY = 5
DEFAULT_WINDOW_SENSOR_DELAY = 10

ALL_WEEKDAYS = set(range(1, 8))
RANGE_PATTERN = re.compile(r"^(\d+)\-(\d+)$")
TIME_PATTERN = re.compile(r"^([01]\d|2[0123])\:([012345]\d)$")


class Heaty(appapi.AppDaemon):
    def initialize(self):
        """Parses the configuration, initializes all timers and state
           callbacks and sets temperatures in all rooms according to
           the configured schedule."""

        self.log("--- Heaty v{} initialization started.".format(__version__))

        self.parse_config()

        self.reschedule_timers = {}

        self.log("--- Getting current temperatures from thermostats.")
        self.current_temps = {}
        for room_name, room in self.cfg["rooms"].items():
            # set placeholder value in case there are no thermostats
            self.current_temps[room_name] = None
            for th_name, th in room["thermostats"].items():
                if th["ignore_updates"]:
                    # don't consider this thermostat for state updates
                    continue
                # fetch initial state from thermostats
                state = self.get_state(th_name, attribute="all")
                # populate self.current_temps by simulating a state change
                self.thermostat_state_cb(th_name, "all", state, state,
                        {"room_name": room_name, "no_reschedule": True})
                # only consider one thermostat per room
                break

        if self.cfg["debug"]:
            self.log("--- Creating schedule timers.")
        for room_name, room in self.cfg["rooms"].items():
            for slot in room["schedule"]:
                # run 1 second later to guarantee there is no race condition
                t = datetime.time(slot[1].hour, slot[1].minute,
                        slot[1].second + 1)
                if self.cfg["debug"]:
                    self.log("--- [{}] Registering timer at {}."
                            .format(room["friendly_name"], t))
                self.run_daily(self.schedule_cb, t, room_name=room_name)

        if self.cfg["debug"]:
            self.log("--- Registering state listeners for schedule entities.")
        for entity_name, entity in self.cfg["schedule_entities"].items():
            if self.cfg["debug"]:
                self.log("--- Registering state listener for {}, delay {}."
                        .format(entity_name, DEFAULT_SCHEDULE_ENTITY_DELAY))
            self.listen_state(self.schedule_entity_state_cb, entity_name,
                    duration=DEFAULT_SCHEDULE_ENTITY_DELAY)

        if self.cfg["debug"]:
            self.log("--- Registering thermostat state listeners.")
        for room_name, room in self.cfg["rooms"].items():
            for th_name, th in room["thermostats"].items():
                if not th["ignore_updates"]:
                    if self.cfg["debug"]:
                        self.log("--- [{}] Registering state listener for {}."
                                .format(room["friendly_name"], th_name))
                    self.listen_state(self.thermostat_state_cb, th_name,
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
                        duration=sensor["delay"], room_name=room_name)

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
            if self.cfg["debug"]:
                self.log("--- [{}] Ignoring because of running re-schedule "
                         "timer."
                         .format(room["friendly_name"]))
            return

        self.set_scheduled_temp(room_name)

    def reschedule_cb(self, kwargs):
        """Is called whenever a re-schedule timer fires."""

        room_name = kwargs["room_name"]
        room = self.cfg["rooms"][room_name]

        if self.cfg["debug"]:
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
        th = room["thermostats"][entity]

        opmode = new["attributes"].get(th["opmode_state_attr"])
        if self.cfg["debug"]:
            self.log("--> [{}] {}: attribute {} is {}"
                    .format(room["friendly_name"], entity,
                        th["opmode_state_attr"], opmode))

        if opmode is None:
            # don't consider this thermostat
            return
        elif opmode == th["opmode_off"]:
            temp = "off"
        else:
            temp = new["attributes"].get(th["temp_state_attr"])
            if self.cfg["debug"]:
                self.log("--> [{}] {}: attribute {} is {}"
                        .format(room["friendly_name"], entity,
                            th["temp_state_attr"], temp))
            if temp is None:
                # don't consider this thermostat
                return
            temp = float(temp) - th["delta"]

        if temp == self.current_temps[room_name]:
            return

        self.log("--> [{}] Temperature is currently set to {}."
                .format(room["friendly_name"], temp))
        if len(room["thermostats"]) > 1 and \
           room["replicate_changes"] and self.master_switch_enabled():
            if self.cfg["debug"]:
                self.log("<-- [{}] Propagating the change to all "
                         "thermostats.".format(room["friendly_name"]))
            # propagate the change to all other thermostats in the room
            self.set_temp(room_name, temp, auto=False)
        else:
            # just update the records
            self.current_temps[room_name] = temp

        if not self.master_switch_enabled() or \
           not self.schedule_switch_enabled(room_name) or \
           kwargs.get("no_reschedule"):
            return

        if temp == self.get_scheduled_temp(room_name):
            # hit scheduled temperature, cancelling the timer and
            # going back to schedule
            self.cancel_reschedule_timer(room_name)
        elif room["reschedule_delay"]:
            self.cancel_reschedule_timer(room_name)
            # delay is expected to be in seconds by appdaemon
            delay = 60 * room["reschedule_delay"]
            # register a new timer
            if self.cfg["debug"]:
                self.log("--- [{}] Registering re-schedule timer in "
                         "{} seconds."
                         .format(room["friendly_name"], delay))
            timer = self.run_in(self.reschedule_cb, delay,
                    room_name=room_name)
            self.reschedule_timers[room_name] = timer

    def master_switch_cb(self, entity, attr, old, new, kwargs):
        """Is called when the master switch is toggled."""
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
                self.set_temp(room_name, self.cfg["off_temp"], auto=False)

    def schedule_switch_cb(self, entity, attr, old, new, kwargs):
        """Is called when a room's schedule switch is toggled."""

        room_name = kwargs["room_name"]
        room = self.cfg["rooms"][room_name]
        self.log("--> [{}] Schedule switch turned {}."
                .format(room["friendly_name"], new))

        if not self.master_switch_enabled():
            self.log("--- Master switch is off, setting no initial values.")
            return

        if new == "on":
            self.set_scheduled_temp(room_name)
        else:
            self.cancel_reschedule_timer(room_name)

    def window_sensor_cb(self, entity, attr, old, new, kwargs):
        """Is called when a window sensor's state has changed."""

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
        else:
            # restore temperature from before opening the window
            orig_temp = self.current_temps[room_name]
            # could be None if we don't knew the temperature before
            # opening the window
            if orig_temp is not None:
                self.set_temp(room_name, orig_temp, auto=False)

    def set_temp(self, room_name, target_temp, auto=False):
        """Sets the given target temperature for all thermostats in the
           given room. If auto is True, master/schedule switches may
           prevent setting the temperature."""

        room = self.cfg["rooms"][room_name]

        if auto and \
           (not self.master_switch_enabled() or \
           not self.schedule_switch_enabled(room_name)):
            return

        self.log("<-- [{}] Temperature to {}  [{}]".format(
                room["friendly_name"], target_temp,
                "scheduled" if auto else "manual"))

        self.current_temps[room_name] = target_temp

        for th_name, th in room["thermostats"].items():
            if target_temp == "off":
                value = None
                opmode = th["opmode_off"]
            else:
                value = target_temp + th["delta"]
                if th["min_temp"] is not None and value < th["min_temp"]:
                    value = None
                    opmode = th["opmode_off"]
                else:
                    opmode = th["opmode_heat"]

            if self.cfg["debug"]:
                self.log("<-- [{}] Setting {}: {}={}, {}={}".format(
                    room["friendly_name"], th_name,
                    th["temp_service_attr"],
                    value if value is not None else "<unset>",
                    th["opmode_service_attr"],
                    opmode))

            attrs = {"entity_id": th_name,
                     th["opmode_service_attr"]: opmode}
            self.call_service(th["opmode_service"], **attrs)
            if value is not None:
                attrs = {"entity_id": th_name,
                         th["temp_service_attr"]: value}
                self.call_service(th["temp_service"], **attrs)

    def get_scheduled_temp(self, room_name):
        room = self.cfg["rooms"][room_name]
        now = datetime.datetime.now()
        weekday = now.isoweekday()
        current_time = now.time()
        _time = current_time
        checked_weekdays = set()
        found_slots = []
        # sort slots by time in descending order
        slots = list(room["schedule"])
        slots.sort(key=lambda a: a[1], reverse=True)

        while len(checked_weekdays) < len(ALL_WEEKDAYS):
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
                         "to {}.".format(room["friendly_name"],
                             repr(temp_expr[1]), temp))
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

        if any([not self.master_switch_enabled(),
                not self.schedule_switch_enabled(room_name),
                room_name in self.reschedule_timers,
                self.window_open(room_name)]):
            return

        room = self.cfg["rooms"][room_name]

        temp = self.get_scheduled_temp(room_name)
        if temp is not None:
            if self.current_temps[room_name] != temp or force_resend:
                self.set_temp(room_name, temp, auto=True)
            elif self.cfg["debug"]:
                self.log("--- [{}] Not setting temperature to {} "
                         "redundantly."
                         .format(room["friendly_name"], temp))

    def cancel_reschedule_timer(self, room_name):
        """Cancels the reschedule timer for the given room, if one exists."""
        try:
            timer = self.reschedule_timers.pop(room_name)
        except KeyError:
            pass
        else:
            if self.cfg["debug"]:
                room = self.cfg["rooms"][room_name]
                self.log("--- [{}] Cancelling re-schedule timer."
                        .format(room["friendly_name"]))
            self.cancel_timer(timer)

    def check_for_open_window(self, room_name):
        """Checks whether a window is open in the given room and,
           if so, turns the heating off there. It returns True if
           a window is open, False otherwise."""

        room = self.cfg["rooms"][room_name]
        if self.window_open(room_name):
            # window is open, turn heating off
            orig_temp = self.current_temps[room_name]
            off_temp = self.cfg["off_temp"]
            if self.current_temps[room_name] != off_temp:
                self.log("<-- [{}] Turning heating off due to an open "
                         "window.".format(room["friendly_name"]))
                self.set_temp(room_name, off_temp, auto=False)
            self.current_temps[room_name] = orig_temp
            return True
        return False

    def eval_temp_expr(self, temp_expr):
        """This method evaluates the given temperature expression.
           The evaluation result is returned."""

        parsed = parse_temp(temp_expr)
        if parsed:
            # not an expression, just return the parsed value
            return parsed

        # this is a dynamic temperature expression, evaluate it
        env = {"app": self}
        env.update(TIME_EXPRESSION_MODULES)
        temp = eval(temp_expr, env)

        if temp is None:
            # None is a special case, pass it through
            return

        parsed = parse_temp(temp)
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
        """Returns the state of the schedule switch for given room or True
           if no schedule switch is configured."""
        schedule_switch = self.cfg["rooms"][room_name]["schedule_switch"]
        if schedule_switch:
            return self.get_state(schedule_switch) == "on"
        return True

    def window_open(self, room_name):
        """Returns True if a window is open in the given room,
           False otherwise."""
        sensors = self.cfg["rooms"][room_name]["window_sensors"]
        for sensor_name, sensor in sensors.items():
            if self.get_state(sensor_name) == "on" or sensor["inverted"]:
                return True
        return False

    def parse_config(self):
        """Parses the configuration provided via self.args and populates
           self.cfg."""

        def parse_thermostat_config(th_data, defaults=None):
            """Parses and returns the config for a single thermostat.
               Defaults will be used for values, if given as a dict."""

            if defaults is None:
                defaults = {}

            th = {}
            th["delta"] = float(th_data.get("delta",
                defaults.get("delta", 0)))
            th["min_temp"] = parse_temp(th_data.get("min_temp",
                defaults.get("min_temp")))
            th["ignore_updates"] = bool(th_data.get("ignore_updates",
                defaults.get("ignore_updates", False)))
            th["opmode_heat"] = str(th_data.get("opmode_heat",
                defaults.get("opmode_heat", DEFAULT_OPMODE_HEAT)))
            th["opmode_off"] = str(th_data.get("opmode_off",
                defaults.get("opmode_off", DEFAULT_OPMODE_OFF)))
            th["opmode_service"] = str(th_data.get("opmode_service",
                defaults.get("opmode_service", DEFAULT_OPMODE_SERVICE)))
            th["opmode_service_attr"] = str(th_data.get(
                "opmode_service_attr",
                defaults.get("opmode_service_attr",
                    DEFAULT_OPMODE_SERVICE_ATTR)))
            th["opmode_state_attr"] = str(th_data.get(
                "opmode_state_attr",
                defaults.get("opmode_state_attr",
                    DEFAULT_OPMODE_STATE_ATTR)))
            th["temp_service"] = str(th_data.get("temp_service",
                defaults.get("temp_service", DEFAULT_TEMP_SERVICE)))
            th["temp_service_attr"] = str(th_data.get(
                "temp_service_attr",
                defaults.get("temp_service_attr",
                    DEFAULT_TEMP_SERVICE_ATTR)))
            th["temp_state_attr"] = str(th_data.get(
                "temp_state_attr",
                defaults.get("temp_state_attr",
                    DEFAULT_TEMP_STATE_ATTR)))
            return th

        def parse_window_sensor_config(sensor_data, defaults=None):
            """Parses and returns the config for a single window sensor.
               Defaults will be used for values, if given as a dict."""

            if defaults is None:
                defaults = {}

            s = {}
            s["delay"] = int(sensor_data.get("delay",
                defaults.get("delay", DEFAULT_WINDOW_SENSOR_DELAY)))
            s["inverted"] = bool(sensor_data.get("inverted",
                defaults.get("inverted", False)))
            return s

        self.log("--- Parsing configuration.")

        cfg = {}

        cfg["debug"] = bool(self.args.get("debug", False))

        master_switch = self.args.get("master_switch")
        cfg["master_switch"] = None
        if master_switch is not None:
            cfg["master_switch"] = str(master_switch)

        cfg["master_controls_schedule_switches"] = bool(self.args.get(
                "master_controls_schedule_switches", True))

        cfg["off_temp"] = parse_temp(self.args.get("off_temp")) or "off"

        entities = self.args.get("schedule_entities") or {}
        assert isinstance(entities, dict)
        cfg["schedule_entities"] = {}
        for entity, entity_data in entities.items():
            e = {}
            # no settings yet
            cfg["schedule_entities"][entity] = e

        th_data = self.args.get("thermostat_defaults") or {}
        assert isinstance(th_data, dict)
        th = parse_thermostat_config(th_data)
        cfg["thermostat_defaults"] = th

        sensor_data = self.args.get("window_sensor_defaults") or {}
        assert isinstance(sensor_data, dict)
        s = parse_window_sensor_config(sensor_data)
        cfg["window_sensor_defaults"] = s

        rooms = self.args.get("rooms") or {}
        assert isinstance(rooms, dict)
        cfg["rooms"] = {}
        for room_name, room in rooms.items():
            room = room or {}
            assert isinstance(room, dict)
            cfg["rooms"][room_name] = {}

            friendly_name = room.get("friendly_name", room_name)
            assert isinstance(friendly_name, str)
            cfg["rooms"][room_name]["friendly_name"] = friendly_name

            schedule_switch = room.get("schedule_switch")
            cfg["rooms"][room_name]["schedule_switch"] = None
            if schedule_switch is not None:
                cfg["rooms"][room_name]["schedule_switch"] = \
                        str(schedule_switch)

            cfg["rooms"][room_name]["replicate_changes"] = bool(room.get(
                "replicate_changes", True))

            reschedule_delay = int(room.get("reschedule_delay", 0))
            cfg["rooms"][room_name]["reschedule_delay"] = reschedule_delay

            thermostats = room.get("thermostats") or {}
            assert isinstance(thermostats, dict)
            cfg["rooms"][room_name]["thermostats"] = {}
            for th_name, th_data in thermostats.items():
                th_data = th_data or {}
                assert isinstance(th_data, dict)
                th = parse_thermostat_config(th_data,
                        defaults=cfg["thermostat_defaults"])
                cfg["rooms"][room_name]["thermostats"][th_name] = th

            schedule = room.get("schedule", [])
            assert isinstance(schedule, list)
            cfg["rooms"][room_name]["schedule"] = []
            for rule in schedule:
                assert isinstance(rule, str)
                spl = rule.strip().split(";")
                weekdays = expand_range_string("".join(spl[0].split()))
                for point in spl[1:]:
                    spl = point.split("=", 1)
                    assert len(spl) == 2
                    m = TIME_PATTERN.match("".join(spl[0].split()))
                    assert m is not None
                    daytime = datetime.time(int(m.group(1)), int(m.group(2)))
                    temp_str = "".join(spl[1].split())
                    temp = parse_temp(temp_str)
                    if temp is None:
                        # this is a temperature expression, precompile it
                        temp_str = spl[1].strip()
                        temp = compile(temp_str, "temp_expr", "eval")
                    slot = (weekdays, daytime, (temp, temp_str))
                    cfg["rooms"][room_name]["schedule"].append(slot)

            window_sensors = room.get("window_sensors") or {}
            assert isinstance(window_sensors, dict)
            cfg["rooms"][room_name]["window_sensors"] = {}
            for sensor_name, sensor_data in window_sensors.items():
                sensor_data = sensor_data or {}
                assert isinstance(sensor_data, dict)
                s = parse_window_sensor_config(sensor_data,
                        defaults=cfg["window_sensor_defaults"])
                cfg["rooms"][room_name]["window_sensors"][sensor_name] = s

        self.cfg = cfg


def expand_range_string(s):
    """Expands strings of the form '1,2-4,9,11-12 to set(1,2,3,4,9,11,12).
       Any whitespace is ignored."""

    l = set()
    for part in "".join(s.split()).split(","):
        m = RANGE_PATTERN.match(part)
        if m is not None:
            for i in range(int(m.group(1)), int(m.group(2)) + 1):
                l.add(i)
        else:
            l.add(int(part))
    return l

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
