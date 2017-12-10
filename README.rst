hass-heaty
==========

A highly-configurable, comfortable to use Home Assistant / appdaemon app
that controls thermostats based on a schedule while still facilitating
manual intervention at any time.

**Note:**
Heaty is still a young piece of software which likely contains some bugs.
Please keep that in mind when using it. Bug reports and suggestions are
always welcome. Use the GitHub Issues for this sort of feedback.


Installation
------------

Install from PyPi.

::

    pip3 install hass-heaty

Or clone the GitHub repository to get even the latest changes:

::

    git clone https://github.com/efficiosoft/hass-heaty
    cd hass-heaty
    pip3 install . --upgrade


Configuration
-------------

1. Get yourself a nice cup of coffee or tea. You'll surely need it.

2. Copy the file ``heaty_app.py`` to your AppDaemon's ``apps`` directory.
   This is just a stub that imports the real app's code, making later
   upgrades a little easier.

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

Simply pull upgrades from PyPi:

::

    pip3 install --upgrade hass-heaty

Or, if you installed from the git repository:

::

    cd /path/to/your/clone/of/the/repository
    git pull
    pip3 install . --upgrade

Note that AppDaemon doesn't detect changes in the imported modules
automatically and needs to be restarted manually after an upgrade.

**When upgrading from v0.2.0,** please do also upgrade ``heaty_app.py``.
