"""Read-only water data. Zero is a valid value; missing data stays unknown."""
import time
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from .const import DOMAIN
from .entity import DeermaEntity
from .protocol import first_present, i2pro_cooling_mode, has_i2pro_fields, is_cubeuv

SENSORS = [
    ('tap_water_tds', '自来水TDS', 'ppm', ('TapWaterTDS', 'TapWaterTds', 'tapWaterTds', 'inputTds'), 'mdi:water-opacity'),
    ('purified_tds', '饮用水TDS', 'ppm', ('TDS', 'Tds', 'tds', 'purifiedTds', 'outputTds'), 'mdi:water-check'),
    ('aqp_filter_life', 'AQP滤芯寿命', '%', ('AQPLife', 'AqpFilterLife', 'aqpFilterLife', 'filter1Life'), 'mdi:filter-outline'),
    ('pc5in1_filter_life', 'PC5IN1滤芯寿命', '%', ('PC5in1FilterLife', 'PC5IN1Life', 'PC5IN1FilterLife', 'pc5in1FilterLife', 'filter2Life'), 'mdi:filter-outline'),
]

CUBEUV_SENSORS = [
    ('input_temp', '进水温度', '°C', 'InputTemp', SensorDeviceClass.TEMPERATURE, 'mdi:thermometer-water'),
    ('set_temp_value', '当前设定水温', '°C', 'SetTemp', SensorDeviceClass.TEMPERATURE, 'mdi:thermometer-check'),
    ('set_outlet_value', '当前设定水量', 'mL', 'SetOutlet', None, 'mdi:cup-water'),
    ('one_time_water', '上次出水量', 'mL', 'OneTimeWater', None, 'mdi:water-outline'),
]

CUBEUV_STATUS_MAP = {0: '待机', 1: '待机', 2: '制水中', 3: '加热中', 4: '冲洗中'}


def _retire_missing_sensors(hass, entry, coordinator, target_keys):
    registry = er.async_get(hass)
    for key, _name, _unit, fields, _icon in SENSORS:
        if key not in target_keys:
            continue
        if any(field in coordinator.reported for field in fields):
            continue
        entity_id = registry.async_get_entity_id('sensor', DOMAIN, f'{coordinator.identifier}_{key}')
        if entity_id:
            item = registry.async_get(entity_id)
            if item and item.config_entry_id == entry.entry_id and item.disabled_by is None:
                registry.async_update_entity(entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [Reading(coordinator, *spec) for spec in SENSORS] + [Usage(coordinator)]
    if is_cubeuv(coordinator.device):
        entities.extend([CubeUVNumericSensor(coordinator, *spec) for spec in CUBEUV_SENSORS] + [CubeUVStatusSensor(coordinator)])
    async_add_entities(entities)
    added = False
    retired = False
    @callback
    def discover_cooling():
        nonlocal added, retired
        if not retired:
            target_keys = None
            if has_i2pro_fields(coordinator.reported):
                target_keys = ('tap_water_tds', 'aqp_filter_life')
            elif is_cubeuv(coordinator.device) and any(
                k in coordinator.reported for k in ('PC5in1FilterLife', 'PC5IN1Life', 'Status')
            ):
                target_keys = ('aqp_filter_life',)
            if target_keys:
                retired = True
                _retire_missing_sensors(hass, entry, coordinator, target_keys)

        # Wait for the first shadow report; do not add to older water-only devices.
        if not added and {"IceCubeMode", "IceWaterMode"} <= coordinator.reported.keys():
            added = True
            async_add_entities([CoolingMode(coordinator)])
    entry.async_on_unload(coordinator.async_add_listener(discover_cooling))
    discover_cooling()

class Reading(DeermaEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    def __init__(self, coordinator, key, name, unit, fields, icon=None):
        super().__init__(coordinator, key)
        self._attr_name, self._attr_native_unit_of_measurement, self.fields = name, unit, fields
        self._attr_icon = icon
    @property
    def native_value(self):
        value = first_present(self.coordinator.reported, *self.fields)
        try: return float(value) if value is not None else None
        except (ValueError, TypeError): return None

class Usage(DeermaEntity, SensorEntity):
    _attr_name = '总用水量'
    _attr_native_unit_of_measurement = 'L'
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_device_class = SensorDeviceClass.WATER
    _attr_icon = 'mdi:water-pump'
    def __init__(self, coordinator): super().__init__(coordinator, 'total_water')
    @property
    def available(self):
        # Legacy WaterPurifier endpoint is not validated for ice/water models.
        if 'IceCubeMode' in self.coordinator.reported:
            return False
        return self.coordinator.usage is not None and time.monotonic() - self.coordinator.usage_seen < 180
    @property
    def native_value(self):
        value = (self.coordinator.usage or {}).get('totalWater')
        try: return float(value) if value is not None else None
        except (ValueError, TypeError): return None


class CubeUVNumericSensor(DeermaEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    def __init__(self, coordinator, key, name, unit, field, device_class, icon):
        super().__init__(coordinator, key)
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self.field = field
        self._attr_device_class = device_class
        self._attr_icon = icon

    @property
    def native_value(self):
        value = self.coordinator.reported.get(self.field)
        if isinstance(value, bool):
            return None
        try:
            return float(value) if value is not None else None
        except (ValueError, TypeError):
            return None


class CubeUVStatusSensor(DeermaEntity, SensorEntity):
    _attr_name = '工作状态'
    _attr_icon = 'mdi:water-boiler'
    def __init__(self, coordinator):
        super().__init__(coordinator, 'work_status')

    @property
    def native_value(self):
        val = self.coordinator.reported.get('Status')
        if type(val) is not int:
            return None
        return CUBEUV_STATUS_MAP.get(val, f'状态 {val}')

    @property
    def extra_state_attributes(self):
        r = self.coordinator.reported
        return {
            'status_code': r.get('Status'),
            'boiling_point': r.get('BoilingPoint'),
            'winter_mode': r.get('WinterMode'),
            'flush': r.get('Flush'),
            'error_code': r.get('ErrorCode'),
        }


class CoolingMode(DeermaEntity, SensorEntity):
    """Observed mode only. No control service and no inferred working status."""
    _attr_name = "制冷模式（观测）"
    _attr_icon = "mdi:snowflake"
    def __init__(self, coordinator):
        super().__init__(coordinator, 'observed_cooling_mode')
    @property
    def native_value(self):
        return i2pro_cooling_mode(self.coordinator.reported)
    @property
    def extra_state_attributes(self):
        return {key: self.coordinator.reported.get(key) for key in
                ("IceCubeMode", "IceWaterMode", "IceCubeStatus", "IceWaterStatus")}
