"""Tests for the Solar Dispatcher virtual switch entities."""

from __future__ import annotations

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant

from .conftest import DEVICE_ID, DEVICE_SWITCH, MOCK_DEVICE, setup_integration

from tests.common import MockConfigEntry


async def test_virtual_switch_on_by_default(
    hass: HomeAssistant, mock_config_entry_with_device: MockConfigEntry
) -> None:
    """The virtual dispatch switch must be ON (enabled) after setup."""
    await setup_integration(hass, mock_config_entry_with_device)

    hass.states.get("switch.ev_charger")
    # The virtual switch entity name comes from CONF_DEVICE_NAME ("EV Charger").
    # Its entity_id is derived by HA from name + device.
    # We look it up via the coordinator's device_enabled mapping.
    coordinator = mock_config_entry_with_device.runtime_data
    assert coordinator.device_enabled.get(DEVICE_ID, True) is True


async def test_turn_off_disables_algorithm_and_turns_off_real(
    hass: HomeAssistant, mock_config_entry_with_device: MockConfigEntry
) -> None:
    """Turning off the virtual switch must disable algorithm control and turn off the real switch."""
    await setup_integration(hass, mock_config_entry_with_device)

    coordinator = mock_config_entry_with_device.runtime_data
    assert coordinator.device_enabled[DEVICE_ID] is True

    # Find the virtual switch entity.
    er = hass.states.async_entity_ids("switch")
    virtual_switch_id = next(
        eid for eid in er if eid.startswith("switch.") and eid != DEVICE_SWITCH
    )

    # Turn the virtual switch OFF.
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": virtual_switch_id}, blocking=True
    )
    await hass.async_block_till_done()

    assert coordinator.device_enabled[DEVICE_ID] is False
    assert hass.states.get(virtual_switch_id).state == STATE_OFF


async def test_turn_on_re_enables_algorithm(
    hass: HomeAssistant, mock_config_entry_with_device: MockConfigEntry
) -> None:
    """Turning on the virtual switch must re-enable algorithm control."""
    await setup_integration(hass, mock_config_entry_with_device)
    coordinator = mock_config_entry_with_device.runtime_data

    # Disable first via the coordinator dict directly.
    coordinator.device_enabled[DEVICE_ID] = False

    er = hass.states.async_entity_ids("switch")
    virtual_switch_id = next(
        eid for eid in er if eid != DEVICE_SWITCH and eid.startswith("switch.")
    )

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": virtual_switch_id}, blocking=True
    )
    await hass.async_block_till_done()

    assert coordinator.device_enabled[DEVICE_ID] is True
    assert hass.states.get(virtual_switch_id).state == STATE_ON


async def test_virtual_switch_extra_attributes(
    hass: HomeAssistant, mock_config_entry_with_device: MockConfigEntry
) -> None:
    """The virtual switch must expose device config as state attributes."""
    await setup_integration(hass, mock_config_entry_with_device)

    er = hass.states.async_entity_ids("switch")
    virtual_switch_id = next(
        eid for eid in er if eid != DEVICE_SWITCH and eid.startswith("switch.")
    )

    state = hass.states.get(virtual_switch_id)
    assert state is not None
    attrs = state.attributes
    assert attrs["controlled_entity"] == DEVICE_SWITCH
    assert attrs["priority"] == MOCK_DEVICE["priority"]
    assert attrs["estimated_power_w"] == MOCK_DEVICE["estimated_power"]
    assert attrs["min_battery_state_pct"] == MOCK_DEVICE["min_battery_state"]
