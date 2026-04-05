# Domoticz plugin for WeHeat devices
#
# Author: Jordy Knubben
#
"""
<plugin key="WeHeat" name="WeHeat" author="Jordy Knubben" version="0.0.4" shared="true" wikilink="https://wiki.domoticz.com/Plugins" externallink="https://www.weheat.nl/">
    <description>
        <h2>WeHeat</h2><br/>
        A plugin that reads out information about WeHeat heat pumps.<br/>
        Uses the official python client application to access the
        <a href="https://github.com/wefabricate/wh-python"> WeHeat backend</a><br/>
        <h3>Features</h3>
        <ul style="list-style-type:square">
            <li>Determine setup type and create sensors accordingly</li>
            <li>Fill sensors from latest heatpump log with data every 2 minutes</li>
            <li>Fill sensors from total energy log with data every 15 minutes</li>
            <li>Import energy log data to calender table</li>
            <li>Option to import and resync COP values based on energy over instantaneous power consumption</li>
        </ul>
        <h3>Devices</h3>
        <ul style="list-style-type:square">
            <li>Too many to name</li>
        </ul>
    </description>
    <params>
        <param field="Username" label="Username" required="true"/>
        <param field="Password" label="Password" required="true" password="true"/>
        <param field="Mode1" label="Import start date (yyyy-mm-dd)" required="false"/>
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
from datetime import datetime, timedelta, timezone
from keycloak import KeycloakOpenID
from keycloak import KeycloakAuthenticationError, KeycloakPostError
from typing import Optional, Union
from weheat import ApiClient, ApiException, Configuration
from weheat.api import EnergyLogApi
from weheat.abstractions import HeatPumpDiscovery, HeatPump

# global constants
sAuthUrl = 'https://auth.weheat.nl/auth/'
sApiUrl = 'https://api.weheat.nl/third_party'
sRealmName = 'Weheat'
sClientId = 'HomeAssistantAPI'
sClientSecret = 'TqpNpiJDKbGXF8jaL9D1Y8yzl1pI1Fly'
sHeatpumpLogInterval = 4 # 4 * 30 = 2 minutes = Advised by WeHeat
sEnergyLogInterval =  30 # 30 * 30 = 15 minutes = Advised by WeHeat
sMinCOP = 0
sMaxCOP = 10 * 100
sLogSourceHeatpump = "Heatpump"
sLogSourceEnergy = "Energy"
sTimeFormat = "%Y-%m-%d"

class WeHeatPlugin:
    enabled = False

    def __init__(self):
        self._AccessToken = ''
        self._correctImport = False
        self._Expiration = datetime.now()
        self._RefreshToken = ''
        self._HeatPumpUuid = ''
        self._KeyCloakOpenId: KeycloakOpenID | None = None
        self._loggedIn = False
        self._readyForWork = False
        self._hasChBoiler = False
        self._hasDhw = False
        self._hasCooling = False
        self._counter = 1

    def login(self) -> None:
        Domoticz.Status('Logging into WeHeat backend...')
        self._KeyCloakOpenId = KeycloakOpenID(server_url=sAuthUrl,
                                              client_id=sClientId,
                                              realm_name=sRealmName,
                                              client_secret_key=sClientSecret)
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

    def refreshToken(self) -> None:
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

    async def fetchSetup(self) -> None:
        discovery = HeatPumpDiscovery()
        try:
          heatpumps = await HeatPumpDiscovery.async_discover_active(api_url=sApiUrl, access_token=self._AccessToken)
        except ApiException as e:
            self.handleApiException(e)
            return

        if len(heatpumps) > 1:
            Domoticz.Status('WARNING: response data contains more than 1 heatpump, picking the first one!')
        self._HeatPumpUuid = heatpumps[0].uuid
        self._hasDhw = heatpumps[0].has_dhw
        #self._hasChBoiler = heatpumps[0].has_ch_boiler
        self._hasChBoiler = True
        Domoticz.Status("Using heatpump UUID '" + self._HeatPumpUuid + "'")
        if self._hasChBoiler:
            Domoticz.Status('Detected a hybrid configuration')
        else:
            Domoticz.Status('Detected an all-electric configuration')

    def GetValue(self, hp: HeatPump, Id: str) -> Union [int, float, str, None]:
        if hasattr(hp, Id):
            return getattr(hp, Id)

        # TODO: Temporary patch  remove these additions when wh-python is patched
        raw_content = hp.raw_content
        raw_content['total_ein_heating'] = hp.energy_in_heating
        raw_content['total_ein_heating_defrost'] = hp.energy_in_defrost
        #raw_content['total_ein_standby'] = hp.energy_in_standby
        raw_content['total_ein_cooling'] = hp.energy_in_cooling
        raw_content['total_e_out_heating'] = hp.energy_out_heating
        raw_content['total_e_out_heating_defrost'] = hp.energy_out_defrost
        raw_content['total_e_out_cooling'] = hp.energy_out_cooling
        if Id in raw_content:
            return raw_content[Id]
        Domoticz.Error(f"Could not retrieve '{Id}' from HeatPump object")
        return None

    def PostProcess(self, dev: Domoticz.Device, sample: Union [int, float, str], hp: Optional[HeatPump] = None) -> Union [int, float, str]:
        if dev.Type == 243 and dev.SubType == 19 and sample is None:
            sample = 'None'
        if sample is None:
            return None

        if 'COP' in dev.Name:
            #ein = sum(value for key, value in hp.raw_content.items() if key.startswith("total_ein"))
            #eout = sum(value for key, value in hp.raw_content.items() if key.startswith("total_e_out"))
            sample = sample * 100
            sample = max(sample, sMinCOP) # cutoff negative to MinCOP
            sample = min(sample, sMaxCOP) # cutoff positive beyond MaxCOP
        # TODO: Remove, power values are no longer being updated via the API
        if 'Power from air' in dev.Name and hp is not None:
            sample = 0 if hp.power_output is None or hp.power_input is None else hp.power_output - hp.power_input
            sample = max(sample, 0) # cutoff negative values of defrost
        # TODO: Correct energy out calculation for now, check how to add to wh-python without breaking HA integration
        if 'Total Energy Out' in dev.Name and hp is not None:
            # hp.energy_out_defrost is negative in sign, so remove 1x to correct addition in hp.energy_output 
            # and 1x to process it as it should have been
            sample = hp.energy_output + 2 * hp.energy_out_defrost
        if dev.Options['LogSource'] == sLogSourceEnergy:
            if dev.SwitchType == 4:
                sample *= -1
            sample *= 1000
        return sample

    def UpdateDatabase(self, dev: Domoticz.Device, sample: Union [int, float, str]) -> None:
        nValue = 0
        sValue = ""
        # TODO: check if a registry pattern (in form of a dict) can be beneficial here
        # in order to prevent the long if elif else chain
        if (dev.Type == 80 or
           (dev.Type == 243 and dev.SubType == 6)): # Temperature or Percentage
            sValue = f"{sample:.1f}"
        elif dev.Type == 243 and dev.SubType == 19: # Text
            sValue = str(sample)
        elif dev.Type == 243 and dev.SubType == 29: # kWh
            if 'EnergyMeterMode' in dev.Options and dev.Options['EnergyMeterMode'] is '1':
                power, energy = map(float, (dev.sValue or "0;0.0").split(";"))
                energy += sample # WeHeat power sensors are in Watt
                # Dang need 2 params here otherwise the calculaton could go to postprocessing
                sValue = f"{sample:.1f};{energy:.1f}"
            else:
                # WeHeat energy sensors are in kWh
                sValue = f"{0:.1f};{sample:.1f}"
        elif dev.Type == 244: # Switch
            nValue = 0 if not isinstance(sample, int) else sample
        else:
            Domoticz.Error(f"Processing of sensor '{dev.Name}' with Type '{dev.Type}' and SubType '{dev.SubType}' not supported")
            return
        # TODO: Revert to debug when we have sufficient proof everything works as expected
        Domoticz.Log(f"Device name '{dev.Name}', new nValue: '{nValue}', new sValue: '{sValue}'")
        dev.Update(nValue=nValue, sValue=sValue)

    async def pollLog(self, log_type: str) -> None:
        Domoticz.Log(f"Retrieving {log_type} log...")
        heatpump = HeatPump(api_url=sApiUrl, uuid=self._HeatPumpUuid)
        try:
            await heatpump.async_get_status(self._AccessToken)
            #if log_type == sLogSourceHeatpump:
            #    await heatpump.async_get_logs(self._AccessToken)
            #elif log_type == sLogSourceEnergy:
            #    await heatpump.async_get_energy(self._AccessToken)
            #else:
            #    Domoticz.Error(f"Unsupported log type requested: {log_type}. Expected: {sLogSourceHeatpump} or {sLogSourceEnergy}")
            #    return
        except ApiException as e:
            self.handleApiException(e)
            return

        for unit in Devices:
            Device = Devices[unit]
            if Device.Options['LogSource'] != log_type:
                continue
            # TODO: Temporary statement until all Energy log fields can be retrieved reliably
            if Device.Options['LogSource'] == sLogSourceEnergy and ('DHW' in Device.Name or 'Standby Energy In' in Device.Name):
                continue

            if 'ExternalId' in Device.Options and Device.Options['ExternalId'] == 'Math':
                value = self.PostProcess(Device, 0, heatpump)
            else:
                value = self.GetValue(heatpump, Device.Options['ExternalId'])
                value = self.PostProcess(Device, value)

            if value is not None:
                self.UpdateDatabase(Device, value)

    async def importEnergyLogHistory(self, start_date: datetime) -> None:
        end_date = datetime.now(timezone.utc)
        Domoticz.Status(f"Starting Energy Log import from {start_date} to {end_date}...")
        config = Configuration(host=sApiUrl, access_token=self._AccessToken)
        async with ApiClient(configuration=config) as client:
            try:
                response = await EnergyLogApi(client).api_v1_energy_logs_heat_pump_id_get_with_http_info(heat_pump_id=self._HeatPumpUuid, start_time=start_date, end_time=end_date, interval='Day')
            except ApiException as e:
                self.handleApiException(e)
                return

            if response.status_code == 200:
                for unit in Devices:
                    Device = Devices[unit]
                    if 'LogSource' in Device.Options and Device.Options['LogSource'] != sLogSourceEnergy:
                        continue
                    if 'DHW' in Device.Name or 'Standby Energy In' in Device.Name:
                        continue

                    accumulate = 0 # Good for now TBD if we can get the value of the start date
                    if 'AddDBLogEntry' not in Device.Options:
                            Device.Options['AddDBLogEntry'] = 'true'
                            Device.Update(nValue=Device.nValue, sValue=Device.sValue, Options=Device.Options)

                    for energyLog in response.data:
                        energyLog = vars(energyLog)
                        if 'Total Energy In' in Device.Name:
                            today = sum(value for key, value in energyLog.items() if key.startswith("total_ein"))
                        elif 'Total Energy Out' in Device.Name:
                            today = sum(value for key, value in energyLog.items() if key.startswith("total_e_out"))
                        else:
                            today = energyLog[Device.Options['ExternalId']]
                        if Device.SwitchType == 4:
                            today *= -1
                        today *= 1000
                        total = today + accumulate
                        # Don't ask me why this makes sense, but this is stored (in 2025.2) as COUNTER;VALUE;DATE in the table
                        sValue = f"{total:.1f};{today:.1f};{datetime.strftime(energyLog['time_bucket'],'%Y-%m-%d')}"
                        Domoticz.Status(f"Importing: {Device.Name}<=>{sValue}")
                        Device.Update(nValue=0, sValue=sValue)
                        accumulate = total

                    self._correctImport = True
                    Device.Options.pop('AddDBLogEntry', None)
                    # Disable History modification AND make today connect to the just imported data
                    # Here the meaning is different: Power; Energy
                    Device.Update(nValue=Device.nValue, sValue=f"{0:.1f};{total:.1f}", Options=Device.Options)

    def onStart(self):
        Domoticz.Status('WeHeat plugin is starting')

        # Handle OAuth2 authentication with WeHeat backend
        self.login()
        if not self._loggedIn:
            return

        # Fetch heatpump configuration
        asyncio.run(self.fetchSetup())

        # Create sensors based on heatpump type if they do not exist
        self.createDevice(1 , "Room temperature"                     , "Temperature", { 'LogSource': sLogSourceHeatpump, 'ExternalId': 't_room'})
        self.createDevice(2 , "Room temperature setpoint"            , "Temperature", { 'LogSource': sLogSourceHeatpump, 'ExternalId': 't_room_target'})
        self.createDevice(3 , "Heating flow temperature"             , "Temperature", { 'LogSource': sLogSourceHeatpump, 'ExternalId': 't_water_house_in'})
        self.createDevice(4 , "Heating flow temperature setpoint"    , "Temperature", { 'LogSource': sLogSourceHeatpump, 'ExternalId': 't_thermostat_setpoint'})
        self.createDevice(5 , "Heatpump flow temperature"            , "Temperature", { 'LogSource': sLogSourceHeatpump, 'ExternalId': 't_water_out'})
        self.createDevice(6 , "Heatpump return temperature"          , "Temperature", { 'LogSource': sLogSourceHeatpump, 'ExternalId': 't_water_in'})
        self.createDevice(17, "Outside air temperature in"           , "Temperature", { 'LogSource': sLogSourceHeatpump, 'ExternalId': 't_air_in'})
        self.createDevice(18, "Outside air temperature out"          , "Temperature", { 'LogSource': sLogSourceHeatpump, 'ExternalId': 't_air_out'})
        self.createDevice(7 , "Electrical power"                     , "kWh"        , { 'LogSource': sLogSourceHeatpump, 'ExternalId': 'power_input' , 'EnergyMeterMode': '1'})
        self.createDevice(8 , "Heat power"                           , "kWh"        , { 'LogSource': sLogSourceHeatpump, 'ExternalId': 'power_output', 'EnergyMeterMode': '1'})
        self.createDevice(9 , "Compressor usage"                     , "Percentage" , { 'LogSource': sLogSourceHeatpump, 'ExternalId': 'compressor_percentage'})
        self.createDevice(10, "COP"                                  , "Percentage" , { 'LogSource': sLogSourceHeatpump, 'ExternalId': 'cop'})
        self.deleteDevice(11, "Power from air"                       , "kWh"        , { 'LogSource': sLogSourceHeatpump, 'ExternalId': 'Math'}) # Instant power values no longer part of the API
        self.createDevice(12, "State"                                , "Text"       , { 'LogSource': sLogSourceHeatpump, 'ExternalId': 'heat_pump_state'})
        self.createDevice(13, "Cooling state"                        , "Text"       , { 'LogSource': sLogSourceHeatpump, 'ExternalId': 'cooling_status'})
        self.createDevice(14, "Error"                                , "Text"       , { 'LogSource': sLogSourceHeatpump, 'ExternalId': 'error'})
        if self._hasChBoiler:
            self.createDevice(15, "Gas boiler state"                 , "Switch"     , { 'LogSource': sLogSourceHeatpump, 'ExternalId': 'control_bridge_status_decoded_gas_boiler'})
        else:
            self.createDevice(16, "Electric heating state"           , "Switch"     , { 'LogSource': sLogSourceHeatpump, 'ExternalId': 'control_bridge_status_decoded_electric_heater'})

        self.createDevice(20, "Total Energy In"                      , "kWh"        , { 'LogSource': sLogSourceEnergy  , 'ExternalId': 'energy_total'})
        self.createDevice(21, "Heating Energy In"                    , "kWh"        , { 'LogSource': sLogSourceEnergy  , 'ExternalId': 'total_ein_heating'})
        self.createDevice(22, "Heating Defrost Energy In"            , "kWh"        , { 'LogSource': sLogSourceEnergy  , 'ExternalId': 'total_ein_heating_defrost'})
        self.createDevice(23, "Standby Energy In"                    , "kWh"        , { 'LogSource': sLogSourceEnergy  , 'ExternalId': 'total_ein_standby'})
        self.createDevice(24, "Cooling Energy In"                    , "kWh"        , { 'LogSource': sLogSourceEnergy  , 'ExternalId': 'total_ein_cooling'})

        self.createDevice(25, "Total Energy Out"                     , "kWh"        , { 'LogSource': sLogSourceEnergy  , 'ExternalId': 'Math'})
        self.createDevice(26, "Heating Energy Out"                   , "kWh"        , { 'LogSource': sLogSourceEnergy  , 'ExternalId': 'total_e_out_heating'})
        self.createDevice(27, "Heating Defrost Energy Out"           , "kWh"        , { 'LogSource': sLogSourceEnergy  , 'ExternalId': 'total_e_out_heating_defrost'})
        self.createDevice(28, "Cooling Energy Out"                   , "kWh"        , { 'LogSource': sLogSourceEnergy  , 'ExternalId': 'total_e_out_cooling'})

        if self._hasDhw:
            self.createDevice(40, "DHW Top Temperature"              , "Temperature", { 'LogSource': sLogSourceHeatpump, 'ExternalId': 'dhw_top_temperature'})
            self.createDevice(41, "DHW Bottom Temperature"           , "Temperature", { 'LogSource': sLogSourceHeatpump, 'ExternalId': 'dhw_bottom_temperature'})
            self.createDevice(42, "DHW Defrost Energy In"            , "kWh"        , { 'LogSource': sLogSourceEnergy  , 'ExternalId': 'total_ein_dhw_defrost'})
            self.createDevice(43, "DHW Energy In"                    , "kWh"        , { 'LogSource': sLogSourceEnergy  , 'ExternalId': 'total_ein_dhw'})
            self.createDevice(44, "DHW Defrost Energy Out"           , "kWh"        , { 'LogSource': sLogSourceEnergy  , 'ExternalId': 'total_e_out_dhw_defrost'})
            self.createDevice(45, "DHW Energy Out"                   , "kWh"        , { 'LogSource': sLogSourceEnergy  , 'ExternalId': 'total_e_out_dhw'})

        # Set hearbeat to the maximum, multiply the sampling frequency by counter in the hearbeat function
        Domoticz.Heartbeat(30)
        self._readyForWork = True

        if 'Mode1' in Parameters:
            start_date = Parameters['Mode1']

            try:
                datetime.strptime(start_date, sTimeFormat)
                asyncio.run(self.importEnergyLogHistory(start_date))
            except ValueError:
                Domoticz.Error("Invalid date time format provided, expecting yyyy-mm-dd")

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

        if self._correctImport and datetime.now().hour == 0 and datetime.now().minute > 15:
            start = datetime.now()
            start = start - timedelta(minutes=start.minute + 1)
            self.importEnergyLogHistory(datetime.strftime(start, "%Y-%m-%d"))
            self._correctImport = False

        if self._counter % sEnergyLogInterval == 0:
            self._counter = 0
            asyncio.run(self.pollLog(sLogSourceEnergy))
        if self._counter % sHeatpumpLogInterval == 0:
            asyncio.run(self.pollLog(sLogSourceHeatpump))
        self._counter += 1

    def createDevice(self, Id: int, Name: str, Type: str, Options: dict[str, str]) -> None:
        if not Id in Devices:
            Domoticz.Status(f"Creating new sensor '{Name}' ({Id}) of type '{Type}' with options '{Options}'")
            if Type == "Switch":
                Domoticz.Device(Name=Name, Unit=Id, Type=244, Subtype=73, Switchtype=0, Options=Options).Create()
            else:
                Domoticz.Device(Name=Name, Unit=Id, TypeName=Type, Options=Options).Create()
                if ('Cooling' in Name or 'Defrost' in Name) and 'Out' in Name:
                    Device = Devices[Id]
                    Device.Update(nValue=Device.nValue, sValue=Device.sValue, Switchtype=4)
        else:
            Device = Devices[Id]
            if Device.Options != Options:
                Domoticz.Log(f"Updating sensor options for sensor '{Device.Name}'; Old value: '{Device.Options}'; New value: '{Options}'")
                Device.Update(nValue=Device.nValue, sValue=Device.sValue, Options=Options)

    def deleteDevice(self, Id: int, Name: str, Type: str, Options: dict[str, str]) -> None:
        if Id in Devices:
            Domoticz.Status(f"Deleting sensor '{Name}' ({Id}) of type '{Type}' with options '{Options}'")

    def handleApiException(self, e: ApiException):
        if(e.status == 401): # Unauthorized
            Domoticz.Error('WeHeat login has expired, trying to login again...')
            self.login()
        elif(e.status == 429): # Too Many requests
            Domoticz.Error('Request rate limit to the Weheat back-end exceeded')
        elif(e.status >= 500 or e.status <= 599): # Service exception
            Domoticz.Error(f"Weheat server side exception({e.status}): {e}")
        else:
            Domoticz.Error(f"Unhandled HTTP exception: {e}")

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
