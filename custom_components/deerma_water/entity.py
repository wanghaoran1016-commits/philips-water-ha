"""Shared per-device entity metadata."""
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN

class DeermaEntity(CoordinatorEntity):
    _attr_has_entity_name = True
    def __init__(self, coordinator, key):
        super().__init__(coordinator)
        self._attr_unique_id = f'{coordinator.identifier}_{key}'
        device_data = coordinator.device if isinstance(coordinator.device, dict) else {}
        product = device_data.get('product') if isinstance(device_data.get('product'), dict) else {}
        dev = device_data.get('device') if isinstance(device_data.get('device'), dict) else {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.identifier)},
            name=coordinator.entry.title,
            manufacturer='Philips / Deerma',
            model=product.get('modelName') or product.get('name'),
            sw_version=dev.get('wifiVersion'),
        )

    @property
    def available(self):
        return self.coordinator.live
