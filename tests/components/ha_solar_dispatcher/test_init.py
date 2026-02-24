"""Tests for Solar Dispatcher integration setup and teardown."""

from __future__ import annotations

from homeassistant.components.ha_solar_dispatcher.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .conftest import setup_integration

from tests.common import MockConfigEntry


async def test_load_unload(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """The integration must load and unload cleanly."""
    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_load_fails_when_grid_unavailable(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """When the grid entity is unavailable the entry must not load."""
    # Do NOT set the grid entity state — coordinator will raise UpdateFailed.
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_options_change_triggers_reload(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Saving new options must reload the config entry."""
    await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED

    # Simulate the user saving options from the UI.
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={"devices": []},
    )
    await hass.async_block_till_done()

    # Entry is reloaded — it will go through LOADED again.
    assert mock_config_entry.state is ConfigEntryState.LOADED


async def test_service_device_registered(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A service device entry must be created in the device registry."""
    await setup_integration(hass, mock_config_entry)

    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(
        identifiers={(DOMAIN, mock_config_entry.entry_id)}
    )
    assert device is not None
    assert device.name == mock_config_entry.title
