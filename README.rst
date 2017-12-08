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

1. Get yourself a nice cup of coffee or tea. You'll surely need it.

2. Copy the file ``heaty_app.py`` to your AppDaemon's ``apps`` directory.
   This is just a stub that imports the real app's code and hence does
   never need to be upgraded or modified again.

3. Copy the contents of ``apps.yaml.example`` to your ``apps.yaml`` file
   and adapt it as necessary. The example file also contains documentation
   comments explaining what the different settings mean.
   There are both a minimal and a full configuration example in that file.
   You'll probably want to get up and running with the minimal one and
   extend your configuration later, since there is really a lot you can do
   if you want. But don't worry, the minimal configuration will probably
   do just fine for now.

4. AppDaemon should have noticed the changes made to ``apps.yaml`` and
   restart its apps automatically.

You're done!


Upgrade
-------

Simply pull upgrades via PIP:

::

    pip3 install --upgrade hass-heaty

Note that AppDaemon doesn't detect changes in the imported modules
automatically and needs to be restarted manually after an upgrade.

**Since v0.1.3:**
Alternatively, touch the ``heaty_app.py`` file which will trigger a
reload of the ``hass_heaty`` module explicitly, like so:

::

    touch ~/.homeassistant/apps/heaty_app.py
