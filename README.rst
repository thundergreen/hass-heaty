hass-heaty
==========

A highly-configurable, comfortable to use Home Assistant / appdaemon app
that controls thermostats based on a schedule while still facilitating
manual intervention at any time.


Installation
------------

Install via PIP.

::

    pip3 install hass-heaty


Configuration
-------------

1. Create the file ``heaty.py`` in your appdaemon's apps directory
   with the following content:

   ::

       from hass_heaty import *

2. Copy the contents of ``apps.yaml.example`` to your ``apps.yaml`` file
   and adapt it as necessary. The example file also contains documentation
   comments explaining what the different settings mean.
