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

1. Copy the file ``heaty_app.py`` to your AppDaemon's ``apps`` directory.
   This is just a one-liner that imports the real app's code and hence does
   never need to be upgraded.

2. Copy the contents of ``apps.yaml.example`` to your ``apps.yaml`` file
   and adapt it as necessary. The example file also contains documentation
   comments explaining what the different settings mean.

3. AppDaemon should have noticed the changes made to ``apps.yaml`` and
   restart its apps automatically.
   
You're done!


Upgrading
---------

Simply pull upgrades via PIP:

::

    pip3 install --upgrade hass-heaty

Note that AppDaemon doesn't detect changes in the imported modules
automatically and needs to be restarted manually after an upgrade.
