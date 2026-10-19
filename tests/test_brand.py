"""The integration ships its own brand images, served by Home Assistant."""

from __future__ import annotations

from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.racktivity_dcmu.const import DOMAIN

BRAND = Path(__file__).parent.parent / "custom_components" / DOMAIN / "brand"


@pytest.mark.parametrize("image", ["icon.png", "icon@2x.png", "dark_icon.png", "dark_icon@2x.png"])
async def test_brand_images_served(hass: HomeAssistant, hass_client, image: str) -> None:
    """HA serves each image from brand/ for this custom integration."""
    assert await async_setup_component(hass, "brands", {})
    client = await hass_client()
    resp = await client.get(f"/api/brands/integration/{DOMAIN}/{image}")
    assert resp.status == 200
    assert await resp.read() == (BRAND / image).read_bytes()
