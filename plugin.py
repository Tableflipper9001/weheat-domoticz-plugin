# Domoticz plugin for WeHeat devices
#
# Author: Jordy Knubben
#
"""
<plugin key="WeHeat" name="WeHeat" author="Jordy Knubben" version="0.0.1" wikilink="https://wiki.domoticz.com/Plugins" externallink="https://www.weheat.nl/">
    <description>
        <h2>WeHeat</h2><br/>
        A plugin that reads out information about WeHeat heat pumps.<br/>
        Uses the official python client application to access the WeHeat backend TODO link.<br/>
        TODO: determine the throttle limit on the amount of requests
        <h3>Features</h3>
        <ul style="list-style-type:square">
            <li>OpenTherm, hybrid system only</li>
            <li>Read out some sensors, see devices</li>
        </ul>
        <h3>Devices</h3>
        <ul style="list-style-type:square">
            <li>Temperature - Actual room temperature</li>
            <li>Temperature - Room temperature setpoint</li>
            <li>Temperature - House water temperature</li>
            <li>Temperature - Water temperawture house setpoint</li>
            <li>Temperature - Heatpump temperature out</li>
            <li>Temperature - Heatpump temperature in</li>
            <li>Percentage  - COP</li>
            <li>Power - Consumed power</li>
            <li>Power - Heat power</li>
            <li>Power - Heat power air</li>
            <li>Percentage - Compressor usage</li>
        </ul>
        <h3>Configuration</h3>
        TODO config options
    </description>
    <params>
        <param field="Username" label="Username" required="true"/>
        <param field="Password" label="Password" required="true" password="true"/>
        <param field="Mode6" label="Debug" width="150px">
            <options>
                <option label="None" value="0"  default="true" />
                <option label="Python Only" value="2"/>
                <option label="Basic Debugging" value="62"/>
                <option label="Basic+Messages" value="126"/>
                <option label="Queue" value="128"/>
                <option label="Connections Only" value="16"/>
                <option label="Connections+Queue" value="144"/>
                <option label="All" value="-1"/>
            </options>
        </param>
    </params>
</plugin>
"""

import DomoticzEx as Domoticz
#import asyncio
#import datetime
#from keycloak import KeycloakOpenID  # install with pip install python-keycloak
#from weheat import ApiClient, Configuration, HeatPumpApi, HeatPumpLogApi, EnergyLogApi, UserApi

# global constants
sAuthUrl = 'https://auth.weheat.nl/auth/'
sApiUrl = 'https://api.weheat.nl'
sRealmName = 'WeHeat'
sCliendId = 'WeheatCommunityAPI'
sClientSecret = ''

class WeHeatPlugin:
    enabled = False
    mHeatPumpUuid = ''

    def __init__(self):
        return

    def onStart(self):
        Domoticz.Log("WeHeat plugin is starting")

        # Create all sensors if they do not exist
        createDevice("Actual room temperature", "Temp", "t_room")

        # Handle OAuth2 authentication with WeHeat backend and get heatpump UUID

        # Schedule a heartbeat to get sensor values

        # Dump config
        if Parameters["Mode6"] != "0":
            Domoticz.Debugging(int(Parameters["Mode6"]))
            DumpConfigToLog()

    def onStop(self):
        Domoticz.Log("WeHeat plugin is stopping")

    def onConnect(self, Connection, Status, Description):
        Domoticz.Log("onConnect called")

    def onMessage(self, Connection, Data):
        Domoticz.Log("onMessage called")

    def onCommand(self, DeviceID, Unit, Command, Level, Color):
        Domoticz.Log("onCommand called for Device " + str(DeviceID) + " Unit " + str(Unit) + ": Parameter '" + str(Command) + "', Level: " + str(Level))

    def onNotification(self, Name, Subject, Text, Status, Priority, Sound, ImageFile):
        Domoticz.Log("Notification: " + Name + "," + Subject + "," + Text + "," + Status + "," + str(Priority) + "," + Sound + "," + ImageFile)

    def onDisconnect(self, Connection):
        Domoticz.Log("onDisconnect called")

    def onHeartbeat(self):
        Domoticz.Log("onHeartbeat called")

    def createDevice(self, Name, Type, ExternalId)
         if (not Name in Devices):
             id = len(Devices) + 1
             Domoticz.Log("Creating new sensor '" + Name + "' (" + id + ") of type '" + Type + "' with external id '" + ExternalId + "'")
             Domoticz.Device(Name=Name, Unit=id, TypeName=Type, DeviceId=ExternalId).Create()

global _plugin
_plugin = WeHeatPlugin()

def onStart():
    global _plugin
    _plugin.onStart()

def onStop():
    global _plugin
    _plugin.onStop()

def onConnect(Connection, Status, Description):
    global _plugin
    _plugin.onConnect(Connection, Status, Description)

def onMessage(Connection, Data):
    global _plugin
    _plugin.onMessage(Connection, Data)

def onCommand(DeviceID, Unit, Command, Level, Color):
    global _plugin
    _plugin.onCommand(DeviceID, Unit, Command, Level, Color)

def onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile):
    global _plugin
    _plugin.onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile)

def onDisconnect(Connection):
    global _plugin
    _plugin.onDisconnect(Connection)

def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()

# Generic helper functions
def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Debug( "'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Debug("Device count: " + str(len(Devices)))
    for DeviceName in Devices:
        Device = Devices[DeviceName]
        Domoticz.Debug("Device ID:       '" + str(Device.DeviceID) + "'")
        Domoticz.Debug("--->Unit Count:      '" + str(len(Device.Units)) + "'")
        for UnitNo in Device.Units:
            Unit = Device.Units[UnitNo]
            Domoticz.Debug("--->Unit:           " + str(UnitNo))
            Domoticz.Debug("--->Unit Name:     '" + Unit.Name + "'")
            Domoticz.Debug("--->Unit nValue:    " + str(Unit.nValue))
            Domoticz.Debug("--->Unit sValue:   '" + Unit.sValue + "'")
            Domoticz.Debug("--->Unit LastLevel: " + str(Unit.LastLevel))
    return
