"""
This module parses and validates the configuration.
"""

import copy
import json
import os

from jsonschema import Draft4Validator, validators

from . import expr, schedule, util


# file containing the jsonschema of Heaty's configuration
SCHEMA_FILE = os.path.join(
    os.path.dirname(__file__), "data", "config_schema.json"
)
# all constraints that have values in the range_string format
# (see util.expand_range_string)
RANGE_STRING_CONSTRAINTS = ("years", "months", "days", "weeks", "weekdays")


def extend_with_default(validator_class):
    """This extends the given validator class with two special validator
    functions in order to provide automatic setting of default values."""

    validate_properties = validator_class.VALIDATORS["properties"]

    def val_properties(validator, properties, instance, schema):
        """An add-on to the properties validator that sets default values."""

        if not schema.get("ignoreDefaults"):
            for prop, subschema in properties.items():
                # set default value
                if "default" in subschema:
                    # deep-copy because the default value may be mutable
                    # and inserted multiple times
                    value = copy.deepcopy(subschema["default"])
                    instance.setdefault(prop, value)

        for error in validate_properties(
                validator, properties, instance, schema
            ):
            yield error

    def val_ref(validator, ref, instance, schema):
        """A special implementation of the $ref validator that takes over
           all properties from the referring schema to the referenced one."""

        def patch_resolved(resolved):
            """Returns a copy of the given dict with all keys/values
            from schema deep-copied over."""

            patched = copy.deepcopy(resolved)
            for key, val in schema.items():
                if key != "$ref":
                    patched[key] = val
            return patched

        resolve = getattr(validator.resolver, "resolve", None)
        if resolve is None:
            with validator.resolver.resolving(ref) as resolved:
                resolved = patch_resolved(resolved)
                for error in validator.descend(instance, resolved):
                    yield error
        else:
            scope, resolved = validator.resolver.resolve(ref)
            validator.resolver.push_scope(scope)

            resolved = patch_resolved(resolved)

            try:
                for error in validator.descend(instance, resolved):
                    yield error
            finally:
                validator.resolver.pop_scope()

    return validators.extend(
        validator_class, {
            "properties": val_properties,
            "$ref": val_ref,
        }
    )


DefaultValidatingDraft4Validator = extend_with_default(Draft4Validator)


def validate_config(cfg, schema_file=SCHEMA_FILE):
    """Validates the given configuration, filling defaults in if required."""

    schema = json.load(open(schema_file))
    DefaultValidatingDraft4Validator(schema).validate(cfg)

def patch_if_none(obj, key, value):
    """If obj.get(key) is None, this runs obj[key] = value."""

    if obj.get(key) is None:
        obj[key] = value

def parse_config(cfg):
    """Creates a copy of the given config dict, validates it and populates
    it with default values where appropriate."""

    # pylint: disable=too-many-branches,too-many-locals

    cfg = copy.deepcopy(cfg)

    # Yes, this is dirty, but the values we get from yaml can contain
    # None where we expect a dictionary to be.
    # jsonschema can't initialize dicts as values of additionalProperties.
    patch_if_none(cfg, "temp_expression_modules", {})
    for key in cfg["temp_expression_modules"]:
        patch_if_none(cfg["temp_expression_modules"], key, {})
    patch_if_none(cfg, "thermostat_defaults", {})
    patch_if_none(cfg, "window_sensor_defaults", {})
    patch_if_none(cfg, "schedule_prepend", [])
    patch_if_none(cfg, "schedule_append", [])
    patch_if_none(cfg, "rooms", {})
    for key in cfg["rooms"]:
        patch_if_none(cfg["rooms"], key, {})
    for room in cfg["rooms"].values():
        patch_if_none(room, "thermostats", {})
        for key in room["thermostats"]:
            patch_if_none(room["thermostats"], key, {})
        patch_if_none(room, "window_sensors", {})
        for key in room["window_sensors"]:
            patch_if_none(room["window_sensors"], key, {})
        patch_if_none(room, "schedule", [])

    validate_config(cfg)

    cfg["off_temp"] = expr.Temp(cfg["off_temp"])
    min_temp = cfg["thermostat_defaults"].get("min_temp")
    if min_temp is not None:
        cfg["thermostat_defaults"]["min_temp"] = expr.Temp(min_temp)
    for room in cfg["rooms"].values():
        for key in room["thermostats"]:
            min_temp = room["thermostats"][key].get("min_temp")
            if min_temp is not None:
                room["thermostats"][key]["min_temp"] = expr.Temp(min_temp)

    cfg["schedule_prepend"] = parse_schedule(cfg["schedule_prepend"])
    cfg["schedule_append"] = parse_schedule(cfg["schedule_append"])

    # set some initial values
    for room_name, room in cfg["rooms"].items():
        room.setdefault("friendly_name", room_name)
        room["wanted_temp"] = None

        # copy settings from defaults sections to this room
        for therm in room["thermostats"].values():
            for key, val in cfg["thermostat_defaults"].items():
                therm.setdefault(key, val)
            therm["current_temp"] = None
        for sensor in room["window_sensors"].values():
            for key, val in cfg["window_sensor_defaults"].items():
                sensor.setdefault(key, val)

        room["schedule"] = parse_schedule(room["schedule"])
        room["schedule"].items.insert(0, cfg["schedule_prepend"])
        room["schedule"].items.append(cfg["schedule_append"])

    return cfg

def parse_schedule(rules):
    """Builds and returns a Schedule object from the given schedule
    config block."""

    sched = schedule.Schedule()
    for rule in rules:
        constraints = {}
        for name, value in rule.items():
            if name in RANGE_STRING_CONSTRAINTS:
                constraints[name] = util.expand_range_string(value)

        start_time = rule.get("start")
        if start_time is not None:
            start_time = util.parse_time_string(start_time)
        end_time = rule.get("end")

        if end_time is not None:
            end_time = util.parse_time_string(end_time)
        end_plus_days = rule["end_plus_days"]

        temp_expr = rule["temp"]

        rule = schedule.Rule(temp_expr=temp_expr,
                             start_time=start_time,
                             end_time=end_time,
                             end_plus_days=end_plus_days,
                             constraints=constraints)

        sched.items.append(rule)

    return sched
