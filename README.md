# WeHeat plugin for Domoticz
A plugin to read out WeHeat heatpump data.

## Prerequisites and installation
It is advisable to have the domoticz python distribution use a python virtual environment.
For example Debian manages its python packages through apt and does not have the neccessary dependencies in apt before Debian 13 (trixie).

To create the virtual environment:
* python(3) -m venv <path to virtual environment> (advise: put it next to the domoticz installation folder
* cd <path to virtual environment>
* . ./bin/activate
* python -m pip install --upgrade pip
* python -m pip install <dependencies> (see list below)
* deactivate
* Add to your startupscript: export PYTHONPATH=<paths>:${PYTHONPATH}

The advised paths to add are:
* <path to virtual environment>
* <path to virtual environment>/lib/site-packages

Also see:
See https://wiki.domoticz.com/Using_Python_plugins and
https://zigbeefordomoticz.github.io/wiki/en-eng/HowTo_PythonVirtualEnv.html

Dependencies of the plugin:
* python-keycloak
* weheat

TODO: Cristalize instruction for systemd configuration file
TODO: Cristalize instruction for windows users

## Supported sensors
See the plugin description in the Domoticz hardware tab

## Known issues
* When restarting the plugin hits an ImportError on keycloak and weheat.
  This cannot be resolved at this moment in time.
  Restart Domoticz as a work around.
* Only 1 heatpump is supported per account, there is no reason to assume more right now
* No hot water sensors yet
* Compressor usage is not a valid percentage as shown in the app

## Release history

### v0.0.x
* Fix COP being a factor instead of a percentage
* Tryfix 1: compressor usage as rpm / power_out -> also not ok

### v0.0.1
Initial plugin version, supporting some basic functionality like:
* Authentication
* Heatpump installation type (hybrid / all-electric)
* Basic sensor retrieval
