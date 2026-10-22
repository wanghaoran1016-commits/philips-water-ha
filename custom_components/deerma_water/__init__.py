"""Philips Water Health community integration, derived from hlhk2017."""
from homeassistant.const import Platform
from .const import DOMAIN
from .coordinator import DeermaCoordinator
from .protocol import device_id

PLATFORMS = [Platform.SELECT, Platform.SENSOR, Platform.BUTTON, Platform.SWITCH]

async def async_setup_entry(hass, entry):
    coordinator = DeermaCoordinator(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    coordinator.async_set_updated_data({})
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        coordinator.shadow.start()
    except Exception:
        await coordinator.shadow.stop()
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise
    return True

async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.shadow.stop()
        return True
    return False

async def async_migrate_entry(hass, entry):
    if entry.version > 2: return False
    if entry.version == 1:
        devices = entry.data.get('devices', [])
        identifier = entry.data.get('device_id')
        selected = next((d for d in devices if device_id(d) == identifier), None)
        if not selected or not entry.data.get('access_token'): return False
        # Drop stored password, phone, refresh token and unrelated devices.
        hass.config_entries.async_update_entry(entry, version=2, unique_id=identifier,
            data={'device_id': identifier, 'device': selected, 'access_token': entry.data['access_token']})
    return True
