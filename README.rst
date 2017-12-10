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


A note for hass.io users
~~~~~~~~~~~~~~~~~~~~~~~~

As far as I know, it's not possible to create a plug & play add-on for
hass.io containing Heaty, because it needs to be installed into
AppDaemon's container.

Even though it's untested, the only actions needed in order to install
under hass.io are:

1. Install the appdaemon add-on.
2. Copy the ``hass_heaty`` folder and the file ``heaty_app.py`` into
   the ``apps`` directory of your AppDaemon container. This is also the
   only thing you need to do when upgrading to a newer version of Heaty.
3. Continue with the configuration as normal.


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


Temperature Expressions
-----------------------

Heaty accepts so called temperature expressions in schedules or when
manually setting a temperature via the ``heaty_set_temp`` event.

Temperature expressions are a powerful way of expressing a temperature
in relation to anything you can think of. This power comes from the fact
that temperature expressions are just normal Python expressions which
are evaluated at runtime. When Heaty parses its configuration, all
temperature expressions are pre-compiled to make their later evaluation
more performant.

Temperature expressions must evaluate to one of the following values:

* a ``float`` or ``int`` which is used as the temperature,
* a ``str`` containing a number, which is converted to a ``float``
  automatically for convenience,
* the string ``"off"``, which means just that,
* the string ``"ignore"``, which causes the rule to be ignored and,
  if one exists, the next older one to be evaluated or
* the value ``None``, which simply means no change to the temperature.

There is an object available under the name ``app`` which represents
the ``appdaemon.appapi.AppDaemon`` object of Heaty. You could,
for instance, retrieve values of input sliders via the normal
AppDaemon API.

The following variables are available inside time expressions:

* ``app``: the appdaemon.appapi.AppDaemon object
* ``datetime``: Python's ``datetime`` module
* ``now``: a ``datetime.datetime`` object containing the current date and time
* ``date``: a shortcut for ``now.date()``
* ``time``: a shortcut for ``now.time()``

Examples on how to use temperature expressions are coming soon.


Security considerations
~~~~~~~~~~~~~~~~~~~~~~~

It has to be noted that temperature expressions are evaluated using
Python's ``eval()`` function. In general, this is not suited for code
originating from a source you don't trust completely, because such code
can potentially execute arbitrary commands on your system with the same
permissions and capabilities the AppDaemon process itself has.
That shouldn't be a problem for temperature expressions you write
yourself inside schedules.

This feature could however become problematic if an attacker somehow
is able to emit events on your Home Assistant's event bus. To prevent
temperature expressions from being accepted in the ``heaty_set_temp``
event, processing of such expressions is disabled by default and has
to be enabled explicitly by setting ``untrusted_temp_expressions: true``
in your Heaty configuration.


Re-schedule entities
--------------------

Schedules may be based on the state of some known entities. Heaty can
register a state listener for these entities which triggers a
re-scheduling everytime the state of an entity changes.

These entities go into the ``reschedule_entities`` section of your config:

::

    reschedule_entities:
      input_boolean.some_switch:

Now, whenever the state of ``input_boolean.some_switch`` changes, a
re-scheduling is triggered in all rooms, giving schedule rules the
chance to react on the new state.

Note that Heaty adds a slight delay of 5 seconds afther the entity
has changed before it starts the re-scheduling. This allows correcting
accidental changes of input elements within 5 seconds. Also, several
changes that happen in series will only trigger one single re-scheduling.


Events
------

Heaty introduces two new events it listens to:

* ``heaty_reschedule``: Trigger a re-scheduling of the temperature.
  Parameters are:

  * ``room_name``: the name of the room to re-schedule as defined in Heaty's configuration (not the ``friendly_name``) (optional, default: ``null``, which means all rooms)

* ``heaty_set_temp``: Sets a given temperature in a room.
  Parameters are:

  * ``room_name``: the name of the room as defined in Heaty's configuration (not the ``friendly_name``)
  * ``temp``: a temperature expression
  * ``force_resend``: whether to re-send the temperature to the thermostats even if it hasn't changed due to Heaty's records (optional, default: ``false``)
  * ``reschedule_delay``: a number of minutes after which Heaty should automatically switch back to the schedule (optional, default: the ``reschedule_delay`` set in Heaty's configuration for the particular room)

You can emit these events from your custom Home Assistant automations
or scripts in order to control Heaty's behaviour.

This is an example Home Assistant script that turns the heating in the
room named ``living`` to ``25.0`` degrees and switches back to the
regular schedule after one hour:

::

    alias: Hot for one hour
    sequence:
    - event: heaty_set_temp
      event_data:
        room_name: living
        temp: 25.0
        reschedule_delay: 60


Using Heaty without schedules
-----------------------------

Schedules are not mandatory when using Heaty. It is perfectly valid to
use Heaty just for controlling temperatures in rooms manually while
still benefitting from other features like the open window detection.

To do so, just leave out everything that is related to schedules in
your ``apps.yaml``.
