"""Fresh reported state, cloud usage, and per-device connection lifecycle."""
from datetime import timedelta
import time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import HomeAssistantError
import logging
from .api_client import DeermaAPIClient, APIError, AuthError
from .mqtt_client import ShadowClient
from .trace import ControlTrace
from .protocol import enum_mapping, packet, mqtt_string, has_i2pro_fields
from .const import DOMAIN

class DeermaCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(hass, logging.getLogger(__name__), name=DOMAIN, update_interval=timedelta(seconds=60))
        self.entry = entry
        self.device = entry.data['device']
        self.identifier = entry.data['device_id']
        self.data = {}
        self.reported = {}
        self.control_trace = ControlTrace()
        self.last_seen = 0
        self.connected = False
        self.reauth_requested = False
        self.usage = None
        self.usage_seen = 0
        self.api = DeermaAPIClient(async_get_clientsession(hass), entry.data['access_token'])
        self.shadow = ShadowClient(async_get_clientsession(hass), self.api, self.identifier,
                                   self.on_state, self.on_connection, self.on_auth)
        self.shadow.on_desired = lambda state: self.control_trace.record("desired_snapshot", state)

    def on_auth(self):
        if not self.reauth_requested:
            self.reauth_requested = True
            self.entry.async_start_reauth(self.hass)

    def on_state(self, state):
        self.control_trace.record("reported", state)
        self.reported.update(state)
        self.last_seen = time.monotonic()
        self.async_set_updated_data(dict(self.reported))

    def on_connection(self, connected):
        self.connected = connected
        if not connected: self.last_seen = 0
        self.async_set_updated_data(dict(self.reported))

    @property
    def live(self):
        return self.connected and bool(self.last_seen) and time.monotonic() - self.last_seen < 180

    async def _async_update_data(self):
        if self.connected and self.shadow.ws:
            try:
                await self.shadow.ws.send_bytes(packet(0x30, mqtt_string(self.shadow.prefix+'get') + b'{}'))
            except (ConnectionError, RuntimeError):
                self.on_connection(False)
        # Usage is optional; unsupported usage API must not disable reported sensors.
        try:
            self.usage = await self.api.total_water(self.identifier)
            self.usage_seen = time.monotonic()
        except AuthError:
            self.usage = None
            self.on_auth()
        except APIError:
            self.usage = None
        return dict(self.reported)

    async def set_option(self, field, label):
        mapping = enum_mapping(self.device, field)
        if label not in mapping: raise HomeAssistantError('该型号未提供此选项映射，未发送指令')
        if not self.live: raise HomeAssistantError('设备状态未同步，未发送指令')
        value = mapping[label]
        if self.reported.get(field) == value: return
        try:
            await self.shadow.set_value(field, value)
        except (ConnectionError, RuntimeError, TimeoutError, ValueError):
            raise HomeAssistantError('未收到设备状态确认，请检查官方 App；指令可能已生效') from None


    async def set_i2pro_values(self, values):
        if not self.live or not has_i2pro_fields(self.reported):
            raise HomeAssistantError('设备状态或机型特征未确认，未发送指令')
        try:
            await self.shadow.set_i2pro_values(values, dict(self.reported))
        except (ConnectionError, RuntimeError, TimeoutError, ValueError):
            raise HomeAssistantError('未收到完整设备确认；请查看官方 App，勿连续重试') from None
        if any(type(self.reported.get(k)) is not int or self.reported[k] != v for k,v in values.items()):
            raise HomeAssistantError('设备返回状态与目标不一致，请查看官方 App')
