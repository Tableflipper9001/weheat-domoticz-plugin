# Domoticz plugin for WeHeat devices
#
# Author: Jordy Knubben
#
"""
<plugin key="WeHeat" name="WeHeat" author="Jordy Knubben" version="0.0.3" wikilink="https://wiki.domoticz.com/Plugins" externallink="https://www.weheat.nl/">
    <description>
        <h2>WeHeat</h2><br/>
        A plugin that reads out information about WeHeat heat pumps.<br/>
        Uses the official python client application to access the
        <a href="https://github.com/wefabricate/wh-python"> WeHeat backend</a><br/>
        <h3>Features</h3>
        <ul style="list-style-type:square">
            <li>Basic determination on setup (hybrid vs. all electric)</li>
            <li>Read out some sensors, see devices for the list</li>
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
            <li>kWh - Electrical power</li>
            <li>kWh - Heat power</li>
            <li>kWh - Power from air</li>
            <li>Percentage - Compressor usage</li>
            <li>Text - Heatpump state</li>
            <li>Text - Cooling state</li>
            <li>Text - Heatpump error</li>
            <li>Hybrid:</li>
            <li>On/off switch - Gas boiler state</li>
            <li>All-electric:</li>
            <li>On/off switch - Electric heater state</li>
        </ul>
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
from enum import IntEnum
from datetime import datetime, timedelta
from keycloak import KeycloakOpenID
from keycloak import KeycloakAuthenticationError, KeycloakPostError
from weheat import BoilerType, HeatPumpModel
from weheat import ApiClient, Configuration, HeatPumpApi, HeatPumpLogApi
from weheat import ApiException

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
        self._Pnom = 0
        self._KeyCloakOpenId: KeycloakOpenID | None = None
        self._loggedIn = False
        self._readyForWork = False
        self._boilerType: ReadableBoilerType | None = None
        self._counter = 1

    def login(self):
        Domoticz.Status('Logging into WeHeat backend...')
        self._KeyCloakOpenId = KeycloakOpenID(server_url=sAuthUrl,
                                              client_id=sClientId,
                                              realm_name=sRealmName,
                                              client_secret_key=sClientSecret)
        # TODO: Check if we can just stop the plugin instead of ghosting CPU cycles
        try:
            token_response = self._KeyCloakOpenId.token(Parameters['Username'], Parameters['Password'])
        except KeycloakAuthenticationError as e:
            Domoticz.Error(f"Failed to authenticate: {e}")
            Domoticz.Error('This plugin will not execute any logic and now ghost CPU cycles')
            return
        except KeycloakPostError as e:
            Domoticz.Error(f"Failed to send login request: {e}")
            Domoticz.Error('This plugin will not execute any logic and now ghost CPU cycles')
            return
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

    async def fetchSetup(self):
        config = Configuration(host=sApiUrl, access_token=self._AccessToken)
        async with ApiClient(configuration=config) as client:
            try:
                response = await HeatPumpApi(client).api_v1_heat_pumps_get_with_http_info()
            except ApiException as e:
                if(e.status >= 500 or e.status <= 599): # Service exception
                    Domoticz.Error(f"Service exception({e.status}), is the WeHeat backend alive?")
                else:
                    Domoticz.Error(f"Unhandled HTTP exception: {e}, please report to plugin maintainer")
                return

            if response.status_code == 200:
                if len(response.data) > 1:
                    Domoticz.Status('WARNING: response data contains more than 1 heatpump, picking the first one!')
                if len(response.data) > 0:
                    self._HeatPumpUuid = response.data[0].id
                    Domoticz.Status("Using heatpump UUID '" + self._HeatPumpUuid + "'")
                    self._boilerType = MAP_BOILER_TYPE[response.data[0].boiler_type]
                    if self._boilerType == ReadableBoilerType.ON_OFF_BOILER or self._boilerType == ReadableBoilerType.OT_BOILER:
                         Domoticz.Status('Detected a hybrid configuration')
                    else:
                         Domoticz.Status('Detected an all-electric configuration')
                    if response.data[0].model == HeatPumpModel.NUMBER_1: # Blackbird P80
                        self._Pnom = 8000
                    elif response.data[0].model == HeatPumpModel.NUMBER_5: # Flint P40
                        self._Pnom = 4000
                    else: # All other models are 6kW nominal rated
                        self._Pnom = 6000
            else:
                Domoticz.Error(f"Unexpected WeHeat API HTTP response code: {response.status_code}")

    async def pollHeatPumpLog(self):
        Domoticz.Log('Sampling heatpump...')
        config = Configuration(host=sApiUrl, access_token=self._AccessToken)
        async with ApiClient(configuration=config) as client:
            try:
                response = await HeatPumpLogApi(client).api_v1_heat_pumps_heat_pump_id_logs_latest_get_with_http_info(
                heat_pump_id=self._HeatPumpUuid)
            except ApiException as e:
                if(e.status == 401): # Unauthorized
                    Domoticz.Error('WeHeat login has expired, trying to login again...')
                    self.login()
                elif(e.status == 429): # Too Many requests
                    Domoticz.Error('Too many requests, ask plugin maintainer to re-adjust sThrottleFactor')
                elif(e.status >= 500 or e.status <= 599): # Service exception
                    Domoticz.Error(f"Service exception({e.status}, is the WeHeat backend alive?")
                else:
                    Domoticz.Error(f"Unhandled HTTP exception: {e}, please report to plugin maintainer")
                return

            if response.status_code == 200:
                for unit in Devices:
                    Device = Devices[unit]
                    if Device.Options['ExternalId'] == 'Math':
                        # Devices that require calculation
                        nValue = 0
                        if "COP" in Device.Name:
                            nValue = (vars(response.data)['cm_mass_power_out'] / vars(response.data)['cm_mass_power_in']) * 100
                        if "Power from air" in Device.Name:
                            nValue = vars(response.data)['cm_mass_power_out'] - vars(response.data)['cm_mass_power_in']
                            nValue = max(nValue, 0)
                        if "Compressor usage" in Device.Name:
                            nValue = (vars(response.data)['rpm'] / self._Pnom) * 100
                        sValue = f"{nValue:.1f}"
                        if 'EnergyMeterMode' in Device.Options: # No energy sensor available, just power so calculate
                            sValue += ';0'
                        Domoticz.Debug(f"{Device.Name} = {sValue}")
                        Device.Update(nValue=0, sValue=sValue)
                    elif Device.Type == 244: # switch
                        sValue = vars(response.data)[Device.Options['ExternalId']]
                        Domoticz.Debug(f"{Device.Name} = {sValue}")
                        Device.Update(nValue=sValue, sValue="")
                    elif Device.Type == 243 and Device.SubType == 19: # text
                        nValue = vars(response.data)[Device.Options['ExternalId']]
                        if "State" in Device.Name: # Warning: Possible name collision here
                            # Requires translation of enum
                            sValue = ConvertHeatPumpStatus(nValue)
                        else:
                            sValue = str(nValue)
                        Domoticz.Debug(f"{Device.Name} = {sValue}")
                        Device.Update(nValue=0, sValue=sValue)
                    elif Device.Options['ExternalId'] in vars(response.data):
                        sValue = vars(response.data)[Device.Options['ExternalId']]
                        sValue = f"{sValue:.1f}"
                        if 'EnergyMeterMode' in Device.Options: # No energy sensor available, just power so calculate
                            sValue += ';0'
                        Domoticz.Debug(f"{Device.Name} = {sValue}")
                        Device.Update(nValue=0, sValue=sValue)
                    else:
                        Domoticz.Error(f"Cannot handle sample for {Device.Name}")
            else:
                Domoticz.Error("Did not expect to receive a success other than 200 from WeHeat backend, got {} instead", response.status_code)

    def onStart(self):
        Domoticz.Status('WeHeat plugin is starting')

        # Handle OAuth2 authentication with WeHeat backend
        self.login()
        if not self._loggedIn:
            return

        # Fetch heatpump configuration
        asyncio.run(self.fetchSetup())
        if self._boilerType == None:
            return

        # Create sensors based on heatpump type if they do not exist
        self.createDevice(1 , "Room temperature"                 , "Temperature", "t_room")
        self.createDevice(2 , "Room temperature setpoint"        , "Temperature", "t_room_target")
        self.createDevice(3 , "Heating flow temperature"         , "Temperature", "t_water_house_in")
        self.createDevice(4 , "Heating flow temperature setpoint", "Temperature", "t_thermostat_setpoint")
        self.createDevice(5 , "Heatpump flow temperature"        , "Temperature", "t_water_out")
        self.createDevice(6 , "Heatpump return temperature"      , "Temperature", "t_water_in")
        self.createDevice(7 , "Electrical power"                 , "kWh"        , "cm_mass_power_in")
        self.createDevice(8 , "Heat power"                       , "kWh"        , "cm_mass_power_out")
        self.createDevice(9 , "Compressor usage"                 , "Percentage" , "Math")
        self.createDevice(10, "COP"                              , "Percentage" , "Math")
        self.createDevice(11, "Power from air"                   , "kWh"        , "Math")
        self.createDevice(12, "State"                            , "Text"       , "state")
        self.createDevice(13, "Cooling state"                    , "Text"       , "cooling_status")
        self.createDevice(14, "Error"                            , "Text"       , "error")
        if self._boilerType == ReadableBoilerType.ON_OFF_BOILER or self._boilerType == ReadableBoilerType.OT_BOILER:
            self.createDevice(15, "Gas boiler state"             , "Switch"     , "control_bridge_status_decoded_gas_boiler")
        else:
            self.createDevice(16, "Electric heating state"       , "Switch"     , "control_bridge_status_decoded_electric_heater")
            # TODO: DHW sensors

        # Set hearbeat to the maximum, multiply the sampling frequency by counter in the hearbeat function
        Domoticz.Heartbeat(30)
        self._readyForWork = True

        # Dump config
        if Parameters["Mode6"] != "0":
            Domoticz.Debugging(int(Parameters["Mode6"]))
            DumpConfigToLog()

    def onStop(self):
        Domoticz.Status("WeHeat plugin is stopping")
        if self._loggedIn:
            self._KeyCloakOpenId.logout(self._RefreshToken)
            self._loggedIn = False
            self._readyForWork = False
        # Don't leave anything regarding authentication hanging in memory
        self._AccessToken=''
        self._RefreshToken=''
        self._KeyCloakOpenId = None

    def onConnect(self, Connection, Status, Description):
        Domoticz.Status("onConnect called")

    def onMessage(self, Connection, Data):
        Domoticz.Status("onMessage called")

    def onCommand(self, DeviceID, Unit, Command, Level, Color):
        Domoticz.Status("onCommand called for Device " + str(DeviceID) + " Unit " + str(Unit) + ": Parameter '" + str(Command) + "', Level: " + str(Level))

    def onNotification(self, Name, Subject, Text, Status, Priority, Sound, ImageFile):
        Domoticz.Status("Notification: " + Name + "," + Subject + "," + Text + "," + Status + "," + str(Priority) + "," + Sound + "," + ImageFile)

    def onDisconnect(self, Connection):
        Domoticz.Status("onDisconnect called")

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
             Domoticz.Status("Creating new sensor '" + Name + "' (" + str(Id) + ") of type '" + Type + "' with external id '" + ExternalId + "'")
             if Type == "Switch":
                 Domoticz.Device(Name=Name, Unit=Id, Type=244, Subtype=73, Switchtype=0, Options={'ExternalId': ExternalId}).Create()
             else:
                 if Type == "kWh":
                     Domoticz.Device(Name=Name, Unit=Id, TypeName=Type, Options={'ExternalId': ExternalId, 'EnergyMeterMode': '1'}).Create()
                 else:
                     Domoticz.Device(Name=Name, Unit=Id, TypeName=Type, Options={'ExternalId': ExternalId}).Create()

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
    return

# Source of definition:
# https://github.com/wefabricate/wh-python/blob/main/weheat/models/boiler_type.py
# Use this for logic so convert to a readable enum
class ReadableBoilerType(IntEnum):
    UNKNOWN = 0
    NO_BOILER = 1
    ON_OFF_BOILER = 2
    OT_BOILER = 3

MAP_BOILER_TYPE = {
    BoilerType.NUMBER_0: ReadableBoilerType.UNKNOWN,
    BoilerType.NUMBER_1: ReadableBoilerType.NO_BOILER,
    BoilerType.NUMBER_2: ReadableBoilerType.ON_OFF_BOILER,
    BoilerType.NUMBER_3: ReadableBoilerType.OT_BOILER
}

# Source of definition:
# https://github.com/wefabricate/wh-python/blob/main/weheat/models/heat_pump_status_enum.py
# Use this for text sensor, so convert to string
def ConvertHeatPumpStatus(number: int) -> str:
    match number:
       case 40:
           return "Standby"
       case 70:
           return "Heating"
       case 90:
           return "Defrost"
       case 130:
           return "Cooling"
       case 150:
           return "Hot water"
       case 160:
           return "Anti legionella"
       case 170:
           return "Selftest"
       case 180:
           return "Manual control"
