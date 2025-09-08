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
import asyncio
from datetime import datetime, timedelta
from keycloak import KeycloakOpenID
from weheat import ApiClient, Configuration, HeatPumpApi, HeatPumpLogApi, EnergyLogApi, UserApi

# global constants
sAuthUrl = 'https://auth.weheat.nl/auth/'
sApiUrl = 'https://api.weheat.nl'
sRealmName = 'WeHeat'
sCliendId = 'WeheatCommunityAPI'
sClientSecret = ''

class WeHeatPlugin:
    enabled = False

    def __init__(self):
        self._AccessToken = ''
        self._Expiration = datetime.now()
        self._RefreshToken = ''
        self._HeatPumpUuid = ''
        self._KeyCloakOpenId: KeycloakOpenID | None = None
        return

    def login(self):
        Domoticz.Log('Logging into WeHeat backend...')
        self._KeyCloakOpenId = KeycloakOpenID(server_url=sAuthUrl,
                                              client_id=sClientId,
                                              realm_name=sRealmName,
                                              client_secret_key=sClientSecret)
        token_response = self._KeyCloakOpenId.token(Parameter['Username'], Parameter['Password'])
        self._AccessToken = token_response['access_token']
        self._Expiration = datetime.now() + timedelta(seconds = token_response['expires_in'])
        self._RefreshToken = token_response['refresh_token']

    def refreshToken(self):
        if datetime.now() > self._Expiration - timedelta(seconds = 60):
            Domoticz.Log('Refreshing token...')
            token_response = self._KeyCloakOpenId.refresh_token(refresh_token=self._RefreshToken, grant_type='refresh_token')
            self._AccessToken = token_response['access_token']
            self._Expiration = datetime.now() + timedelta(seconds = token_response['expires_in'])
            self._RefreshToken = token_response['refresh_token']

    async def fetchUuid(self):
        config = Configuration(host=sApiUrl, access_token=self._AccessToken)
        async with ApiClient(configuration=config) as client:
            response = await HeatPumpApi(client).api_v1_heat_pumps_get_with_http_info()
            if response.status_code == 200:
                if len(response.data) > 1:
                    Domoticz.Log('WARNING: response data contains more than 1 heatpump, picking the first one!')
                if len(response.data) > 0:
                    self._HeatPumpUuid = response.data[0].id
                    Domoticz.Log("Using heatpump UUID '" + self._HeatPumpUuid + "'")
                else:
                    Domoticz.Error('Failed to connect to WeHeat API with HTTP response: ' +  response.status_code)
                    # Stop / restart the plugin

    async def pollHeatPumpLog(self):
        self.refreshToken()
        Domoticz.Log('Getting a data sample from heatpump')
        config = Configuration(host=sApiUrl, access_token=self._AccessToken)
        async with ApiClient(configuration=config) as client:
            response = await HeatPumpLogApi(client).api_v1_heat_pumps_heat_pump_id_logs_latest_get_with_http_info(
            heat_pump_id=self._HeatPumpUuid)

            if response.status_code == 200:
                for key,value in vars(response.data).items():
                    Domoticz.Log(f'{key} = {value}')

    def onStart(self):
        Domoticz.Log('WeHeat plugin is starting')

        # Create all sensors if they do not exist
        # createDevice("Actual room temperature", "Temp", "t_room")

        # Handle OAuth2 authentication with WeHeat backend
        self.login()

        # Fetch heatpump UUID
        asyncio.get_event_loop().run_until_complete(self.fetchUuid())

        # Schedule a heartbeat to get sensor values

        # Dump config
        if Parameters["Mode6"] != "0":
            Domoticz.Debugging(int(Parameters["Mode6"]))
            DumpConfigToLog()

    def onStop(self):
        Domoticz.Log("WeHeat plugin is stopping")
        self._KeyCloakOpenId.logout(self._RefreshToken)
        # Don't leave anything regarding authentication hanging in memory
        self._AccessToken=''
        self._RefreshToken=''
        self._KeyCloakOpenId = None

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
        Domoticz.Log('Doing work on hearbeat...')
        asyncio.get_event_loop().run_until_complete(self.pollHeatPumpLog())

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
