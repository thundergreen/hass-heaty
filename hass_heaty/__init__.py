import datetime
import re

try:
    import appdaemon.appapi as appapi
except ImportError:
    # Handle imports by setup.py to be able to fetch requirements.
    class appapi:
        AppDaemon = object


__all__ = ["Heaty"]
__version__ = "0.1.3"


DEFAULT_OPMODE_HEAT = "Heat"
DEFAULT_OPMODE_OFF = "Off"
DEFAULT_OPMODE_SERVICE = "climate/set_operation_mode"
DEFAULT_OPMODE_SERVICE_ATTR = "operation_mode"
DEFAULT_OPMODE_STATE_ATTR = "operation_mode"
DEFAULT_TEMP_SERVICE = "climate/set_temperature"
DEFAULT_TEMP_SERVICE_ATTR = "temperature"
DEFAULT_TEMP_STATE_ATTR = "temperature"
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

        self.current_temps = {}
        # populate with placeholder values for each room
        for room_name in self.cfg["rooms"]:
            self.current_temps[room_name] = None

        if self.cfg["debug"]:
            self.log("--- Creating schedule timers.")
        for room_name, room in self.cfg["rooms"].items():
            for index, slot in enumerate(room["schedule"]):
                self.run_daily(self.schedule_cb, slot[1],
                        room_name=room_name, slot_index=index)

        if self.cfg["debug"]:
            self.log("--- Registering thermostat state listeners.")
        for room_name, room in self.cfg["rooms"].items():
            for th_name in room["thermostats"]:
                # fetch initial state from thermostats
                state = self.get_state(th_name, attribute="all")
                # populate self.current_temps by simulating a state change
                self.thermostat_state_cb(th_name, "all", state, state,
                        {"room_name": room_name})
                # finally, register the callback
                self.listen_state(self.thermostat_state_cb, th_name,
                        attribute="all", room_name=room_name)

        if self.cfg["debug"]:
            self.log("--- Registering master/schedule switch state listeners.")
        master_switch = self.cfg["master_switch"]
        if master_switch:
            self.listen_state(self.master_switch_cb, master_switch)
        for room_name, room in self.cfg["rooms"].items():
            schedule_switch = room["schedule_switch"]
            if schedule_switch:
                self.listen_state(self.schedule_switch_cb, schedule_switch,
                        room_name=room_name)

        if self.cfg["debug"]:
            self.log("--- Registering window sensor state listeners.")
        for room_name, room in self.cfg["rooms"].items():
            for sensor_name, sensor in room["window_sensors"].items():
                self.listen_state(self.window_sensor_cb, sensor_name,
                        duration=sensor["delay"], room_name=room_name)

        if self.master_switch_enabled():
            self.log("--- Setting initial temperatures where needed.")
            for room_name in self.cfg["rooms"]:
                self.set_scheduled_temp(room_name)
        else:
            self.log("--- Master switch is off, setting no initial values.")

        self.log("--- Initialization done.")

    def schedule_cb(self, kwargs):
        """Is called whenever a schedule timer fires."""
        room = self.cfg["rooms"][kwargs["room_name"]]
        slot = room["schedule"][kwargs["slot_index"]]
        weekday = datetime.datetime.now().isoweekday()
        if weekday not in slot[0]:
            # not today
            return
        target_temp = slot[2]
        self.set_temp(kwargs["room_name"], target_temp, auto=True)

    def thermostat_state_cb(self, entity, attr, old, new, kwargs):
        room_name = kwargs["room_name"]
        room = self.cfg["rooms"][room_name]
        th = room["thermostats"][entity]
        opmode = new["attributes"][th["opmode_state_attr"]]
        if self.cfg["debug"]:
            self.log("<-- {}: attribute {} is {}"
                    .format(entity, th["opmode_state_attr"], opmode))
        if opmode == th["opmode_off"]:
            temp = "off"
        else:
            temp = new["attributes"][th["temp_state_attr"]]
            if self.cfg["debug"]:
                self.log("<-- {}: attribute {} is {}"
                        .format(entity, th["temp_state_attr"], temp))
            temp = float(temp) - th["delta"]

        if temp != self.current_temps[room_name]:
            self.log("<-- Temperature set to {} in {}."
                    .format(temp, room["friendly_name"]))
            self.current_temps[room_name] = temp

    def master_switch_cb(self, entity, attr, old, new, kwargs):
        """Is called when the master switch is toggled."""
        self.log("<-- Master switch turned {}.".format(new))
        for room_name, room in self.cfg["rooms"].items():
            schedule_switch = room["schedule_switch"]
            if new == "on":
                if schedule_switch and \
                   self.cfg["master_controls_schedule_switches"] and \
                   not self.schedule_switch_enabled(room_name):
                    self.log("--> Turning schedule switch for {} on."
                            .format(room["friendly_name"]))
                    # This will automatically invoke a call to
                    # set_scheduled_temp by the schedule_switch_cb.
                    self.turn_on(schedule_switch)
                else:
                    self.set_scheduled_temp(room_name)
            else:
                self.set_temp(room_name, self.cfg["off_temp"], auto=False)

    def schedule_switch_cb(self, entity, attr, old, new, kwargs):
        """Is called when a room's schedule switch is toggled."""
        room_name = kwargs["room_name"]
        self.log("<-- Schedule switch for {} turned {}."
                .format(self.cfg["rooms"][room_name]["friendly_name"], new))
        if new == "on" and self.master_switch_enabled():
            self.set_scheduled_temp(room_name)

    def window_sensor_cb(self, entity, attr, old, new, kwargs):
        """Is called when a window sensor's state has changed."""
        room_name = kwargs["room_name"]
        room = self.cfg["rooms"][room_name]
        sensor = room["window_sensors"][entity]
        action = "opened" if new == "on" or sensor["inverted"] else "closed"
        self.log("<-- Window in {} {}.".format(room["friendly_name"], action))
        if action == "opened":
            if self.schedule_switch_enabled(room_name):
                # just turn off heating, temperature will be restored
                # from schedule anyway
                self.set_temp(room_name, "off", auto=False)
            else:
                # turn heating off, but store the original temperature
                orig_temp = self.current_temps[room_name]
                self.set_temp(room_name, "off", auto=False)
                self.current_temps[room_name] = orig_temp
        else:
            if self.schedule_switch_enabled(room_name):
                # easy, just set the scheduled temperature for now
                self.set_scheduled_temp(room_name)
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

        self.log("--> Setting temperature in {} to {}  [{}]".format(
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
                self.log("--> Setting {}: {}={}, {}={}".format(
                    th_name,
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

    def set_scheduled_temp(self, room_name, force_reset=False):
        """Sets the temperature that is configured for the current time
           in the given room. If the master or schedule switch is
           turned off, this won't do anything. If force_reset is True,
           and the temperature didn't change, it is sent to the
           thermostats anyway."""

        room = self.cfg["rooms"][room_name]

        if not self.master_switch_enabled() or \
           not self.schedule_switch_enabled(room_name):
            return

        now = datetime.datetime.now()
        weekday = now.isoweekday()
        current_time = now.time()
        _time = current_time
        checked_weekdays = set()
        found_slot = None

        while not found_slot and len(checked_weekdays) < len(ALL_WEEKDAYS):
            # sort slots by time in descending order
            slots = list(room["schedule"])
            slots.sort(key=lambda a: a[1], reverse=True)
            # first matching slot will be the latest scheduled temperature
            for slot in slots:
                if weekday in slot[0] and slot[1] <= _time:
                    found_slot = slot
                    break
            _time = datetime.time(23, 59)
            checked_weekdays.add(weekday)
            # go one day backwards
            weekday = (weekday - 2) % 7 + 1

        if found_slot:
            temp = found_slot[2]
            if self.current_temps[room_name] != temp or force_reset:
                self.set_temp(room_name, temp, auto=True)
            elif self.cfg["debug"]:
                self.log("--- Not setting temperature to {} in {} "
                         "redundantly.".format(temp, room["friendly_name"]))

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
            min_temp = th_data.get("min_temp", defaults.get("min_temp"))
            if min_temp is not None:
                min_temp = float(min_temp)
            th["min_temp"] = min_temp
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

        off_temp = str(self.args.get("off_temp", "off")).lower()
        if off_temp != "off":
            off_temp = float(off_temp)
        cfg["off_temp"] = off_temp

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
                cfg["rooms"][room_name]["schedule_switch"] = str(schedule_switch)

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
                spl = "".join(rule.split()).split(";")
                weekdays = expand_range_string(spl[0])
                for point in spl[1:]:
                    spl = point.split("=")
                    assert len(spl) == 2
                    m = TIME_PATTERN.match(spl[0])
                    assert m is not None
                    daytime = datetime.time(int(m.group(1)), int(m.group(2)))
                    temp = float(spl[1])
                    slot = (weekdays, daytime, temp)
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
