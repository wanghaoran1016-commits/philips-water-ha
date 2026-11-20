"""Offline regression tests for CubeUV (ADD6862) compatibility."""
import asyncio
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / 'custom_components' / 'deerma_water'

CUBEUV_DEVICE = {
    'deviceNickname': 'ADD6862',
    'device': {'id': 'example-cubeuv', 'name': 'CubeUV01', 'wifiVersion': 'A1_0C-0.8.6'},
    'product': {'modelName': 'ADD6862', 'name': 'CubeUV01', 'seriesName': 'CubeUV'},
    'showAttributes': [
        {
            'id': 'SetTemp',
            'valueMapping': {
                '0': {'en': 'Normal', 'zh-CN': '常温'},
                '1': '45℃',
                '2': '85℃',
                '3': '99℃',
            },
        },
        {
            'id': 'SetOutlet',
            'valueMapping': {'0': '150mL', '1': '200mL', '2': '300mL'},
        },
    ],
}

I2PRO_DEVICE = {
    'deviceNickname': 'i2 Pro',
    'device': {'id': 'example-i2pro', 'name': 'I2Pro', 'wifiVersion': '0.1.0'},
    'product': {'modelName': 'ADD8666', 'name': 'I2Pro', 'seriesName': 'Ice'},
    'showAttributes': [],
}


def _build_ha_stubs():
    class CoordinatorEntity:
        def __init__(self, coordinator):
            self.coordinator = coordinator

    class DataUpdateCoordinator:
        def __init__(self, hass, logger, *, name=None, update_interval=None):
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval
            self._listeners = []

        def async_set_updated_data(self, data):
            self.data = data
            for cb in list(self._listeners):
                cb()

        def async_add_listener(self, cb):
            self._listeners.append(cb)

            def unsub():
                if cb in self._listeners:
                    self._listeners.remove(cb)

            return unsub

    def DeviceInfo(**kwargs):
        return dict(kwargs)

    class HomeAssistantError(Exception):
        pass

    class SelectEntity:
        pass

    class SensorEntity:
        pass

    class BinarySensorEntity:
        pass

    class ButtonEntity:
        pass

    class SwitchEntity:
        pass

    class FakeEntityRegistry:
        def __init__(self, items=None):
            self.items = dict(items or {})

        def async_get_entity_id(self, domain, platform, unique_id):
            for entity_id, item in self.items.items():
                if entity_id.startswith(f'{domain}.') and item.unique_id == unique_id:
                    return entity_id
            return None

        def async_get(self, entity_id):
            return self.items.get(entity_id)

        def async_update_entity(self, entity_id, **kwargs):
            item = self.items[entity_id]
            for k, v in kwargs.items():
                setattr(item, k, v)
            return item

    ha = types.ModuleType('homeassistant')
    ha_const = types.ModuleType('homeassistant.const')
    ha_const.Platform = types.SimpleNamespace(
        SELECT='select',
        SENSOR='sensor',
        BINARY_SENSOR='binary_sensor',
        BUTTON='button',
        SWITCH='switch',
    )
    ha_core = types.ModuleType('homeassistant.core')
    ha_core.callback = lambda fn: fn
    ha_exc = types.ModuleType('homeassistant.exceptions')
    ha_exc.HomeAssistantError = HomeAssistantError
    ha_helpers = types.ModuleType('homeassistant.helpers')
    ha_uc = types.ModuleType('homeassistant.helpers.update_coordinator')
    ha_uc.CoordinatorEntity = CoordinatorEntity
    ha_uc.DataUpdateCoordinator = DataUpdateCoordinator
    ha_aio = types.ModuleType('homeassistant.helpers.aiohttp_client')
    ha_aio.async_get_clientsession = lambda _: None
    ha_entity = types.ModuleType('homeassistant.helpers.entity')
    ha_entity.DeviceInfo = DeviceInfo
    ha_entity.EntityCategory = types.SimpleNamespace(CONFIG='config', DIAGNOSTIC='diagnostic')
    ha_er = types.ModuleType('homeassistant.helpers.entity_registry')
    ha_er.RegistryEntryDisabler = types.SimpleNamespace(INTEGRATION='integration', USER='user')
    ha_er.async_get = lambda hass: hass._er
    ha_components = types.ModuleType('homeassistant.components')
    ha_select = types.ModuleType('homeassistant.components.select')
    ha_select.SelectEntity = SelectEntity
    ha_sensor = types.ModuleType('homeassistant.components.sensor')
    ha_sensor.SensorEntity = SensorEntity
    ha_sensor.SensorDeviceClass = types.SimpleNamespace(TEMPERATURE='temperature', WATER='water')
    ha_sensor.SensorStateClass = types.SimpleNamespace(MEASUREMENT='measurement', TOTAL_INCREASING='total_increasing')
    ha_bs = types.ModuleType('homeassistant.components.binary_sensor')
    ha_bs.BinarySensorEntity = BinarySensorEntity
    ha_bs.BinarySensorDeviceClass = types.SimpleNamespace(PROBLEM='problem', RUNNING='running')
    ha_btn = types.ModuleType('homeassistant.components.button')
    ha_btn.ButtonEntity = ButtonEntity
    ha_sw = types.ModuleType('homeassistant.components.switch')
    ha_sw.SwitchEntity = SwitchEntity

    package = types.ModuleType('deerma_cubeuv_test')
    package.__path__ = [str(PKG)]

    stub_map = {
        'deerma_cubeuv_test': package,
        'homeassistant': ha,
        'homeassistant.const': ha_const,
        'homeassistant.core': ha_core,
        'homeassistant.exceptions': ha_exc,
        'homeassistant.helpers': ha_helpers,
        'homeassistant.helpers.update_coordinator': ha_uc,
        'homeassistant.helpers.aiohttp_client': ha_aio,
        'homeassistant.helpers.entity': ha_entity,
        'homeassistant.helpers.entity_registry': ha_er,
        'homeassistant.components': ha_components,
        'homeassistant.components.select': ha_select,
        'homeassistant.components.sensor': ha_sensor,
        'homeassistant.components.binary_sensor': ha_bs,
        'homeassistant.components.button': ha_btn,
        'homeassistant.components.switch': ha_sw,
    }
    return stub_map, FakeEntityRegistry


def _load_pkg_modules():
    stub_map, FakeEntityRegistry = _build_ha_stubs()
    spec = importlib.util.spec_from_file_location(
        'deerma_cubeuv_test',
        str(PKG / '__init__.py'),
        submodule_search_locations=[str(PKG)],
    )
    pkg = importlib.util.module_from_spec(spec)
    stub_map['deerma_cubeuv_test'] = pkg
    patcher = patch.dict(sys.modules, stub_map)
    patcher.start()
    spec.loader.exec_module(pkg)
    mods = {
        name: importlib.import_module(f'deerma_cubeuv_test.{name}')
        for name in ('protocol', 'mqtt_client', 'coordinator', 'select', 'sensor', 'binary_sensor')
    }
    mods['init'] = pkg
    return patcher, mods, FakeEntityRegistry


class CubeUVProtocolTests(unittest.TestCase):
    def setUp(self):
        patcher, mods, _ = _load_pkg_modules()
        self.addCleanup(patcher.stop)
        self.p = mods['protocol']

    def test_is_cubeuv_detection(self):
        self.assertTrue(self.p.is_cubeuv(CUBEUV_DEVICE))
        self.assertTrue(self.p.is_cubeuv({'product': {'modelName': 'ADD6862'}}))
        self.assertFalse(self.p.is_cubeuv(I2PRO_DEVICE))
        self.assertFalse(self.p.is_cubeuv({}))
        self.assertFalse(self.p.is_cubeuv(None))
        self.assertFalse(self.p.is_cubeuv({'product': 'bad'}))

    def test_match_reported_option_exact_and_numeric_telemetry(self):
        temp_map = self.p.enum_mapping(CUBEUV_DEVICE, 'SetTemp')
        outlet_map = self.p.enum_mapping(CUBEUV_DEVICE, 'SetOutlet')

        self.assertEqual(self.p.match_reported_option('SetTemp', 0, temp_map), '常温')
        self.assertEqual(self.p.match_reported_option('SetTemp', 1, temp_map), '45℃')
        self.assertEqual(self.p.match_reported_option('SetOutlet', 1, outlet_map), '200mL')

        reported = {'InputTemp': 20, 'BoilingPoint': 99}
        self.assertEqual(self.p.match_reported_option('SetTemp', 20, temp_map, reported), '常温')
        self.assertEqual(self.p.match_reported_option('SetTemp', 45, temp_map, reported), '45℃')
        self.assertEqual(self.p.match_reported_option('SetTemp', 85, temp_map, reported), '85℃')
        self.assertEqual(self.p.match_reported_option('SetTemp', 99, temp_map, reported), '99℃')
        self.assertEqual(
            self.p.match_reported_option('SetTemp', 96, temp_map, {'InputTemp': 20, 'BoilingPoint': 96}),
            '99℃',
        )
        self.assertEqual(self.p.match_reported_option('SetOutlet', 150, outlet_map), '150mL')
        self.assertEqual(self.p.match_reported_option('SetOutlet', 200, outlet_map), '200mL')
        self.assertEqual(self.p.match_reported_option('SetOutlet', 200.0, outlet_map), '200mL')
        self.assertEqual(self.p.match_reported_option('SetOutlet', 300, outlet_map), '300mL')

    def test_match_reported_option_priority_and_unmatched_guards(self):
        mapping = {'常温': 0, '25℃': 4, '45℃': 1}
        self.assertEqual(self.p.match_reported_option('SetTemp', 25, mapping, {'InputTemp': 25}), '25℃')
        temp_map = self.p.enum_mapping(CUBEUV_DEVICE, 'SetTemp')
        outlet_map = self.p.enum_mapping(CUBEUV_DEVICE, 'SetOutlet')
        for bad in (60, 45.5, -5, True, False, None):
            self.assertIsNone(self.p.match_reported_option('SetTemp', bad, temp_map, {'InputTemp': 20}))
        for bad in (250, 999, 200.5, -1, True, False, None):
            self.assertIsNone(self.p.match_reported_option('SetOutlet', bad, outlet_map))

    def test_accepted_confirm_values(self):
        self.assertEqual(
            self.p.accepted_confirm_values('SetTemp', 0, '常温', {'InputTemp': 22}),
            frozenset({'0', '20', '22', '25'}),
        )
        self.assertEqual(
            self.p.accepted_confirm_values('SetTemp', 1, '45℃', {'InputTemp': 20}),
            frozenset({'1', '45'}),
        )
        self.assertEqual(
            self.p.accepted_confirm_values('SetTemp', 3, '99℃', {'BoilingPoint': 96}),
            frozenset({'3', '99', '96'}),
        )
        self.assertEqual(
            self.p.accepted_confirm_values('SetOutlet', 1, '200mL', {}),
            frozenset({'1', '200'}),
        )


class FakeAPI:
    async def mqtt_config(self, identifier):
        return {'host': 'wss://example.invalid/mqtt', 'clientID': 'example'}


class WebSocket:
    def __init__(self):
        self.inbox = asyncio.Queue()
        self.sent = []
        self.closed = False

    async def send_bytes(self, data):
        self.sent.append(data)

    async def receive(self, timeout):
        return await asyncio.wait_for(self.inbox.get(), timeout)

    async def close(self):
        self.closed = True

    def push(self, data):
        self.inbox.put_nowait(types.SimpleNamespace(type=aiohttp.WSMsgType.BINARY, data=data))


class WSSession:
    def __init__(self, ws):
        self.ws = ws

    async def ws_connect(self, *args, **kwargs):
        return self.ws


async def until(predicate):
    async with asyncio.timeout(1):
        while not predicate():
            await asyncio.sleep(0.001)


class CubeUVTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        patcher, mods, _ = _load_pkg_modules()
        self.addCleanup(patcher.stop)
        self.p = mods['protocol']
        self.m = mods['mqtt_client']
        self.ws = WebSocket()
        self.states = []
        self.client = self.m.ShadowClient(
            WSSession(self.ws), FakeAPI(), 'example', self.states.append, lambda _: None, lambda: None
        )
        self.client.start()
        await until(lambda: bool(self.ws.sent))
        self.ws.push(self.p.packet(0x20, b'\x00\x00'))
        await until(lambda: len(self.ws.sent) >= 2)
        self.ws.push(self.p.packet(0x90, b'\x00\x01\x01\x01\x01\x01'))
        await until(lambda: self.client.connected)

    async def asyncTearDown(self):
        await self.client.stop()

    def report(self, state, version=1):
        body = (
            self.p.mqtt_string(self.client.prefix + 'update/accepted')
            + b'\x00\x01'
            + json.dumps({'version': version, 'state': {'reported': state}}).encode()
        )
        self.ws.push(self.p.packet(0x32, body))

    async def test_set_value_accepts_numeric_reported_echo(self):
        task = asyncio.create_task(self.client.set_value('SetTemp', 1, accepted=frozenset({'1', '45'})))
        await until(lambda: bool(self.client.pending))
        frames = self.p.extract_packets(bytearray(self.ws.sent[-1]))
        _, payload, _ = self.p.parse_publish(*frames[0])
        self.assertEqual(payload['state']['desired']['SetTemp'], 1)

        # desired-only or non-matching reported value must not confirm early.
        desired_body = self.p.mqtt_string(self.client.prefix + 'update/accepted') + json.dumps(
            {'version': 1, 'state': {'desired': {'SetTemp': 1}}}
        ).encode()
        self.ws.push(self.p.packet(0x30, desired_body))
        self.report({'SetTemp': 85}, version=2)
        await asyncio.sleep(0.01)
        self.assertFalse(task.done())

        # Numeric temperature reported back by CubeUV confirms the command.
        self.report({'SetTemp': 45}, version=3)
        await asyncio.wait_for(task, 1)
        self.assertFalse(self.client.pending)

    async def test_concurrent_and_disconnect_with_accepted_set(self):
        task = asyncio.create_task(self.client.set_value('SetOutlet', 1, accepted=frozenset({'1', '200'})))
        await until(lambda: bool(self.client.pending))
        with self.assertRaises(RuntimeError):
            await self.client.set_value('SetTemp', 1, accepted=frozenset({'1', '45'}))
        await self.client.stop()
        with self.assertRaises(ConnectionError):
            await task
        self.assertFalse(self.client.pending)

    async def test_legacy_set_value_without_accepted_unchanged(self):
        task = asyncio.create_task(self.client.set_value('SetTemp', 27))
        await until(lambda: bool(self.client.pending))
        self.report({'SetTemp': 27}, version=1)
        await asyncio.wait_for(task, 1)


class CubeUVEntityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patcher, mods, FakeEntityRegistry = _load_pkg_modules()
        self.addCleanup(patcher.stop)
        self.mods = mods
        self.FakeEntityRegistry = FakeEntityRegistry

    def _make_hass_and_entry(self, device, title='ADD6862', registry_items=None):
        hass = types.SimpleNamespace(
            data={},
            _er=self.FakeEntityRegistry(registry_items),
        )
        entry = types.SimpleNamespace(
            entry_id='entry_1',
            title=title,
            data={'device_id': device['device']['id'], 'device': device, 'access_token': 'tok'},
            _unsubs=[],
        )
        entry.async_on_unload = entry._unsubs.append
        entry.async_start_reauth = lambda _: None
        return hass, entry

    async def test_init_includes_binary_sensor_platform(self):
        self.assertIn('binary_sensor', self.mods['init'].PLATFORMS)

    async def test_device_info_and_select_and_coordinator(self):
        hass, entry = self._make_hass_and_entry(CUBEUV_DEVICE)
        coord = self.mods['coordinator'].DeermaCoordinator(hass, entry)
        coord.connected = True
        coord.last_seen = 1e12
        coord.on_state({'SetTemp': 20, 'SetOutlet': 200, 'InputTemp': 20, 'BoilingPoint': 99})
        hass.data['deerma_water'] = {entry.entry_id: coord}

        select_entities = []
        await self.mods['select'].async_setup_entry(hass, entry, select_entities.extend)
        self.assertEqual([e._attr_name for e in select_entities], ['水温设置', '出水量设置'])
        temp_sel, out_sel = select_entities
        self.assertEqual(temp_sel._attr_device_info['model'], 'ADD6862')
        self.assertEqual(temp_sel._attr_device_info['sw_version'], 'A1_0C-0.8.6')
        self.assertEqual(temp_sel.current_option, '常温')
        self.assertEqual(out_sel.current_option, '200mL')

        # Custom slider temperature should stay None rather than misreporting.
        coord.on_state({'SetTemp': 60})
        self.assertIsNone(temp_sel.current_option)

        # Fallback when metadata is absent
        hass_empty, entry_empty = self._make_hass_and_entry({'device': {'id': 'd0'}})
        coord_empty = self.mods['coordinator'].DeermaCoordinator(hass_empty, entry_empty)
        sel_empty = self.mods['select'].DeermaSelect(coord_empty, 'SetTemp', 'temperature', '水温设置')
        self.assertIsNone(sel_empty._attr_device_info['model'])
        self.assertIsNone(sel_empty._attr_device_info['sw_version'])

        # Coordinator set_option no-ops when numeric value already matches
        coord.on_state({'SetTemp': 20, 'InputTemp': 20})
        coord.shadow.set_value = AsyncMock()
        await coord.set_option('SetTemp', '常温')
        coord.shadow.set_value.assert_not_awaited()

        # Different target dispatches enum code with accepted numeric confirm set
        await coord.set_option('SetTemp', '45℃')
        coord.shadow.set_value.assert_awaited_once_with('SetTemp', 1, accepted=frozenset({'1', '45'}))

    async def test_sensor_registration_and_aqp_retirement(self):
        uid_base = CUBEUV_DEVICE['device']['id']
        reg_items = {
            'sensor.add6862_tap': types.SimpleNamespace(
                unique_id=f'{uid_base}_tap_water_tds', config_entry_id='entry_1', disabled_by=None
            ),
            'sensor.add6862_aqp': types.SimpleNamespace(
                unique_id=f'{uid_base}_aqp_filter_life', config_entry_id='entry_1', disabled_by=None
            ),
        }
        hass, entry = self._make_hass_and_entry(CUBEUV_DEVICE, registry_items=reg_items)
        coord = self.mods['coordinator'].DeermaCoordinator(hass, entry)
        hass.data['deerma_water'] = {entry.entry_id: coord}

        sensors = []
        await self.mods['sensor'].async_setup_entry(hass, entry, sensors.extend)
        # 4 base Reading + 1 Usage + 4 CubeUVNumericSensor + 1 CubeUVStatusSensor
        self.assertEqual(len(sensors), 10)
        by_key = {s._attr_unique_id.split('_', 1)[1]: s for s in sensors}

        # Partial state without filter/status must not prematurely retire AQP
        coord.on_state({'TDS': 22})
        self.assertIsNone(reg_items['sensor.add6862_aqp'].disabled_by)

        # Full CubeUV snapshot without AQP retires only AQP, keeping tap_water_tds active
        coord.on_state({
            'TDS': 22,
            'TapWaterTDS': 38,
            'PC5in1FilterLife': 71,
            'InputTemp': 20,
            'SetTemp': 20,
            'SetOutlet': 200,
            'OneTimeWater': 0,
            'Status': 1,
            'BoilingPoint': 99,
            'WinterMode': 0,
            'Flush': 0,
            'ErrorCode': '00',
        })
        self.assertIsNone(reg_items['sensor.add6862_tap'].disabled_by)
        self.assertEqual(reg_items['sensor.add6862_aqp'].disabled_by, 'integration')

        self.assertEqual(by_key['input_temp'].native_value, 20.0)
        self.assertEqual(by_key['set_temp_value'].native_value, 20.0)
        self.assertEqual(by_key['set_outlet_value'].native_value, 200.0)
        self.assertEqual(by_key['one_time_water'].native_value, 0.0)
        self.assertEqual(by_key['work_status'].native_value, '待机')
        self.assertEqual(by_key['work_status'].extra_state_attributes['boiling_point'], 99)

        coord.on_state({'InputTemp': True, 'Status': 4})
        self.assertIsNone(by_key['input_temp'].native_value)
        self.assertEqual(by_key['work_status'].native_value, '冲洗中')
        coord.on_state({'Status': 99})
        self.assertEqual(by_key['work_status'].native_value, '状态 99')

        # If a device variant actually reports AQPLife, AQP remains enabled
        aqp_items = {
            'sensor.var_aqp': types.SimpleNamespace(
                unique_id=f'{uid_base}_aqp_filter_life', config_entry_id='entry_1', disabled_by=None
            ),
        }
        hass_var, entry_var = self._make_hass_and_entry(CUBEUV_DEVICE, registry_items=aqp_items)
        coord_var = self.mods['coordinator'].DeermaCoordinator(hass_var, entry_var)
        hass_var.data['deerma_water'] = {entry_var.entry_id: coord_var}
        await self.mods['sensor'].async_setup_entry(hass_var, entry_var, lambda _: None)
        coord_var.on_state({'PC5in1FilterLife': 80, 'AQPLife': 90, 'Status': 1})
        self.assertIsNone(aqp_items['sensor.var_aqp'].disabled_by)

        # Non-CubeUV device only gets the 5 base sensors
        hass_i2, entry_i2 = self._make_hass_and_entry(I2PRO_DEVICE)
        coord_i2 = self.mods['coordinator'].DeermaCoordinator(hass_i2, entry_i2)
        hass_i2.data['deerma_water'] = {entry_i2.entry_id: coord_i2}
        i2_sensors = []
        await self.mods['sensor'].async_setup_entry(hass_i2, entry_i2, i2_sensors.extend)
        self.assertEqual(len(i2_sensors), 5)

    async def test_binary_sensors_cubeuv_and_non_cubeuv(self):
        hass, entry = self._make_hass_and_entry(CUBEUV_DEVICE)
        coord = self.mods['coordinator'].DeermaCoordinator(hass, entry)
        hass.data['deerma_water'] = {entry.entry_id: coord}
        bs_list = []
        await self.mods['binary_sensor'].async_setup_entry(hass, entry, bs_list.extend)
        self.assertEqual(len(bs_list), 6)
        by_key = {e._attr_unique_id.split('_', 1)[1]: e for e in bs_list}

        # Missing fields stay None
        for entity in bs_list:
            self.assertIsNone(entity.is_on)

        coord.on_state({'Warning': [2], 'SterilizerState': 0, 'ErrorCode': '00'})
        self.assertTrue(by_key['warning_change_water'].is_on)
        self.assertFalse(by_key['warning_water_lack'].is_on)
        self.assertFalse(by_key['warning_water_quality'].is_on)
        self.assertFalse(by_key['warning_pure_tank_removed'].is_on)
        self.assertFalse(by_key['uv_sterilizing'].is_on)
        self.assertFalse(by_key['device_error'].is_on)

        coord.on_state({'Warning': 'bad', 'SterilizerState': 1, 'ErrorCode': 'E00'})
        self.assertIsNone(by_key['warning_change_water'].is_on)
        self.assertTrue(by_key['uv_sterilizing'].is_on)
        self.assertFalse(by_key['device_error'].is_on)

        coord.on_state({'ErrorCode': 'E2'})
        self.assertTrue(by_key['device_error'].is_on)
        self.assertEqual(by_key['device_error'].extra_state_attributes, {'error_code': 'E2'})

        # Non-CubeUV adds zero binary sensors
        hass_i2, entry_i2 = self._make_hass_and_entry(I2PRO_DEVICE)
        coord_i2 = self.mods['coordinator'].DeermaCoordinator(hass_i2, entry_i2)
        hass_i2.data['deerma_water'] = {entry_i2.entry_id: coord_i2}
        i2_bs = []
        await self.mods['binary_sensor'].async_setup_entry(hass_i2, entry_i2, i2_bs.extend)
        self.assertEqual(i2_bs, [])


if __name__ == '__main__':
    unittest.main()
