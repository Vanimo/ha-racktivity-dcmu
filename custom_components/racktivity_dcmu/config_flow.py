"""Config flow for the Racktivity DCMU integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

try:  # HA >= 2026.x validates with probatio (voluptuous-compatible)
    import probatio as vol
except ImportError:  # pragma: no cover
    import voluptuous as vol  # type: ignore[no-redef]
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_COMMUNITY,
    CONF_CONFIG_INTERVAL,
    CONF_CYCLE_DELAY,
    CONF_ENABLE_CONTROL,
    CONF_HTTP_INTERVAL,
    CONF_SCAN_INTERVAL,
    CONF_WEB_PASSWORD,
    CONF_WEB_USERNAME,
    CONF_WRITE_COMMUNITY,
    DEFAULT_COMMUNITY,
    DEFAULT_CONFIG_INTERVAL,
    DEFAULT_CYCLE_DELAY,
    DEFAULT_HTTP_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_CONFIG_INTERVAL,
    MAX_CYCLE_DELAY,
    MAX_HTTP_INTERVAL,
    MAX_SCAN_INTERVAL,
    MIN_CONFIG_INTERVAL,
    MIN_CYCLE_DELAY,
    MIN_HTTP_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .coordinator import DcmuConfigEntry
from .http_api import DcmuHttp, DcmuHttpAuthError, DcmuHttpError
from .pdu import DcmuSnmp, NotADcmu
from .snmp import SnmpClient, SnmpError

_LOGGER = logging.getLogger(__name__)

_PASSWORD = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)


def _connection_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, vol.UNDEFINED)): str,
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
            vol.Required(
                CONF_COMMUNITY, default=defaults.get(CONF_COMMUNITY, DEFAULT_COMMUNITY)
            ): _PASSWORD,
        }
    )


async def _probe(data: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return (pdu name, error key)."""
    pdu = DcmuSnmp(SnmpClient(data[CONF_HOST], data[CONF_PORT], data[CONF_COMMUNITY]))
    try:
        await pdu.identify()
        await pdu.read_config()
    except NotADcmu:
        return None, "not_dcmu"
    except SnmpError:
        return None, "cannot_connect"
    except OSError:
        return None, "cannot_connect"
    except Exception:
        _LOGGER.exception("Unexpected error probing %s", data[CONF_HOST])
        return None, "unknown"
    finally:
        pdu.close()
    return pdu.state.name, None


def _extras_fields(opts: dict[str, Any]) -> dict[Any, Any]:
    """Optional fields shared by setup and options: relay control and web login."""
    return {
        vol.Optional(CONF_ENABLE_CONTROL, default=opts.get(CONF_ENABLE_CONTROL, False)): bool,
        vol.Optional(
            CONF_WRITE_COMMUNITY,
            description={"suggested_value": opts.get(CONF_WRITE_COMMUNITY)},
        ): _PASSWORD,
        vol.Optional(
            CONF_WEB_USERNAME,
            description={"suggested_value": opts.get(CONF_WEB_USERNAME)},
        ): str,
        vol.Optional(
            CONF_WEB_PASSWORD,
            description={"suggested_value": opts.get(CONF_WEB_PASSWORD)},
        ): _PASSWORD,
    }


async def _apply_extras(hass: HomeAssistant, host: str, user_input: dict[str, Any]) -> str | None:
    """Normalise the optional fields in place; return an error key or None.

    Control without a write community is turned off, a half-filled web
    login is dropped, and a complete one is checked with one read.
    """
    if not user_input.get(CONF_WRITE_COMMUNITY):
        user_input.pop(CONF_WRITE_COMMUNITY, None)
        user_input[CONF_ENABLE_CONTROL] = False
    if not (user_input.get(CONF_WEB_USERNAME) and user_input.get(CONF_WEB_PASSWORD)):
        user_input.pop(CONF_WEB_USERNAME, None)
        user_input.pop(CONF_WEB_PASSWORD, None)
        return None
    api = DcmuHttp(
        async_get_clientsession(hass),
        host,
        user_input[CONF_WEB_USERNAME],
        user_input[CONF_WEB_PASSWORD],
    )
    try:
        await api.read_versions()
    except DcmuHttpAuthError:
        return "invalid_auth"
    except DcmuHttpError:
        return "cannot_connect_http"
    return None


class DcmuConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for a Racktivity DCMU."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._title = ""

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: DcmuConfigEntry) -> DcmuOptionsFlow:
        """Options flow."""
        return DcmuOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the agent address and read community."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}")
            self._abort_if_unique_id_configured()
            name, error = await _probe(user_input)
            if error:
                errors["base"] = error
            else:
                self._data = user_input
                self._title = name or user_input[CONF_HOST]
                return await self.async_step_extras()
        return self.async_show_form(
            step_id="user", data_schema=_connection_schema(user_input or {}), errors=errors
        )

    async def async_step_extras(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Optional: relay control and web login. Stored as options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await _apply_extras(self.hass, self._data[CONF_HOST], user_input)
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=self._title, data=self._data, options=user_input
                )
        return self.async_show_form(
            step_id="extras",
            data_schema=vol.Schema(_extras_fields(user_input or {})),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The PDU rejected the web login; ask for a new one."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate the new web login and store it in the options."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await _apply_extras(self.hass, entry.data[CONF_HOST], user_input)
            if error:
                errors["base"] = error
            elif CONF_WEB_USERNAME not in user_input:
                errors["base"] = "invalid_auth"
            else:
                return self.async_update_reload_and_abort(
                    entry, options={**entry.options, **user_input}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_WEB_USERNAME, default=entry.options.get(CONF_WEB_USERNAME, "")
                    ): str,
                    vol.Required(CONF_WEB_PASSWORD): _PASSWORD,
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change host, port or read community."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            unique_id = f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}"
            for other in self._async_current_entries(include_ignore=False):
                if other.entry_id != entry.entry_id and other.unique_id == unique_id:
                    raise AbortFlow("already_configured")
            _, error = await _probe(user_input)
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry, unique_id=unique_id, data=user_input
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(user_input or dict(entry.data)),
            errors=errors,
        )


def _seconds(minimum: int, maximum: int) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum, max=maximum, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX
        )
    )


class DcmuOptionsFlow(OptionsFlowWithReload):
    """Polling intervals, (opt-in) relay control and the optional web login."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            for key in (
                CONF_SCAN_INTERVAL,
                CONF_CONFIG_INTERVAL,
                CONF_HTTP_INTERVAL,
                CONF_CYCLE_DELAY,
            ):
                if key in user_input:
                    user_input[key] = int(user_input[key])
            error = await _apply_extras(self.hass, self.config_entry.data[CONF_HOST], user_input)
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(data=user_input)

        opts = {**self.config_entry.options, **(user_input or {})}
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL, default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): _seconds(MIN_SCAN_INTERVAL, MAX_SCAN_INTERVAL),
                vol.Required(
                    CONF_CONFIG_INTERVAL,
                    default=opts.get(CONF_CONFIG_INTERVAL, DEFAULT_CONFIG_INTERVAL),
                ): _seconds(MIN_CONFIG_INTERVAL, MAX_CONFIG_INTERVAL),
                **_extras_fields(opts),
                vol.Required(
                    CONF_CYCLE_DELAY, default=opts.get(CONF_CYCLE_DELAY, DEFAULT_CYCLE_DELAY)
                ): _seconds(MIN_CYCLE_DELAY, MAX_CYCLE_DELAY),
                vol.Required(
                    CONF_HTTP_INTERVAL, default=opts.get(CONF_HTTP_INTERVAL, DEFAULT_HTTP_INTERVAL)
                ): _seconds(MIN_HTTP_INTERVAL, MAX_HTTP_INTERVAL),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
