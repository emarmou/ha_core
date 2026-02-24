"""Tests for the Solar Dispatcher surplus sensor entity."""

from __future__ import annotations

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant

from .conftest import GRID_ENTITY, setup_integration

from tests.common import MockConfigEntry


async def test_surplus_sensor_initial_value(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """The surplus sensor state must match the computed surplus after setup."""
    # Grid exporting 500 W (positive = exporting in this integration's convention).
    await setup_integration(hass, mock_config_entry, grid_state="500")

    state = hass.states.get("sensor.solar_dispatcher_available_surplus")
    assert state is not None
    assert float(state.state) == 500.0


async def test_surplus_sensor_updates_on_coordinator_refresh(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """The surplus sensor must update when the coordinator refreshes data."""
    await setup_integration(hass, mock_config_entry, grid_state="200")

    # Initial state: 200 W surplus.
    assert (
        float(hass.states.get("sensor.solar_dispatcher_available_surplus").state)
        == 200.0
    )

    # Change the grid reading: now 800 W export.
    hass.states.async_set(GRID_ENTITY, "800")

    coordinator = mock_config_entry.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert (
        float(hass.states.get("sensor.solar_dispatcher_available_surplus").state)
        == 800.0
    )


async def test_surplus_sensor_unavailable_when_grid_missing(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """The surplus sensor must be unavailable when the grid entity becomes unavailable."""
    await setup_integration(hass, mock_config_entry, grid_state="500")

    # Simulate the grid entity becoming unavailable.
    hass.states.async_set(GRID_ENTITY, STATE_UNAVAILABLE)

    coordinator = mock_config_entry.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get("sensor.solar_dispatcher_available_surplus")
    assert state is not None
    assert state.state == STATE_UNAVAILABLE


async def test_surplus_sensor_unit_and_device_class(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """The surplus sensor must report watts and use the power device class."""
    await setup_integration(hass, mock_config_entry, grid_state="100")

    state = hass.states.get("sensor.solar_dispatcher_available_surplus")
    assert state is not None
    assert state.attributes.get("unit_of_measurement") == "W"
    assert state.attributes.get("device_class") == "power"
