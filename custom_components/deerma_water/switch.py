"""Observed i2 Pro buzzer control. No lock/dispense/reset controls."""
from homeassistant.core import callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.components.switch import SwitchEntity
from .const import DOMAIN
from .entity import DeermaEntity
from .protocol import has_i2pro_fields

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    added = False
    @callback
    def discover_controls():
        nonlocal added
        if not added and has_i2pro_fields(coordinator.reported):
            added = True
            async_add_entities([BuzzerSwitch(coordinator)])
    entry.async_on_unload(coordinator.async_add_listener(discover_controls))
    discover_controls()

class BuzzerSwitch(DeermaEntity, SwitchEntity):
    _attr_name = '蜂鸣声'
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = 'mdi:volume-high'
    def __init__(self, coordinator):
        super().__init__(coordinator, 'buzzer_control')
    @property
    def is_on(self):
        value = self.coordinator.reported.get('TouchBuzzerSet')
        return bool(value) if type(value) is int and value in (0,1) else None
    async def async_turn_on(self, **kwargs):
        await self.coordinator.set_i2pro_values({'TouchBuzzerSet':1})
    async def async_turn_off(self, **kwargs):
        await self.coordinator.set_i2pro_values({'TouchBuzzerSet':0})
