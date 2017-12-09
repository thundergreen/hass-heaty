#!/usr/bin/env python3


import os
from setuptools import setup

from hass_heaty import __version__


def read_file(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()


setup(
    name = "hass_heaty",
    version = __version__,
    description = "A highly-configurable, comfortable to use HomeAssistant "
                  "/ appdaemon app that controls thermostats based on a "
                  "schedule while facilitating manual intervention at any "
                  "time.",
    long_description = read_file("README.rst"),
    url = "https://github.com/efficiosoft/hass-heaty",
    author = "Robert Schindler",
    author_email = "r.schindler@efficiosoft.com",
    license = "MIT",
    packages = ["hass_heaty"],
    install_requires = [
        "appdaemon >= 2.1.12",
    ],
    zip_safe = False,
)
