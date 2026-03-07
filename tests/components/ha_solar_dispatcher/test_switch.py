"""Tests for the Solar Dispatcher virtual switch entities."""

from __future__ import annotations

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant

from .conftest import DEVICE_ID, DEVICE_SWITCH, MOCK_DEVICE, setup_integration

from tests.common import MockConfigEntry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_switch_ids(hass: HomeAssistant) -> tuple[str, str]:
    """Return (managed_switch_id, override_switch_id) from the entity registry."""
    all_ids = hass.states.async_entity_ids("switch")
    managed = next(
        eid for eid in all_ids if eid != DEVICE_SWITCH and "override" not in eid
    )
    override = next(
        eid for eid in all_ids if eid != DEVICE_SWITCH and "override" in eid
    )
    return managed, override


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

    managed_switch_id, _ = _find_switch_ids(hass)

    # Turn the virtual switch OFF.
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": managed_switch_id}, blocking=True
    )
    await hass.async_block_till_done()

    assert coordinator.device_enabled[DEVICE_ID] is False
    assert hass.states.get(managed_switch_id).state == STATE_OFF


async def test_turn_on_re_enables_algorithm(
    hass: HomeAssistant, mock_config_entry_with_device: MockConfigEntry
) -> None:
    """Turning on the virtual switch must re-enable algorithm control."""
    await setup_integration(hass, mock_config_entry_with_device)
    coordinator = mock_config_entry_with_device.runtime_data

    # Disable first via the coordinator dict directly.
    coordinator.device_enabled[DEVICE_ID] = False

    managed_switch_id, _ = _find_switch_ids(hass)

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": managed_switch_id}, blocking=True
    )
    await hass.async_block_till_done()

    assert coordinator.device_enabled[DEVICE_ID] is True
    assert hass.states.get(managed_switch_id).state == STATE_ON


async def test_virtual_switch_extra_attributes(
    hass: HomeAssistant, mock_config_entry_with_device: MockConfigEntry
) -> None:
    """The virtual switch must expose device config as state attributes."""
    await setup_integration(hass, mock_config_entry_with_device)

    managed_switch_id, _ = _find_switch_ids(hass)

    state = hass.states.get(managed_switch_id)
    assert state is not None
    attrs = state.attributes
    assert attrs["controlled_entity"] == DEVICE_SWITCH
    assert attrs["priority"] == MOCK_DEVICE["priority"]
    assert attrs["estimated_power_w"] == MOCK_DEVICE["estimated_power"]
    assert attrs["min_battery_state_pct"] == MOCK_DEVICE["min_battery_state"]


# ---------------------------------------------------------------------------
# Override switch tests
# ---------------------------------------------------------------------------


async def test_override_switch_off_by_default(
    hass: HomeAssistant, mock_config_entry_with_device: MockConfigEntry
) -> None:
    """The override switch must be OFF (inactive) after setup."""
    await setup_integration(hass, mock_config_entry_with_device)

    coordinator = mock_config_entry_with_device.runtime_data
    assert coordinator.device_override[DEVICE_ID] is False

    _, override_switch_id = _find_switch_ids(hass)
    assert hass.states.get(override_switch_id).state == STATE_OFF


async def test_override_switch_turn_on_sets_coordinator_flag(
    hass: HomeAssistant, mock_config_entry_with_device: MockConfigEntry
) -> None:
    """Turning on the override switch must set the coordinator's override flag."""
    await setup_integration(hass, mock_config_entry_with_device)

    _, override_switch_id = _find_switch_ids(hass)

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": override_switch_id}, blocking=True
    )
    await hass.async_block_till_done()

    coordinator = mock_config_entry_with_device.runtime_data
    assert coordinator.device_override[DEVICE_ID] is True
    assert hass.states.get(override_switch_id).state == STATE_ON


async def test_override_switch_turn_off_clears_coordinator_flag(
    hass: HomeAssistant, mock_config_entry_with_device: MockConfigEntry
) -> None:
    """Turning off the override switch must clear the coordinator's override flag."""
    await setup_integration(hass, mock_config_entry_with_device)
    coordinator = mock_config_entry_with_device.runtime_data
    coordinator.device_override[DEVICE_ID] = True

    _, override_switch_id = _find_switch_ids(hass)

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": override_switch_id}, blocking=True
    )
    await hass.async_block_till_done()

    assert coordinator.device_override[DEVICE_ID] is False
    assert hass.states.get(override_switch_id).state == STATE_OFF


async def test_override_auto_disables_on_external_real_switch_off(
    hass: HomeAssistant, mock_config_entry_with_device: MockConfigEntry
) -> None:
    """Override switch must auto-disable when an external component turns off the real switch.

    When something other than the Solar Dispatcher algorithm turns the real
    switch off while the override is active, the override should cancel itself
    so the coordinator will not immediately force the real switch back on.
    """
    await setup_integration(hass, mock_config_entry_with_device)
    coordinator = mock_config_entry_with_device.runtime_data

    # Simulate the real switch having been turned on (e.g., by a previous
    # coordinator cycle).  Setting state directly avoids triggering unregistered
    # service calls during the initial coordinator refresh.
    hass.states.async_set(DEVICE_SWITCH, STATE_ON)
    await hass.async_block_till_done()

    # Activate override directly.
    coordinator.device_override[DEVICE_ID] = True

    _, override_switch_id = _find_switch_ids(hass)
    assert coordinator.device_override[DEVICE_ID] is True

    # An external component transitions the real switch from ON → OFF.
    hass.states.async_set(DEVICE_SWITCH, STATE_OFF)
    await hass.async_block_till_done()

    # Override should have been cancelled automatically.
    assert coordinator.device_override[DEVICE_ID] is False
    assert hass.states.get(override_switch_id).state == STATE_OFF


async def test_override_stays_active_when_coordinator_turns_off_real_switch(
    hass: HomeAssistant, mock_config_entry_with_device: MockConfigEntry
) -> None:
    """Override must not be cancelled when the coordinator itself turns off the real switch.

    The override is designed to counteract the coordinator's off decisions,
    so a coordinator-initiated OFF event must not cancel an active override.
    """
    await setup_integration(hass, mock_config_entry_with_device)
    coordinator = mock_config_entry_with_device.runtime_data

    # Simulate the real switch being on.
    hass.states.async_set(DEVICE_SWITCH, STATE_ON)
    await hass.async_block_till_done()

    _, override_switch_id = _find_switch_ids(hass)

    # Turn on the override switch via the service so both the coordinator dict
    # and the entity state are updated properly.
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": override_switch_id}, blocking=True
    )
    await hass.async_block_till_done()

    assert coordinator.device_override[DEVICE_ID] is True
    assert hass.states.get(override_switch_id).state == STATE_ON

    # Simulate the coordinator flagging that it is about to turn off the real
    # switch (as _turn_off() does before calling the service).
    coordinator.turning_off_by_coordinator.add(DEVICE_SWITCH)

    # The state change that would follow the coordinator's service call.
    hass.states.async_set(DEVICE_SWITCH, STATE_OFF)
    await hass.async_block_till_done()

    # Override must still be active; the coordinator caused the OFF event.
    assert coordinator.device_override[DEVICE_ID] is True
    assert hass.states.get(override_switch_id).state == STATE_ON
    # The marker in turning_off_by_coordinator must have been consumed.
    assert DEVICE_SWITCH not in coordinator.turning_off_by_coordinator


async def test_override_ignores_non_on_to_off_transitions(
    hass: HomeAssistant, mock_config_entry_with_device: MockConfigEntry
) -> None:
    """Override must not be cancelled when the real switch appears as OFF from a non-ON state.

    For example, when HA starts up and the switch is unavailable then becomes
    off, the override should not be incorrectly cancelled.
    """
    # Real switch starts as unavailable so the coordinator skips it.
    await setup_integration(
        hass, mock_config_entry_with_device, switch_state="unavailable"
    )
    coordinator = mock_config_entry_with_device.runtime_data
    coordinator.device_override[DEVICE_ID] = True

    # Real switch goes from unavailable → off (not an ON → OFF transition).
    hass.states.async_set(DEVICE_SWITCH, STATE_OFF)
    await hass.async_block_till_done()

    # Override must remain active because the transition was not ON → OFF.
    assert coordinator.device_override[DEVICE_ID] is True
