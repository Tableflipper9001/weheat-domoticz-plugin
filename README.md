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
* \<path to virtual environment\>
* \<path to virtual environment\>/lib/site-packages

Also see:
See https://wiki.domoticz.com/Using_Python_plugins and
https://zigbeefordomoticz.github.io/wiki/en-eng/HowTo_PythonVirtualEnv.html

Dependencies of the plugin:
* See requirements.txt

TODO: Cristalize instruction for systemd configuration file
TODO: Cristalize instruction for windows users

## Supported sensors
See the plugin description in the Domoticz hardware tab

## Known issues
* When restarting the plugin hits an ImportError on PyO3 (internal dependency of python-keycloak)
  This cannot be resolved at this moment in time.
    * Please use Domoticz 2026.1 and later, the plugin will load in shared mode to resolve the pyO3 import / sub interpreter errors
* Only 1 heatpump is supported per account, there is no reason to assume more right now
    * If required make an issue, this should be solvable without too much effort (via a mode variable with the id/uuid and multiple hardware entries)
* Update to weheat >2026.2.28 is pending to work with energy aggregate  

## Release history

### v0.0.4
* Refactor most of the plugin
    * Integrate newer wh-python version using the thirdparty API endpoint
    * Perform most sensor calculation via WeHeat abstraction, provided via wh-python
    * Refactor HTTP error handling into its own function and make generic for all calls
    * Add outside air temperature sensors
    * Fix the PyO3 import bug
    * Add TotalEnergyAggregate sensors and add functionality to import the history for these sensors
    * Update sensor options from plugin when out-of-date
    * TODO: Perform COP calculation on 15 minute basis with energy data (power is no longer available)
* Given up on the idea to stop the plugin from itself when initialisation fails. 
  This would accidently trigger in connection blackouts of a couple of minutes and therefor kill the plugin

### v0.0.3
* Fix the compressor usage properly based on the used heatpump (different Pnominal)
* Fix a div by zero since WeHeat removed the idle power from the electrical power
* Change the logging levels to prevent spamming the log

### v0.0.2
* Fix COP being a factor instead of a percentage
* Tryfix 1: compressor usage as rpm / power_out -> also not ok
* Calculated compressor max RPM from percentage in app and rpm sample
* Changed Usage sensor types to kWh sensor (power + calculated energy) so we can track energy
* If you already initialized with v0.0.1 sensors:
    * Stop plugin
    * Delete old sensor
    * Update plugin
    * Restart domoticz to reload the plugin change
    * Start plugin
    * Pray that it puts the new sensors on the same idx

### v0.0.1
Initial plugin version, supporting some basic functionality like:
* Authentication
* Heatpump installation type (hybrid / all-electric)
* Basic sensor retrieval
