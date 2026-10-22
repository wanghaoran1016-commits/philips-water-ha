"""Only expose enums actually advertised by the selected device."""
from homeassistant.core import callback
from homeassistant.components.select import SelectEntity
from .const import DOMAIN
from .entity import DeermaEntity
from .protocol import enum_mapping, has_i2pro_fields, I2PRO_COOLING_MODES, i2pro_cooling_mode, I2PRO_PRESETS, i2pro_preset_value

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DeermaSelect(coordinator, field, key, name)
        for field, key, name in [('SetTemp', 'temperature', '水温设置'), ('SetOutlet', 'water_volume', '出水量设置')]
        if enum_mapping(coordinator.device, field)])
    added = False
    @callback
    def discover_controls():
        nonlocal added
        if not added and has_i2pro_fields(coordinator.reported):
            added = True
            entities = [CoolingSelect(coordinator)]
            for field, key, name in [('SetTemp','temperature','水温档位'),
                                     ('SetOutlet','water_volume','水量档位')]:
                if not enum_mapping(coordinator.device, field):
                    entities.append(I2ProPreset(coordinator, field, key, name))
            async_add_entities(entities)
    entry.async_on_unload(coordinator.async_add_listener(discover_controls))
    discover_controls()


class DeermaSelect(DeermaEntity, SelectEntity):
    def __init__(self, coordinator, field, key, name):
        super().__init__(coordinator, key)
        self.field = field
        self.mapping = enum_mapping(coordinator.device, field)
        self._attr_options = list(self.mapping)
        self._attr_name = name

    @property
    def current_option(self):
        value = self.coordinator.reported.get(self.field)
        if value is None: return None
        return next((label for label, code in self.mapping.items() if str(code) == str(value)), None)

    async def async_select_option(self, option):
        await self.coordinator.set_option(self.field, option)


class CoolingSelect(DeermaEntity, SelectEntity):
    _attr_name = '制冷模式'
    _attr_icon = 'mdi:snowflake'
    _attr_options = list(I2PRO_COOLING_MODES.values())
    def __init__(self, coordinator):
        super().__init__(coordinator, 'cooling_mode_control')
    @property
    def current_option(self):
        return i2pro_cooling_mode(self.coordinator.reported)
    async def async_select_option(self, option):
        pair = next((pair for pair,label in I2PRO_COOLING_MODES.items() if label == option), None)
        if pair is None: raise ValueError('Unknown mode')
        await self.coordinator.set_i2pro_values(dict(zip(('IceCubeMode','IceWaterMode'),pair)))


class I2ProPreset(DeermaEntity, SelectEntity):
    """Confirmed App preset codes; no dispensing command is sent."""
    def __init__(self, coordinator, field, key, name):
        super().__init__(coordinator, key)
        self.field = field
        self._attr_name = name
        self._attr_options = list(I2PRO_PRESETS[field])
    @property
    def current_option(self):
        value = self.coordinator.reported.get(self.field)
        if type(value) is not int: return None
        return next((label for label,code in I2PRO_PRESETS[self.field].items() if code == value), None)
    async def async_select_option(self, option):
        value = i2pro_preset_value(self.field, option)
        await self.coordinator.set_i2pro_values({self.field:value})
