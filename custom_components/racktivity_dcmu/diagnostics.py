"""Diagnostics for the Racktivity DCMU integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_COMMUNITY, CONF_WEB_PASSWORD, CONF_WEB_USERNAME, CONF_WRITE_COMMUNITY
from .coordinator import DcmuConfigEntry

TO_REDACT = {CONF_COMMUNITY, CONF_WRITE_COMMUNITY, CONF_WEB_USERNAME, CONF_WEB_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DcmuConfigEntry
) -> dict[str, Any]:
    """Return diagnostics, including the OIDs whose meaning is still unknown."""
    coordinator = entry.runtime_data
    state = asdict(coordinator.data)
    unknown = state.pop("unknown")
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "state": state,
        "unidentified_oids": {k: repr(v) for k, v in unknown.items()},
        "web_api": (
            {
                "last_update_success": coordinator.http.last_update_success,
                "data": asdict(coordinator.http.data) if coordinator.http.data else None,
            }
            if coordinator.http is not None
            else None
        ),
    }
