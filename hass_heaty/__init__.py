import datetime
import re

try:
    import appdaemon.appapi as appapi
except ImportError:
    # imported by setup.py
    class appapi:
        AppDaemon = object


__version__ = "0.1.0"


DEFAULT_OPMODE_HEAT = "Heat"
DEFAULT_OPMODE_OFF = "Off"
DEFAULT_OPMODE_SERVICE = "climate/set_operation_mode"
DEFAULT_OPMODE_SERVICE_ATTR = "operation_mode"
DEFAULT_TEMP_SERVICE = "climate/set_temperature"
DEFAULT_TEMP_SERVICE_ATTR = "temperature"

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

        self.log("--- Creating schedule timers.")
        for room_name, room in self.cfg["rooms"].items():
            for index, slot in enumerate(room["schedule"]):
                self.run_daily(self.schedule_cb, slot[1],
                        room_name=room_name, slot_index=index)

        self.log("--- Registering master/schedule switch state listeners.")
        master_switch = self.cfg["master_switch"]
        if master_switch:
            self.listen_state(self.master_switch_cb, master_switch)
        for room_name, room in self.cfg["rooms"].items():
            schedule_switch = room["schedule_switch"]
            if schedule_switch:
                self.listen_state(self.schedule_switch_cb, schedule_switch,
                        room_name=room_name)

        if self.master_switch_enabled():
            self.log("--- Setting initial temperatures.")
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

        for th_name, th in room["thermostats"].items():
            if target_temp == "off":
                value = None
                opmode = th["opmode_off"]
            else:
                value = target_temp + th["delta"]
                if th["min_temp"] is not None and value < th["min_temp"]:
                    opmode = th["opmode_off"]
                else:
                    opmode = th["opmode_heat"]

            self.log("--> Setting {}: {}={}, {}={}".format(
                th_name,
                th["temp_service_attr"],
                value if value is not None else "unset",
                th["opmode_service_attr"],
                opmode))
            attrs = {"entity_id": th_name,
                     th["opmode_service_attr"]: opmode}
            self.call_service(th["opmode_service"], **attrs)
            if value is not None:
                attrs = {"entity_id": th_name,
                         th["temp_service_attr"]: value}
                self.call_service(th["temp_service"], **attrs)

    def set_scheduled_temp(self, room_name):
        """Sets the temperature that is configured for the current time
           in the given room. If the master or schedule switch is
           turned off, this won't do anything."""

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
            self.set_temp(room_name, found_slot[2], auto=True)

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

        self.log("--- Parsing configuration.")

        cfg = {}

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

        rooms = self.args.get("rooms", {})
        assert isinstance(rooms, dict)
        cfg["rooms"] = {}
        for room_name, room in rooms.items():
            cfg["rooms"][room_name] = {}

            friendly_name = room.get("friendly_name", room_name)
            assert isinstance(friendly_name, str)
            cfg["rooms"][room_name]["friendly_name"] = friendly_name

            schedule_switch = room.get("schedule_switch")
            cfg["rooms"][room_name]["schedule_switch"] = None
            if schedule_switch is not None:
                cfg["rooms"][room_name]["schedule_switch"] = str(schedule_switch)

            thermostats = room.get("thermostats", {})
            assert isinstance(thermostats, dict)
            cfg["rooms"][room_name]["thermostats"] = {}
            for th_name, th_data in thermostats.items():
                assert isinstance(th_data, dict)
                th = {}
                th["delta"] = float(th_data.get("delta", 0))
                min_temp = th_data.get("min_temp")
                if min_temp is not None:
                    min_temp = float(min_temp)
                th["min_temp"] = min_temp
                th["opmode_heat"] = str(th_data.get("opmode_heat",
                    DEFAULT_OPMODE_HEAT))
                th["opmode_off"] = str(th_data.get("opmode_off",
                    DEFAULT_OPMODE_OFF))
                th["opmode_service"] = str(th_data.get("opmode_service",
                    DEFAULT_OPMODE_SERVICE))
                th["opmode_service_attr"] = str(th_data.get(
                    "opmode_service_attr", DEFAULT_OPMODE_SERVICE_ATTR))
                th["temp_service"] = str(th_data.get("temp_service",
                    DEFAULT_TEMP_SERVICE))
                th["temp_service_attr"] = str(th_data.get(
                    "temp_service_attr", DEFAULT_TEMP_SERVICE_ATTR))
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
