"""Common fixtures for the Solar Dispatcher tests."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.components.ha_solar_dispatcher.const import (
    CONF_DEVICE_ESTIMATED_POWER,
    CONF_DEVICE_ID,
    CONF_DEVICE_MIN_BATTERY_STATE,
    CONF_DEVICE_NAME,
    CONF_DEVICE_PRIORITY,
    CONF_DEVICE_SWITCH_ENTITY,
    CONF_DEVICES,
    CONF_GRID_ENTITY,
    CONF_GRID_INVERT,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)
from homeassistant.core import HomeAssistant

from tests.common import MockConfigEntry

# ── Shared test constants ─────────────────────────────────────────────────────────────

GRID_ENTITY = "sensor.grid_power"
BATTERY_CHARGE_ENTITY = "sensor.battery_charge"
BATTERY_STATE_ENTITY = "sensor.battery_soc"
ALLOWANCE_ENTITY = "input_number.dispatch_allowance"

DEVICE_ID = "aaaaaaaa-0000-0000-0000-000000000001"
DEVICE_SWITCH = "switch.ev_charger"

MOCK_DEVICE: dict[str, Any] = {
    CONF_DEVICE_ID: DEVICE_ID,
    CONF_DEVICE_NAME: "EV Charger",
    CONF_DEVICE_PRIORITY: 1,
    CONF_DEVICE_MIN_BATTERY_STATE: 0,
    CONF_DEVICE_ESTIMATED_POWER: 1500,
    CONF_DEVICE_SWITCH_ENTITY: DEVICE_SWITCH,
}

# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mocked config entry with no dispatch devices."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Solar Dispatcher",
        unique_id=GRID_ENTITY,
        data={
            CONF_GRID_ENTITY: GRID_ENTITY,
            CONF_GRID_INVERT: False,
            CONF_SCAN_INTERVAL: 30,
        },
        options={CONF_DEVICES: []},
    )


@pytest.fixture
def mock_config_entry_with_device() -> MockConfigEntry:
    """Return a mocked config entry pre-populated with one dispatch device."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Solar Dispatcher",
        unique_id=GRID_ENTITY,
        data={
            CONF_GRID_ENTITY: GRID_ENTITY,
            CONF_GRID_INVERT: False,
            CONF_SCAN_INTERVAL: 30,
        },
        options={CONF_DEVICES: [MOCK_DEVICE]},
    )


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Prevent the real async_setup_entry from running in config-flow tests."""
    with patch(
        "homeassistant.components.ha_solar_dispatcher.async_setup_entry",
        return_value=True,
    ) as mock:
        yield mock


async def setup_integration(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    *,
    grid_state: str = "-2000",
    switch_state: str = "off",
) -> MockConfigEntry:
    """Set up the Solar Dispatcher integration for testing.

    Injects the minimum HA entity states required so the coordinator's first
    refresh does not raise UpdateFailed, then loads the config entry.
    """
    hass.states.async_set(GRID_ENTITY, grid_state)
    for device in entry.options.get(CONF_DEVICES, []):
        hass.states.async_set(device[CONF_DEVICE_SWITCH_ENTITY], switch_state)

    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
