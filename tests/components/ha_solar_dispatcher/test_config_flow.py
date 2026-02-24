"""Tests for the Solar Dispatcher config flow and options flow."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

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
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import (
    ALLOWANCE_ENTITY,
    BATTERY_CHARGE_ENTITY,
    BATTERY_STATE_ENTITY,
    DEVICE_ID,
    DEVICE_SWITCH,
    GRID_ENTITY,
)

from tests.common import MockConfigEntry

# ── Helpers ───────────────────────────────────────────────────────────────────

_VALID_USER_INPUT: dict[str, Any] = {
    CONF_GRID_ENTITY: GRID_ENTITY,
    CONF_GRID_INVERT: False,
    CONF_SCAN_INTERVAL: 30,
}


def _set_entity_states(hass: HomeAssistant, *entity_ids: str) -> None:
    """Register entity states so _entity_exists() resolves them."""
    for entity_id in entity_ids:
        hass.states.async_set(entity_id, "0")


# ── Config flow — user step ───────────────────────────────────────────────────


async def test_user_step_shows_form(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """The initial step must present a FORM result."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert not result["errors"]


async def test_user_step_creates_entry(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """A valid submission must create an entry with the expected data."""
    _set_entity_states(hass, GRID_ENTITY)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _VALID_USER_INPUT
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Solar Dispatcher"
    assert result["data"][CONF_GRID_ENTITY] == GRID_ENTITY
    assert result["data"][CONF_GRID_INVERT] is False
    assert result["data"][CONF_SCAN_INTERVAL] == 30
    assert mock_setup_entry.call_count == 1


async def test_user_step_all_optional_fields(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """All optional entities should be stored when provided."""
    _set_entity_states(
        hass,
        GRID_ENTITY,
        BATTERY_CHARGE_ENTITY,
        BATTERY_STATE_ENTITY,
        ALLOWANCE_ENTITY,
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            **_VALID_USER_INPUT,
            "battery_charge_entity": BATTERY_CHARGE_ENTITY,
            "battery_charge_invert": True,
            "battery_state_entity": BATTERY_STATE_ENTITY,
            "allowance_entity": ALLOWANCE_ENTITY,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    data = result["data"]
    assert data["battery_charge_entity"] == BATTERY_CHARGE_ENTITY
    assert data["battery_charge_invert"] is True
    assert data["battery_state_entity"] == BATTERY_STATE_ENTITY
    assert data["allowance_entity"] == ALLOWANCE_ENTITY


async def test_user_step_entity_not_found_then_recover(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """An unknown entity ID must show entity_not_found and allow recovery."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    # Submit with a non-existent entity.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**_VALID_USER_INPUT, CONF_GRID_ENTITY: "sensor.does_not_exist"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "entity_not_found"}

    # Fix the entity and resubmit — must succeed.
    _set_entity_states(hass, GRID_ENTITY)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _VALID_USER_INPUT
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_step_already_configured(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A second entry using the same grid entity must be aborted."""
    mock_config_entry.add_to_hass(hass)
    _set_entity_states(hass, GRID_ENTITY)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


# ── Config flow — reconfigure step ───────────────────────────────────────────


async def test_reconfigure_updates_entry(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Reconfigure must update the config entry data and reload."""
    mock_config_entry.add_to_hass(hass)
    _set_entity_states(hass, GRID_ENTITY)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    new_input = {**_VALID_USER_INPUT, CONF_SCAN_INTERVAL: 60}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], new_input
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_SCAN_INTERVAL] == 60


async def test_reconfigure_entity_not_found(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Reconfigure with an unknown entity must show entity_not_found."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**_VALID_USER_INPUT, CONF_GRID_ENTITY: "sensor.ghost"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "entity_not_found"}


# ── Options flow — device management ─────────────────────────────────────────


async def test_options_init_menu_no_devices(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Init menu must only offer 'add_device' when no devices are configured."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["add_device"]


async def test_options_init_menu_with_devices(
    hass: HomeAssistant, mock_config_entry_with_device: MockConfigEntry
) -> None:
    """Init menu must offer edit and remove options when devices exist."""
    mock_config_entry_with_device.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(
        mock_config_entry_with_device.entry_id
    )

    assert result["type"] is FlowResultType.MENU
    assert set(result["menu_options"]) == {"add_device", "select_edit", "select_remove"}


async def test_options_add_device(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """The full add_device path must store a new device with a generated UUID."""
    mock_config_entry.add_to_hass(hass)
    _set_entity_states(hass, DEVICE_SWITCH)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_device"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "add_device"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_DEVICE_NAME: "EV Charger",
            CONF_DEVICE_PRIORITY: 1,
            CONF_DEVICE_MIN_BATTERY_STATE: 0,
            CONF_DEVICE_ESTIMATED_POWER: 1500,
            CONF_DEVICE_SWITCH_ENTITY: DEVICE_SWITCH,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    devices: list[dict] = mock_config_entry.options[CONF_DEVICES]
    assert len(devices) == 1
    added = devices[0]
    assert added[CONF_DEVICE_NAME] == "EV Charger"
    assert added[CONF_DEVICE_ESTIMATED_POWER] == 1500
    assert CONF_DEVICE_ID in added  # UUID was generated


async def test_options_edit_device(
    hass: HomeAssistant, mock_config_entry_with_device: MockConfigEntry
) -> None:
    """Editing a device must update its fields while preserving its ID."""
    mock_config_entry_with_device.add_to_hass(hass)
    _set_entity_states(hass, DEVICE_SWITCH)

    result = await hass.config_entries.options.async_init(
        mock_config_entry_with_device.entry_id
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "select_edit"}
    )
    assert result["step_id"] == "select_edit"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_DEVICE_ID: DEVICE_ID}
    )
    assert result["step_id"] == "edit_device"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_DEVICE_NAME: "EV Charger Updated",
            CONF_DEVICE_PRIORITY: 2,
            CONF_DEVICE_MIN_BATTERY_STATE: 20,
            CONF_DEVICE_ESTIMATED_POWER: 2000,
            CONF_DEVICE_SWITCH_ENTITY: DEVICE_SWITCH,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    device = mock_config_entry_with_device.options[CONF_DEVICES][0]
    assert device[CONF_DEVICE_ID] == DEVICE_ID  # ID preserved
    assert device[CONF_DEVICE_NAME] == "EV Charger Updated"
    assert device[CONF_DEVICE_ESTIMATED_POWER] == 2000


async def test_options_remove_device(
    hass: HomeAssistant, mock_config_entry_with_device: MockConfigEntry
) -> None:
    """Removing a device must leave an empty device list."""
    mock_config_entry_with_device.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(
        mock_config_entry_with_device.entry_id
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "select_remove"}
    )
    assert result["step_id"] == "select_remove"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_DEVICE_ID: DEVICE_ID}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry_with_device.options[CONF_DEVICES] == []
