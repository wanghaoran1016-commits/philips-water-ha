"""Shared per-device entity metadata."""
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN

class DeermaEntity(CoordinatorEntity):
    _attr_has_entity_name = True
    def __init__(self, coordinator, key):
        super().__init__(coordinator)
        self._attr_unique_id = f'{coordinator.identifier}_{key}'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, coordinator.identifier)},
            name=coordinator.entry.title, manufacturer='Philips / Deerma')

    @property
    def available(self):
        return self.coordinator.live
