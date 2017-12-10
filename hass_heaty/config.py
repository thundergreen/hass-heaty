"""
This module parses and validates the configuration.
"""

import copy
import datetime
import json
import os

from jsonschema import Draft4Validator, validators

from . import util


SCHEMA_FILE = os.path.join(
    os.path.dirname(__file__), "data", "config_schema.json"
)


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
               from schema copied over."""
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

    cfg = copy.deepcopy(cfg)

    # Yes, this is dirty, but the values we get from yaml can contain
    # None where we expect a dictionary to be.
    # jsonschema can't initialize dicts as values of additionalProperties.
    patch_if_none(cfg, "reschedule_entities", {})
    for key in cfg["reschedule_entities"]:
        patch_if_none(cfg["reschedule_entities"], key, {})
    patch_if_none(cfg, "thermostat_defaults", {})
    patch_if_none(cfg, "window_sensor_defaults", {})
    patch_if_none(cfg, "rooms", {})
    for key in cfg["rooms"]:
        patch_if_none(cfg["rooms"], key, {})
    for room_name, room in cfg["rooms"].items():
        patch_if_none(room, "thermostats", {})
        for key in room["thermostats"]:
            patch_if_none(room["thermostats"], key, {})
        patch_if_none(room, "window_sensors", {})
        for key in room["window_sensors"]:
            patch_if_none(room["window_sensors"], key, {})
        patch_if_none(room, "schedule", [])

    validate_config(cfg)

    # set some initial values
    for room_name, room in cfg["rooms"].items():
        room.setdefault("friendly_name", room_name)

        # copy settings from defaults sections
        for therm in room["thermostats"].values():
            for key, val in cfg["thermostat_defaults"].items():
                therm.setdefault(key, val)
        for sensor in room["window_sensors"].values():
            for key, val in cfg["window_sensor_defaults"].items():
                sensor.setdefault(key, val)

        # build schedule
        slots = []
        for rule in room["schedule"]:
            spl = rule.strip().split(";")
            weekdays = util.expand_range_string("".join(spl[0].split()))
            for point in spl[1:]:
                spl = point.split("=", 1)
                assert len(spl) == 2
                match = util.TIME_PATTERN.match("".join(spl[0].split()))
                assert match is not None
                daytime = datetime.time(int(match.group(1)),
                                        int(match.group(2)))
                temp_str = "".join(spl[1].split())
                temp = util.parse_temp(temp_str)
                if temp is None:
                    # this is a temperature expression, precompile it
                    temp_str = spl[1].strip()
                    temp = compile(temp_str, "temp_expr", "eval")
                slot = (weekdays, daytime, (temp, temp_str))
                slots.append(slot)
            room["schedule"] = slots

    return cfg