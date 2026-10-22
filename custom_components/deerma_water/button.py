"""55°C preset resolves its code from device metadata, never hardcoded."""
from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import EntityCategory
from .const import DOMAIN
from .entity import DeermaEntity
from .protocol import enum_mapping

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([StartTrace(coordinator)])
    label = next((label for label in enum_mapping(coordinator.device, 'SetTemp') if label.replace('°C', '℃').replace(' ', '') == '55℃'), None)
    if label: async_add_entities([Quick55(coordinator, label)])

class Quick55(DeermaEntity, ButtonEntity):
    _attr_name = '设置55度（不出水）'
    _attr_icon = 'mdi:thermometer-water'
    def __init__(self, coordinator, label):
        super().__init__(coordinator, 'quick_55')
        self.label = label
    async def async_press(self):
        await self.coordinator.set_option('SetTemp', self.label)


class StartTrace(DeermaEntity, ButtonEntity):
    _attr_name = '采集控制变化（5分钟）'
    _attr_icon = 'mdi:record-rec'
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    def __init__(self, coordinator):
        super().__init__(coordinator, 'start_control_trace')
    async def async_press(self):
        self.coordinator.control_trace.start(self.coordinator.reported)
