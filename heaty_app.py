# Place this file inside your AppDaemon's apps directory.

# This reloads the hass_heaty module whenever this module is loaded.
# Doing so allows for upgrades of hass-heaty without restarting AppDaemon.
import hass_heaty
try:
    # Python 3.4+
    import importlib
    importlib.reload(hass_heaty)
except AttributeError:
    # Python < 3.4
    import imp
    imp.reload(hass_heaty)
del hass_heaty

# Finally, fetch everything from the real app module.
from hass_heaty import *
