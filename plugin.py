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
        TODO: add conditional logic for different connection styles (hybrid, all electric, OT boiler, on/off boiler, with vale)
        <h3>Features</h3>
        <ul style="list-style-type:square">
            <li>OpenTherm, hybrid system only</li>
            <li>Read out some sensors, see devices</li>
        </ul>
        <h3>Devices</h3>
        <ul style="list-style-type:square">
            <li>Temperature - Room temperature</li>
            <li>Temperature - Room temperature setpoint</li>
            <li>Temperature - Heating flow temperature</li>
            <li>Temperature - Heating flow temperature setpoint</li>
            <li>Temperature - Heatpump flow temperature</li>
            <li>Temperature - Heatpump return temperature</li>
            <li>Percentage  - COP</li>
            <li>Power - Electrical power</li>
            <li>Power - Heat power</li>
            <li>Power - Power from air</li>
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

import Domoticz
import asyncio
from datetime import datetime, timedelta
from keycloak import KeycloakOpenID
from weheat import ApiClient, Configuration, HeatPumpApi, HeatPumpLogApi
#from weheat import UnauthorizedException, TooManyRequestsException, ServiceException, ApiException

# global constants
sAuthUrl = 'https://auth.weheat.nl/auth/'
sApiUrl = 'https://api.weheat.nl'
sRealmName = 'Weheat'
sClientId = 'WeheatCommunityAPI'
sClientSecret = ''
sThrottleFactor = 4 # * 30 seconds

class WeHeatPlugin:
    enabled = False

    def __init__(self):
        self._AccessToken = ''
        self._Expiration = datetime.now()
        self._RefreshToken = ''
        self._HeatPumpUuid = ''
        self._KeyCloakOpenId: KeycloakOpenID | None = None
        self._loggedIn = False
        self._readyForWork = False
        self._counter = 1

    def login(self):
        Domoticz.Log('Logging into WeHeat backend...')
        self._KeyCloakOpenId = KeycloakOpenID(server_url=sAuthUrl,
                                              client_id=sClientId,
                                              realm_name=sRealmName,
                                              client_secret_key=sClientSecret)
        # try except keycloak.exceptions.KeycloackAuthenticationError + Realm name error
        token_response = self._KeyCloakOpenId.token(Parameters['Username'], Parameters['Password'])
        self._AccessToken = token_response['access_token']
        self._Expiration = datetime.now() + timedelta(seconds = token_response['expires_in'])
        self._RefreshToken = token_response['refresh_token']
        self._loggedIn = True

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
            # TODO try except the HTTP request
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
        Domoticz.Log('Sampling heatpump...')
        config = Configuration(host=sApiUrl, access_token=self._AccessToken)
        async with ApiClient(configuration=config) as client:
#            try:
            response = await HeatPumpLogApi(client).api_v1_heat_pumps_heat_pump_id_logs_latest_get_with_http_info(
            heat_pump_id=self._HeatPumpUuid)
#            except UnauthorizedException as e:
#                 Domoticz.Error('Login to weheat was invalidated, trying to login again...')
#                 self.login()
#            except ServiceException as e:
#                 Domoticz.Error(f'Service error: {e}')
#            except TooManyRequestsException as e:
#                 Domoticz.Error('Too many requests, change the plugin heartbeat!')

            if response.status_code == 200:
                for unit in Devices:
                    Device = Devices[unit]
                    if Device.Options['ExternalId'] in vars(response.data):
                        sValue = vars(response.data)[Device.Options['ExternalId']]
                        sValue = f"{sValue:.1f}"
                        Domoticz.Log(f"{Device.Name} = {sValue}")
                        # TODO: add logic for other devices types when added
                        Device.Update(nValue=0, sValue=sValue)
                    else:
                        Domoticz.Error(f"Sensor '{Device.Name}' not found in HTTP response")
            else:
                Domoticz.Error('Weheat: did not get HTTP response code 200 back')

    def onStart(self):
        Domoticz.Log('WeHeat plugin is starting')

        # Handle OAuth2 authentication with WeHeat backend
        self.login()

        # Fetch heatpump UUID
        asyncio.run(self.fetchUuid())

        # TODO: fetch heatpump configuration

        # Create sensors based on heatpump type if they do not exist
        self.createDevice(1, "Room temperature"                 , "Temperature", "t_room")
        self.createDevice(2, "Room temperature setpoint"        , "Temperature", "t_room_target")
        self.createDevice(3, "Heating flow temperature"         , "Temperature", "t_water_house_in")
        self.createDevice(4, "Heating flow temperature setpoint", "Temperature", "t_thermostat_setpoint")
        self.createDevice(5, "Heatpump flow temperature"        , "Temperature", "t_water_out")
        self.createDevice(6, "Heatpump return temperature"      , "Temperature", "t_water_in")
        self.createDevice(7, "Electrical power"                 , "Usage"      , "cm_mass_power_in")
        self.createDevice(8, "Heat power"                       , "Usage"      , "cm_mass_power_out")
        self.createDevice(9, "Compressor usage"                 , "Percentage" , "rpm")
        #self.createDevice(10, "COP"                              , "Percentage", "TBD")
        #self.createDevice(11, "Power from air"                   , "Power"     , "TBD")

        # Set hearbeat to the maximum, TODO if we violate the amount of samples?
        Domoticz.Heartbeat(30)
        self._readyForWork = True

        # Dump config
        if Parameters["Mode6"] != "0":
            Domoticz.Debugging(int(Parameters["Mode6"]))
            DumpConfigToLog()

    def onStop(self):
        Domoticz.Log("WeHeat plugin is stopping")
        if self._loggedIn:
            self._KeyCloakOpenId.logout(self._RefreshToken)
            self._loggedIn = False
            self._readyForWork = False
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
        if not self._readyForWork:
            return
        self.refreshToken()
        if self._counter % sThrottleFactor == 0:
            self._counter = 1
            asyncio.run(self.pollHeatPumpLog())
        else:
            self._counter += 1

    def createDevice(self, Id, Name, Type, ExternalId):
        if not Id in Devices:
             Domoticz.Log("Creating new sensor '" + Name + "' (" + str(Id) + ") of type '" + Type + "' with external id '" + ExternalId + "'")
             Domoticz.Device(Name=Name, Unit=Id, TypeName=Type, Options={"ExternalId": ExternalId}).Create()

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
