"""Constants for the Racktivity DCMU integration."""

from typing import Final

DOMAIN: Final = "racktivity_dcmu"
MANUFACTURER: Final = "Racktivity"

CONF_COMMUNITY: Final = "community"
CONF_WRITE_COMMUNITY: Final = "write_community"
CONF_ENABLE_CONTROL: Final = "enable_control"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_CONFIG_INTERVAL: Final = "config_interval"
CONF_WEB_USERNAME: Final = "web_username"
CONF_WEB_PASSWORD: Final = "web_password"
CONF_HTTP_INTERVAL: Final = "http_interval"

DEFAULT_PORT: Final = 161
DEFAULT_COMMUNITY: Final = "public"
DEFAULT_SCAN_INTERVAL: Final = 5  # seconds, live values + relay state
DEFAULT_CONFIG_INTERVAL: Final = 300  # seconds, names/thresholds/peaks
DEFAULT_HTTP_INTERVAL: Final = 60  # seconds, web API extras + event log

MIN_SCAN_INTERVAL: Final = 2
MAX_SCAN_INTERVAL: Final = 300
MIN_CONFIG_INTERVAL: Final = 60
MAX_CONFIG_INTERVAL: Final = 86400
MIN_HTTP_INTERVAL: Final = 10
MAX_HTTP_INTERVAL: Final = 3600

EVENT_RELAY_CHANGED: Final = f"{DOMAIN}_relay_changed"
EVENT_DEVICE_EVENT: Final = f"{DOMAIN}_device_event"
