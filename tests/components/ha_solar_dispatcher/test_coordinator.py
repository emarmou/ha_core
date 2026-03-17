"""Tests for the Solar Dispatcher coordinator (dispatch algorithm)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.components.ha_solar_dispatcher.const import (
    CONF_DEVICE_ESTIMATED_POWER,
    CONF_DEVICE_ID,
    CONF_DEVICE_MIN_BATTERY_STATE,
    CONF_DEVICE_NAME,
    CONF_DEVICE_POWER_ENTITY,
    CONF_DEVICE_PRIORITY,
    CONF_DEVICE_SWITCH_ENTITY,
    CONF_DEVICES,
    CONF_GRID_ENTITY,
    CONF_GRID_INVERT,
    CONF_SCAN_INTERVAL,
    DOMAIN,
    DispatchPriority,
)
from homeassistant.components.ha_solar_dispatcher.coordinator import (
    SolarDispatcherCoordinator,
    SolarDispatcherData,
)
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

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

_DEVICE_2_ID = "bbbbbbbb-0000-0000-0000-000000000002"
_SWITCH_2 = "switch.water_heater"

_BASE_DEVICE: dict[str, Any] = {
    CONF_DEVICE_ID: DEVICE_ID,
    CONF_DEVICE_NAME: "EV Charger",
    CONF_DEVICE_PRIORITY: DispatchPriority.NORMAL,
    CONF_DEVICE_MIN_BATTERY_STATE: 0,
    CONF_DEVICE_ESTIMATED_POWER: 1500,
    CONF_DEVICE_SWITCH_ENTITY: DEVICE_SWITCH,
}


def _make_coordinator(
    hass: HomeAssistant,
    *,
    grid_entity: str = GRID_ENTITY,
    grid_invert: bool = False,
    extra_data: dict | None = None,
    devices: list[dict] | None = None,
) -> SolarDispatcherCoordinator:
    """Construct a coordinator backed by a MockConfigEntry."""
    data: dict[str, Any] = {
        CONF_GRID_ENTITY: grid_entity,
        CONF_GRID_INVERT: grid_invert,
        CONF_SCAN_INTERVAL: 30,
        **(extra_data or {}),
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=grid_entity,
        data=data,
        options={CONF_DEVICES: devices or []},
    )
    entry.add_to_hass(hass)
    return SolarDispatcherCoordinator(hass, entry)


async def _run(
    coordinator: SolarDispatcherCoordinator,
) -> tuple[SolarDispatcherData, AsyncMock, AsyncMock]:
    """Run the algorithm and return (data, mock_turn_on, mock_turn_off)."""
    with (
        patch.object(coordinator, "_turn_on", new_callable=AsyncMock) as mock_on,
        patch.object(coordinator, "_turn_off", new_callable=AsyncMock) as mock_off,
    ):
        data = await coordinator._async_update_data()
    return data, mock_on, mock_off


# ── Surplus calculation ───────────────────────────────────────────────────────


async def test_surplus_grid_only(hass: HomeAssistant) -> None:
    """Surplus equals grid power when no optional entities are configured."""
    hass.states.async_set(GRID_ENTITY, "-2000")
    coordinator = _make_coordinator(hass)

    data, _, _ = await _run(coordinator)

    assert data.surplus == pytest.approx(-2000)


async def test_grid_invert_negates_value(hass: HomeAssistant) -> None:
    """When grid_invert is True the grid reading must be negated."""
    # Grid reports +2000 W (importing), invert → surplus = -2000 W.
    hass.states.async_set(GRID_ENTITY, "2000")
    coordinator = _make_coordinator(hass, grid_invert=True)

    data, _, _ = await _run(coordinator)

    assert data.surplus == pytest.approx(-2000)


async def test_battery_charge_adds_to_surplus(hass: HomeAssistant) -> None:
    """Battery charging power must be added to the grid surplus."""
    hass.states.async_set(GRID_ENTITY, "-1000")
    hass.states.async_set(BATTERY_CHARGE_ENTITY, "-500")
    coordinator = _make_coordinator(
        hass,
        extra_data={"battery_charge_entity": BATTERY_CHARGE_ENTITY},
    )

    data, _, _ = await _run(coordinator)

    assert data.surplus == pytest.approx(-1500)


async def test_allowance_adds_to_surplus(hass: HomeAssistant) -> None:
    """Allowance ratio must scale the (grid + battery) surplus.

    grid = -1000 W, allowance_ratio = 0.1 → surplus = -1000 × 1.1 = -1100 W.
    """
    hass.states.async_set(GRID_ENTITY, "-1000")
    hass.states.async_set(ALLOWANCE_ENTITY, "0.1")
    coordinator = _make_coordinator(
        hass,
        extra_data={"allowance_entity": ALLOWANCE_ENTITY},
    )

    data, _, _ = await _run(coordinator)

    assert data.surplus == pytest.approx(-1100)


async def test_battery_state_returned_in_data(hass: HomeAssistant) -> None:
    """Battery state of charge must be surfaced in the returned data."""
    hass.states.async_set(GRID_ENTITY, "0")
    hass.states.async_set(BATTERY_STATE_ENTITY, "75")
    coordinator = _make_coordinator(
        hass,
        extra_data={"battery_state_entity": BATTERY_STATE_ENTITY},
    )

    data, _, _ = await _run(coordinator)

    assert data.battery_state == pytest.approx(75)


# ── Grid entity errors ────────────────────────────────────────────────────────


async def test_grid_unavailable_raises(hass: HomeAssistant) -> None:
    """An unavailable grid entity must raise UpdateFailed."""
    hass.states.async_set(GRID_ENTITY, STATE_UNAVAILABLE)
    coordinator = _make_coordinator(hass)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_grid_entity_missing_raises(hass: HomeAssistant) -> None:
    """A missing (never-set) grid entity must raise UpdateFailed."""
    coordinator = _make_coordinator(hass)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


# ── Turn ON logic ─────────────────────────────────────────────────────────────


async def test_surplus_turns_on_device(hass: HomeAssistant) -> None:
    """Device OFF + sufficient surplus → turn_on must be called."""
    hass.states.async_set(GRID_ENTITY, "2000")  # 2 kW exporting (positive = exporting)
    hass.states.async_set(DEVICE_SWITCH, STATE_OFF)
    coordinator = _make_coordinator(hass, devices=[_BASE_DEVICE])

    data, mock_on, mock_off = await _run(coordinator)

    mock_on.assert_called_once_with(DEVICE_SWITCH)
    mock_off.assert_not_called()
    # Surplus decremented by estimated power.
    assert data.surplus == pytest.approx(2000 - 1500)


async def test_insufficient_surplus_keeps_device_off(hass: HomeAssistant) -> None:
    """Device OFF + insufficient surplus → neither service must be called."""
    hass.states.async_set(GRID_ENTITY, "1000")  # Only 1 kW surplus, device needs 1.5 kW
    hass.states.async_set(DEVICE_SWITCH, STATE_OFF)
    coordinator = _make_coordinator(hass, devices=[_BASE_DEVICE])

    _, mock_on, mock_off = await _run(coordinator)

    mock_on.assert_not_called()
    mock_off.assert_not_called()


async def test_min_battery_prevents_turn_on(hass: HomeAssistant) -> None:
    """Battery below min_battery_state must prevent the device being turned on."""
    device = {**_BASE_DEVICE, CONF_DEVICE_MIN_BATTERY_STATE: 80}
    hass.states.async_set(
        GRID_ENTITY, "2000"
    )  # Enough surplus; only battery blocks turn-on
    hass.states.async_set(DEVICE_SWITCH, STATE_OFF)
    hass.states.async_set(BATTERY_STATE_ENTITY, "50")
    coordinator = _make_coordinator(
        hass,
        devices=[device],
        extra_data={"battery_state_entity": BATTERY_STATE_ENTITY},
    )

    _, mock_on, _ = await _run(coordinator)

    mock_on.assert_not_called()


# ── Turn OFF logic ────────────────────────────────────────────────────────────


async def test_exhausted_surplus_turns_off_device(hass: HomeAssistant) -> None:
    """Device ON + non-positive surplus → turn_off must be called."""
    hass.states.async_set(GRID_ENTITY, "-100")  # Importing from grid, surplus < 0
    hass.states.async_set(DEVICE_SWITCH, STATE_ON)
    coordinator = _make_coordinator(hass, devices=[_BASE_DEVICE])

    data, mock_on, mock_off = await _run(coordinator)

    mock_on.assert_not_called()
    mock_off.assert_called_once_with(DEVICE_SWITCH)
    # Surplus increased by estimated power after turn-off.
    assert data.surplus == pytest.approx(-100 + 1500)


async def test_sufficient_surplus_keeps_device_on(hass: HomeAssistant) -> None:
    """Device ON + positive surplus → neither service must be called."""
    hass.states.async_set(GRID_ENTITY, "2000")  # Exporting, surplus > 0
    hass.states.async_set(DEVICE_SWITCH, STATE_ON)
    coordinator = _make_coordinator(hass, devices=[_BASE_DEVICE])

    _, mock_on, mock_off = await _run(coordinator)

    mock_on.assert_not_called()
    mock_off.assert_not_called()


async def test_battery_below_threshold_turns_off_running_device(
    hass: HomeAssistant,
) -> None:
    """Battery dropping below threshold while device is ON → turn_off."""
    device = {**_BASE_DEVICE, CONF_DEVICE_MIN_BATTERY_STATE: 50}
    hass.states.async_set(
        GRID_ENTITY, "2000"
    )  # Positive surplus; only battery triggers turn-off
    hass.states.async_set(DEVICE_SWITCH, STATE_ON)
    hass.states.async_set(BATTERY_STATE_ENTITY, "30")
    coordinator = _make_coordinator(
        hass,
        devices=[device],
        extra_data={"battery_state_entity": BATTERY_STATE_ENTITY},
    )

    _, _, mock_off = await _run(coordinator)

    mock_off.assert_called_once_with(DEVICE_SWITCH)


# ── Actual-power recovery on turn-off ─────────────────────────────────────────


async def test_actual_power_used_on_turn_off(hass: HomeAssistant) -> None:
    """When a measurement entity is configured, actual power is used for recovery."""
    power_entity = "sensor.ev_power"
    device = {**_BASE_DEVICE, CONF_DEVICE_POWER_ENTITY: power_entity}
    hass.states.async_set(GRID_ENTITY, "-100")  # Importing; triggers turn-off
    hass.states.async_set(DEVICE_SWITCH, STATE_ON)
    hass.states.async_set(power_entity, "1800")  # Consuming more than estimated
    coordinator = _make_coordinator(hass, devices=[device])

    data, _, mock_off = await _run(coordinator)

    mock_off.assert_called_once_with(DEVICE_SWITCH)
    # Surplus recovered by actual power (1800) not estimated (1500).
    assert data.surplus == pytest.approx(-100 + 1800)


async def test_actual_power_fallback_to_estimated(hass: HomeAssistant) -> None:
    """When the measurement entity is unavailable, estimated power is used."""
    power_entity = "sensor.ev_power"
    device = {**_BASE_DEVICE, CONF_DEVICE_POWER_ENTITY: power_entity}
    hass.states.async_set(GRID_ENTITY, "-100")  # Importing; triggers turn-off
    hass.states.async_set(DEVICE_SWITCH, STATE_ON)
    hass.states.async_set(power_entity, STATE_UNAVAILABLE)
    coordinator = _make_coordinator(hass, devices=[device])

    data, _, mock_off = await _run(coordinator)

    mock_off.assert_called_once_with(DEVICE_SWITCH)
    assert data.surplus == pytest.approx(-100 + 1500)  # Estimated used as fallback


# ── Priority ordering ─────────────────────────────────────────────────────────


async def test_priority_order_respected(hass: HomeAssistant) -> None:
    """Higher-priority device must receive budget first."""
    # Only 1800 W available — enough for device_1 (1500 W) but not device_2 (1500 W).
    device_1 = {**_BASE_DEVICE, CONF_DEVICE_PRIORITY: DispatchPriority.HIGH}
    device_2 = {
        CONF_DEVICE_ID: _DEVICE_2_ID,
        CONF_DEVICE_NAME: "Water Heater",
        CONF_DEVICE_PRIORITY: DispatchPriority.LOW,
        CONF_DEVICE_MIN_BATTERY_STATE: 0,
        CONF_DEVICE_ESTIMATED_POWER: 1500,
        CONF_DEVICE_SWITCH_ENTITY: _SWITCH_2,
    }
    hass.states.async_set(GRID_ENTITY, "1800")  # 1800 W surplus (positive = exporting)
    hass.states.async_set(DEVICE_SWITCH, STATE_OFF)
    hass.states.async_set(_SWITCH_2, STATE_OFF)
    coordinator = _make_coordinator(
        hass, devices=[device_2, device_1]
    )  # Reversed order

    _, mock_on, _ = await _run(coordinator)

    # Only the higher-priority device (priority=1) must be turned on.
    mock_on.assert_called_once_with(DEVICE_SWITCH)


async def test_two_devices_both_turned_on_with_enough_surplus(
    hass: HomeAssistant,
) -> None:
    """When surplus covers both devices, both must be turned on."""
    device_1 = {**_BASE_DEVICE, CONF_DEVICE_PRIORITY: DispatchPriority.HIGH}
    device_2 = {
        CONF_DEVICE_ID: _DEVICE_2_ID,
        CONF_DEVICE_NAME: "Water Heater",
        CONF_DEVICE_PRIORITY: DispatchPriority.LOW,
        CONF_DEVICE_MIN_BATTERY_STATE: 0,
        CONF_DEVICE_ESTIMATED_POWER: 1200,
        CONF_DEVICE_SWITCH_ENTITY: _SWITCH_2,
    }
    hass.states.async_set(GRID_ENTITY, "3000")  # 3 kW surplus covers both devices
    hass.states.async_set(DEVICE_SWITCH, STATE_OFF)
    hass.states.async_set(_SWITCH_2, STATE_OFF)
    coordinator = _make_coordinator(hass, devices=[device_1, device_2])

    _, mock_on, _ = await _run(coordinator)

    assert mock_on.call_count == 2


# ── User-disabled devices ─────────────────────────────────────────────────────


async def test_user_disabled_device_is_skipped(hass: HomeAssistant) -> None:
    """A device disabled by the user (via virtual switch) must be skipped."""
    hass.states.async_set(GRID_ENTITY, "-2000")
    hass.states.async_set(DEVICE_SWITCH, STATE_OFF)
    coordinator = _make_coordinator(hass, devices=[_BASE_DEVICE])
    coordinator.device_enabled[DEVICE_ID] = False

    _, mock_on, mock_off = await _run(coordinator)

    mock_on.assert_not_called()
    mock_off.assert_not_called()


# ── Unavailable real switch ───────────────────────────────────────────────────


async def test_unavailable_switch_is_skipped(hass: HomeAssistant) -> None:
    """A real switch in unavailable state must be silently skipped."""
    hass.states.async_set(GRID_ENTITY, "-2000")
    hass.states.async_set(DEVICE_SWITCH, STATE_UNAVAILABLE)
    coordinator = _make_coordinator(hass, devices=[_BASE_DEVICE])

    _, mock_on, mock_off = await _run(coordinator)

    mock_on.assert_not_called()
    mock_off.assert_not_called()


# ── Priority preemption ───────────────────────────────────────────────────────


async def test_high_priority_device_preempts_lower_priority_device(
    hass: HomeAssistant,
) -> None:
    """Low-priority device turned off when a high-priority device can be served.

    Cycle 1 — grid 1400 W (no devices running):
      Device B (HIGH, 1800 W) cannot turn on (1800 > 1400 surplus).
      Device A (LOW,  1300 W) turns on      (1300 ≤ 1400 surplus).

    Cycle 2 — grid 500 W (Device A is ON consuming 1300 W, solar = 1800 W):
      Direct surplus = 500 W < 1800 W, so B cannot turn on without preemption.
      Preemption budget = 500 (surplus) + 1300 (A's power) = 1800 W ≥ 1800 W.
      → Turn off A (+1300 W), turn on B (−1800 W): surplus = 500 + 1300 − 1800 = 0 W.

    The net effect is that the algorithm preempts the lower-priority device
    to make room for the higher-priority one.
    """
    _DEVICE_A_ID = DEVICE_ID
    _DEVICE_B_ID = _DEVICE_2_ID
    _SWITCH_A = DEVICE_SWITCH
    _SWITCH_B = _SWITCH_2

    device_a = {
        CONF_DEVICE_ID: _DEVICE_A_ID,
        CONF_DEVICE_NAME: "Device A",
        CONF_DEVICE_PRIORITY: DispatchPriority.LOW,
        CONF_DEVICE_MIN_BATTERY_STATE: 0,
        CONF_DEVICE_ESTIMATED_POWER: 1300,
        CONF_DEVICE_SWITCH_ENTITY: _SWITCH_A,
    }
    device_b = {
        CONF_DEVICE_ID: _DEVICE_B_ID,
        CONF_DEVICE_NAME: "Device B",
        CONF_DEVICE_PRIORITY: DispatchPriority.HIGH,
        CONF_DEVICE_MIN_BATTERY_STATE: 0,
        CONF_DEVICE_ESTIMATED_POWER: 1800,
        CONF_DEVICE_SWITCH_ENTITY: _SWITCH_B,
    }

    # ── Cycle 1: only device A can be served ─────────────────────────────────
    hass.states.async_set(GRID_ENTITY, "1400")
    hass.states.async_set(_SWITCH_A, STATE_OFF)
    hass.states.async_set(_SWITCH_B, STATE_OFF)
    coordinator = _make_coordinator(hass, devices=[device_a, device_b])

    _, mock_on, mock_off = await _run(coordinator)

    mock_on.assert_called_once_with(_SWITCH_A)
    mock_off.assert_not_called()

    # ── Cycle 2: device A is running; solar has risen so total budget = 1800 W ─
    # Grid reads 500 W (= 1800 W solar − 1300 W consumed by A).
    # Preemption: surplus(500) + A's power(1300) = 1800 W ≥ B's need(1800 W).
    # → Turn off A (+1300 W), turn on B (−1800 W): final surplus = 0 W.
    hass.states.async_set(GRID_ENTITY, str(1800 - 1300))
    hass.states.async_set(_SWITCH_A, STATE_ON)  # Result of cycle 1
    hass.states.async_set(_SWITCH_B, STATE_OFF)

    data, mock_on, mock_off = await _run(coordinator)

    mock_on.assert_called_once_with(_SWITCH_B)
    mock_off.assert_called_once_with(_SWITCH_A)
    # After A turns off (+1300 W) and B turns on (−1800 W): 500 + 1300 − 1800 = 0 W.
    assert data.surplus == pytest.approx(0)
