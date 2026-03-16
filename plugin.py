# Domoticz plugin for WeHeat devices
#
# Author: Jordy Knubben
#
"""
<plugin key="WeHeat" name="WeHeat" author="Jordy Knubben" version="0.0.4" wikilink="https://wiki.domoticz.com/Plugins" externallink="https://www.weheat.nl/">
    <description>
        <h2>WeHeat</h2><br/>
        A plugin that reads out information about WeHeat heat pumps.<br/>
        Uses the official python client application to access the
        <a href="https://github.com/wefabricate/wh-python"> WeHeat backend</a><br/>
        <h3>Features</h3>
        <ul style="list-style-type:square">
            <li>Basic determination on setup (hybrid/all electric/with dhw/without dhw)</li>
            <li>Read out current heatpump status</li>
            <li>Read out total energy aggregate</li>
            <li>Import energy aggregate information from history</li>
        </ul>
        <h3>Devices</h3>
        <ul style="list-style-type:square">
            <li>Temperature - Room temperature</li>
            <li>Temperature - Room temperature setpoint</li>
            <li>Temperature - Heating flow temperature</li>
            <li>Temperature - Heating flow temperature setpoint</li>
            <li>Temperature - Heatpump flow temperature</li>
            <li>Temperature - Heatpump return temperature</li>
            <li>Temperature - Outside air temperature in</li>
            <li>Temperature - Outside air temperature out</li>
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
        <param field="ImportDate" label="Import start date (yyyy-mm-dd)" required="false"/>
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
import time
from enum import IntEnum
from datetime import datetime, timedelta, timezone
from keycloak import KeycloakOpenID
from keycloak import KeycloakAuthenticationError, KeycloakPostError
from typing import List
from typing import Optional
from weheat import HeatPumpModel, ApiException
from weheat import ApiClient, Configuration, EnergyLogApi
from weheat.abstractions.heat_pump import HeatPump
from weheat.abstractions.discovery import HeatPumpDiscovery

# global constants
sAuthUrl = 'https://auth.weheat.nl/auth/'
sApiUrl = 'https://api.weheat.nl/third_party'
sRealmName = 'Weheat'
sClientId = 'WeheatCommunityAPI'
sClientSecret = ''
sHeatpumpLogInterval = 4 # * 30 seconds
sEnergyLogInterval =  30 # * 30 seconds
sMinCOP = 0
sMaxCOP = 10 * 100

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
        self._has_ch_boiler = False
        self._hasDhw = False
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
            try:
                token_response = self._KeyCloakOpenId.refresh_token(refresh_token=self._RefreshToken, grant_type='refresh_token')
            except KeycloakPostError as e:
                Domoticz.Error(f"Failed to refresh token with: {e}")
                Domoticz.Error('Trying again next cycle...')
                return
            self._AccessToken = token_response['access_token']
            self._Expiration = datetime.now() + timedelta(seconds = token_response['expires_in'])
            self._RefreshToken = token_response['refresh_token']

    async def fetchSetup(self):
        discovery = HeatPumpDiscovery()
        try:
          heatpumps = await HeatPumpDiscovery.async_discover_active(api_url=sApiUrl, access_token=self._AccessToken)
        except ApiException as e:
            if(e.status >= 500 or e.status <= 599): # Service exception
                Domoticz.Error(f"WeHeat server side exception({e.status}): {e.reason}")
            else:
                Domoticz.Error(f"Unhandled HTTP exception: {e}, please report to plugin maintainer")
            return

        if len(heatpumps) > 1:
            Domoticz.Status('WARNING: response data contains more than 1 heatpump, picking the first one!')
        self._HeatPumpUuid = heatpumps[0].uuid
        self._hasDhw = heatpumps[0].has_dhw
        #self._has_ch_boiler = heatpumps[0].has_ch_boiler # next release
        self._has_ch_boiler = True # for now
        Domoticz.Status("Using heatpump UUID '" + self._HeatPumpUuid + "'")
        #TODO: Lock in for testing, to be fixed before new release
        if self._has_ch_boiler:
            Domoticz.Status('Detected a hybrid configuration')
        else:
            Domoticz.Status('Detected an all-electric configuration')

    async def pollHeatpumpLog(self):
        Domoticz.Log('Sampling heatpump...')
        heatpump = HeatPump(api_url=sApiUrl, uuid=self._HeatPumpUuid)
        try:
            await heatpump.async_get_status(self._AccessToken)
        except ApiException as e:
            if(e.status == 401): # Unauthorized
                Domoticz.Error('WeHeat login has expired, trying to login again...')
                self.login()
            elif(e.status == 429): # Too Many requests
                Domoticz.Error('Too many requests, ask plugin maintainer to re-adjust the Heatpump log interval')
            elif(e.status >= 500 or e.status <= 599): # Service exception
                Domoticz.Error(f"Weheat server side exception({e.status}): {e.reason}")
            else:
                Domoticz.Error(f"Unhandled HTTP exception: {e}, please report to plugin maintainer")
            return

        raw_data = heatpump.raw_content
        for unit in Devices:
            Device = Devices[unit]
            if Device.Options['ExternalId'] == 'Math':
                # Devices that require calculation
                nValue = 0
                if "COP" in Device.Name:
                    nValue = 0 if heatpump.cop is None else heatpump.cop * 100
                    nValue = max(nValue, sMinCOP) # cutoff negative to MinCOP
                    nValue = min(nValue, sMaxCOP) # cutoff positive beyond MaxCOP
                if "Power from air" in Device.Name:
                    nValue = 0 if heatpump.power_output is None or heatpump.power_input is None else heatpump.power_output - heatpump.power_input
                    nValue = max(nValue, 0)
                if "Compressor usage" in Device.Name:
                    nValue = heatpump.compressor_percentage
                sValue = f"{nValue:.1f}"
                if 'EnergyMeterMode' in Device.Options: # No energy sensor available, just power so calculate
                    sValue += ';0'
                Domoticz.Debug(f"{Device.Name} = {sValue}")
                Device.Update(nValue=0, sValue=sValue)
            elif Device.Type == 244: # switch
                sValue = raw_data[Device.Options['ExternalId']]
                Domoticz.Debug(f"{Device.Name} = {sValue}")
                Device.Update(nValue=sValue, sValue="")
            elif Device.Type == 243 and Device.SubType == 19: # text
                nValue = raw_data[Device.Options['ExternalId']]
                if "State" in Device.Name: # Warning: Possible name collision here
                    # Requires translation of enum
                    sValue = ConvertHeatPumpStatus(nValue)
                else:
                    sValue = str(nValue)
                Domoticz.Debug(f"{Device.Name} = {sValue}")
                Device.Update(nValue=0, sValue=sValue)
            elif Device.Options['ExternalId'] in raw_data:
                if raw_data[Device.Options['ExternalId']] is not None:
                    sValue = raw_data[Device.Options['ExternalId']]
                    sValue = f"{sValue:.1f}"
                    if 'EnergyMeterMode' in Device.Options: # No energy sensor available, just power so calculate
                        sValue += ';0'
                    Domoticz.Debug(f"{Device.Name} = {sValue}")
                    Device.Update(nValue=0, sValue=sValue)
            else:
                Domoticz.Error(f"Cannot handle sample for {Device.Name}")

    async def pollEnergyLog(self):
        Domoticz.Log('Updating total energy consumption...')


    async def importEnergyLogHistory(self, start_date: datetime):
        end_date = datetime.now(timezone.utc)
        config = Configuration(host=sApiUrl, access_token=self._AccessToken)
        async with ApiClient(configuration=config) as client:
            try:
                response = await EnergyLogApi(client).api_v1_energy_logs_heat_pump_id_get_with_http_info(heat_pump_id=self._HeatPumpUuid, start_time=start_date, end_time=end_date, interval='Day')
            except ApiException as e:
                if(e.status == 401): # Unauthorized
                    Domoticz.Error('WeHeat login has expired, trying to login again...')
                    self.login()
                elif(e.status == 429): # Too Many requests
                    Domoticz.Error('Too many requests, ask plugin maintainer to re-adjust the Heatpump log interval')
                elif(e.status >= 500 or e.status <= 599): # Service exception
                    Domoticz.Error(f"Weheat server side exception({e.status}): {e.reason}")
                else:
                    Domoticz.Error(f"Unhandled HTTP exception: {e}, please report to plugin maintainer")
                return

            if response.status_code == 200:
                for energy_object in response.data:
                    Domoticz.Status(f"Importing data for date {energy_object['timeBucket']}")
                    # complete import code

    def onStart(self):
        Domoticz.Status('WeHeat plugin is starting')

        # Handle OAuth2 authentication with WeHeat backend
        self.login()
        if not self._loggedIn:
            return

        # Fetch heatpump configuration
        asyncio.run(self.fetchSetup())

        # Create sensors based on heatpump type if they do not exist
        self.createDevice(1 , "Room temperature"                 , "Temperature", "t_room")
        self.createDevice(2 , "Room temperature setpoint"        , "Temperature", "t_room_target")
        self.createDevice(3 , "Heating flow temperature"         , "Temperature", "t_water_house_in")
        self.createDevice(4 , "Heating flow temperature setpoint", "Temperature", "t_thermostat_setpoint")
        self.createDevice(5 , "Heatpump flow temperature"        , "Temperature", "t_water_out")
        self.createDevice(6 , "Heatpump return temperature"      , "Temperature", "t_water_in")
        self.createDevice(17, "Outside air temperature in"       , "Temperature", "t_air_in")
        self.createDevice(18, "Outside air temperature out"      , "Temperature", "t_air_out")
        self.createDevice(7 , "Electrical power"                 , "kWh"        , "cm_mass_power_in")
        self.createDevice(8 , "Heat power"                       , "kWh"        , "cm_mass_power_out")
        self.createDevice(9 , "Compressor usage"                 , "Percentage" , "Math")
        self.createDevice(10, "COP"                              , "Percentage" , "Math")
        self.createDevice(11, "Power from air"                   , "kWh"        , "Math")
        self.createDevice(12, "State"                            , "Text"       , "state")
        self.createDevice(13, "Cooling state"                    , "Text"       , "cooling_status")
        self.createDevice(14, "Error"                            , "Text"       , "error")
        if self._has_ch_boiler:
            self.createDevice(15, "Gas boiler state"             , "Switch"     , "control_bridge_status_decoded_gas_boiler")
        else:
            self.createDevice(16, "Electric heating state"       , "Switch"     , "control_bridge_status_decoded_electric_heater")
        # self.createDevice(20, "Total Energy In", "kWh", "Math")
        # self.createDevice(21, "Heating Energy In", "kWh", "totalEInHeating")
        # self.createDevice(22, "Heating Defrost Energy In", "kWh", "totalEInHeatingDefrost")
        # self.createDevice(23, "Standby Energy In", "kWh", "totalEInStandby")
        # self.createDevice(24, "Cooling Energy In", "kWh", "totalEInCooling")

        # self.createDevice(25, "Total Energy Out", "kWh", "Math")
        # self.createDevice(26, "Heating Energy Out", "kWh", "totalEOutHeating")
        # self.createDevice(27, "Heating Defrost Energy Out", "kWh", "totalEOutHeatingDefrost")
        # self.createDevice(28, "Standby Energy Out", "kWh", "totalEOutStandby")
        # self.createDevice(29, "Cooling Energy Out", "kWh", "totalEOutCooling")
        #
        # self.createDevice(30, "Indoor Unit Standby Energy In", "kWh", "totalEInIUStandby")
        # self.createDevice(31, "Indoor Unit Heating Energy In", "kWh", "totalEInIUHeating")
        # self.createDevice(32, "Indoor Unit Standby Energy In", "kWh", "totalEInIUHeatingDefrost")
        # self.createDevice(33, "Indoor Unit Standby Energy In", "kWh", "totalEInIUCooling")

        # if self._hasDhw:
        #     self.createDevice(40, "DHW Defrost Energy In", "kWh", "totalEInDhwDefrost")
        #     self.createDevice(41, "DHW Energy In", "kWh", "totalEInDhw")
        #     self.createDevice(42, "DHW Indoor Unit Energy In", "kWh", "totalEInIUDhw")
        #     self.createDevice(43, "DHW Defrost Indoor Unit Energy In", "kWh", "totalEInIUDhwDefrost")
        #     self.createDevice(44, "DHW Defrost Energy Out", "kWh", "totalEOutDhwDefrost")
        #     self.createDevice(45, "DHW Energy Out", "kWh", "totalEOutDhw")

        # Set hearbeat to the maximum, multiply the sampling frequency by counter in the hearbeat function
        Domoticz.Heartbeat(30)
        self._readyForWork = True

        if Parameters['ImportDate'] is not None:
            start_date = Parameters['ImportDate']
            timeformat = "%Y-%m-%d"
            try:
                datetime.strptime(start_date, timeformat)
                Domoticz.Log(f"ImportDate specified, starting import from {start_date}...")
                asyncio.run(self.importEnergyLogHistory(start_date))
            except:
                Domoticz.Error("Invalid date time format provided, expecting yyyy-mm-dd")

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
        #self._KeyCloakOpenId = None

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

        if self._counter % sEnergyLogInterval == 0:
            self._counter = 0
            asyncio.run(self.pollEnergyLog())
        if self._counter % sHeatpumpLogInterval == 0:
            asyncio.run(self.pollHeatpumpLog())
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
# https://github.com/wefabricate/wh-python/blob/main/weheat/abstractions/heat_pump.py
# This is apparantly different from https://github.com/wefabricate/wh-python/blob/main/weheat/models/heat_pump_status_enum.py
# Use this for text sensor, so convert to string
def ConvertHeatPumpStatus(number: int) -> str:
    match number:
       case 40:
           return "Standby"
       case 70:
           return "Heating"
       case c if 130 <= c < 140:
           return "Cooling"
       case 150:
           return "Hot water"
       case 160:
           return "Anti legionella"
       case 170:
           return "Selftest"
       case 180:
           return "Manual control"
       case d if 200 <= d <= 240:
           return "Defrost"
       case _:
           return "Unknown (raw value: " + str(number) + ")"
