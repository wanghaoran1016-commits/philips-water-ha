"""Read-only CubeUV warning, sterilizer, and error binary sensors."""
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from .const import DOMAIN
from .entity import DeermaEntity
from .protocol import is_cubeuv

CUBEUV_WARNINGS = [
    ('warning_change_water', '原水箱需换水', 2, 'mdi:water-sync'),
    ('warning_water_lack', '原水箱缺水', 0, 'mdi:water-alert'),
    ('warning_water_quality', '水质异常', 1, 'mdi:water-remove'),
    ('warning_pure_tank_removed', '纯水箱未放好', 3, 'mdi:cup-off-outline'),
]


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    if not is_cubeuv(coordinator.device):
        return
    entities = [CubeUVWarningBinarySensor(coordinator, *spec) for spec in CUBEUV_WARNINGS]
    entities.extend([CubeUVSterilizerBinarySensor(coordinator), CubeUVErrorBinarySensor(coordinator)])
    async_add_entities(entities)


class CubeUVWarningBinarySensor(DeermaEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    def __init__(self, coordinator, key, name, bit, icon):
        super().__init__(coordinator, key)
        self._attr_name = name
        self.bit = bit
        self._attr_icon = icon

    @property
    def is_on(self):
        warnings = self.coordinator.reported.get('Warning')
        if not isinstance(warnings, list):
            return None
        return self.bit in warnings


class CubeUVSterilizerBinarySensor(DeermaEntity, BinarySensorEntity):
    _attr_name = 'UV杀菌中'
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = 'mdi:shimmer'
    def __init__(self, coordinator):
        super().__init__(coordinator, 'uv_sterilizing')

    @property
    def is_on(self):
        if 'SterilizerState' not in self.coordinator.reported:
            return None
        return self.coordinator.reported.get('SterilizerState') == 1


class CubeUVErrorBinarySensor(DeermaEntity, BinarySensorEntity):
    _attr_name = '设备故障'
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = 'mdi:alert-circle-outline'
    def __init__(self, coordinator):
        super().__init__(coordinator, 'device_error')

    @property
    def is_on(self):
        code = self.coordinator.reported.get('ErrorCode')
        if code is None:
            return None
        return str(code) not in ('00', 'E00', '0', '')

    @property
    def extra_state_attributes(self):
        return {'error_code': self.coordinator.reported.get('ErrorCode')}
