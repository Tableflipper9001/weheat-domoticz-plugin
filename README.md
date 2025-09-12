# WeHeat plugin for Domoticz
A plugin to read out WeHeat heatpump data.

## Prerequisites
It is advisable to have the domoticz python distribution use a python virtual environment.
This can be achieved by adding PYTHONPATH=<path_to_venv> to the startup script.
See https://wiki.domoticz.com/Using_Python_plugins and
https://zigbeefordomoticz.github.io/wiki/en-eng/HowTo_PythonVirtualEnv.html

Install the following packages in your python environment:
* python-keycloak
* weheat

## Supported sensors
See the plugin description

## Known issues
* When restarting the plugin hits an ImportError on keycloak and weheat.
  This cannot be resolved at this moment in time.
  Restart Domoticz as a work around.
* Only 1 heatpump is supported per account, there is no reason to assume more right now
* No hot water sensors yet

## Release history

### v0.0.1
Initial plugin version, supporting some basic functionality like:
* Authentication
* Heatpump installation type (hybrid / all-electric)
* Basic sensor retrieval
