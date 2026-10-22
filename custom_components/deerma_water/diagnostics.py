"""Allowlisted export: no config-entry data, account or cloud response dump."""
from .const import DOMAIN, VERSION
from .protocol import diagnostics_snapshot

async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    return {'integration_version': VERSION, 'connection_live': coordinator.live,
            'control_trace': coordinator.control_trace.snapshot(),
            **diagnostics_snapshot(coordinator.device, coordinator.reported)}
