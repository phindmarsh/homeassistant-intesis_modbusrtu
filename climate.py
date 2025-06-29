"""Support for Intesis Modbus RTU gateways, tested with Hitachi."""

from __future__ import annotations

import logging
import time

import voluptuous as vol

from homeassistant.components.climate import PLATFORM_SCHEMA, ClimateEntity
from homeassistant.components.climate.const import (
    HVACMode,
    ClimateEntityFeature,
    FAN_AUTO,
    FAN_LOW,
    FAN_MEDIUM,
    FAN_HIGH,
)
from homeassistant.components.modbus import get_hub
from homeassistant.components.modbus.const import (
    CALL_TYPE_REGISTER_HOLDING,
    CALL_TYPE_REGISTER_INPUT,
    CALL_TYPE_WRITE_REGISTER,
    ATTR_HUB,
    DEFAULT_HUB,
)
from homeassistant.components.modbus.modbus import ModbusHub
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_NAME,
    CONF_SLAVE,
    DEVICE_DEFAULT_NAME,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.event import async_call_later

# Custom configuration constant
CONF_TEMPERATURE_FACTOR = "temperature_factor"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(ATTR_HUB, default=DEFAULT_HUB): cv.string,
        vol.Required(CONF_SLAVE): vol.All(int, vol.Range(min=0, max=32)),
        vol.Optional(CONF_NAME, default=DEVICE_DEFAULT_NAME): cv.string,
        vol.Optional(CONF_TEMPERATURE_FACTOR, default=1): vol.All(
            vol.Coerce(float), vol.Range(min=0, min_included=False)
        ),
    }
)

_LOGGER = logging.getLogger(__name__)

SUPPORT_FLAGS = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE

HVAC_MODES_MAP = [
    HVACMode.AUTO,
    HVACMode.HEAT,
    HVACMode.DRY,
    HVACMode.FAN_ONLY,
    HVACMode.COOL,
]

FAN_MODES_MAP = [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH]


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities,
    discovery_info: DiscoveryInfoType = None,
):
    """Set up the Intesis Modbus RTU Platform."""
    modbus_slave = config.get(CONF_SLAVE)
    name = config.get(CONF_NAME)
    temp_factor = config.get(CONF_TEMPERATURE_FACTOR)
    hub = get_hub(hass, config[ATTR_HUB])
    async_add_entities([IntesisModbusRTU(hub, modbus_slave, name, temp_factor)], True)


class IntesisModbusRTU(ClimateEntity):
    """Representation of an Intesis AC unit."""

    _attr_min_temp = 17
    _attr_max_temp = 30
    _attr_precision = 1.0
    _attr_target_temperature_step = 1.0

    def __init__(
        self,
        hub: ModbusHub,
        modbus_slave: int | None,
        name: str | None,
        temp_factor: float = 1.0,
    ) -> None:
        """Initialize the unit."""
        self._hub = hub
        self._name = name
        self._slave = modbus_slave
        self._temp_factor = (
            float(temp_factor) if temp_factor and temp_factor > 0 else 1.0
        )
        # Update precision/step based on factor (<1 => finer)
        if self._temp_factor < 1:
            self._attr_precision = self._temp_factor
            self._attr_target_temperature_step = self._temp_factor
        else:
            self._attr_precision = 1.0
            self._attr_target_temperature_step = 1.0
        self._target_temperature = None
        self._current_temperature = None
        self._current_fan_mode = None
        self._fan_modes = [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH]
        self._current_hvac_mode = None
        self._hvac_modes = [
            HVACMode.OFF,
            HVACMode.HEAT,
            HVACMode.COOL,
            HVACMode.DRY,
            HVACMode.FAN_ONLY,
        ]
        _LOGGER.debug("Initialised Intesis AC unit")

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return SUPPORT_FLAGS

    async def async_update(self):
        """Update unit attributes."""
        _LOGGER.debug("Updating state")
        result = await self._hub.async_pb_call(
            self._slave, 0, 24, CALL_TYPE_REGISTER_HOLDING
        )
        # The Modbus call may return None or -1 on communication errors.
        if not result or result == -1 or not hasattr(result, "registers"):
            _LOGGER.error("Modbus read failed, skipping state update")
            return

        _LOGGER.debug(result.registers)

        state = result.registers

        if state[0] == 0:
            self._current_hvac_mode = HVACMode.OFF
        else:
            self._current_hvac_mode = HVAC_MODES_MAP[state[1]]
        _LOGGER.debug(f"_current_hvac_mode: {self._current_hvac_mode}")

        self._current_fan_mode = FAN_MODES_MAP[state[2]]
        _LOGGER.debug(f"_current_fan_mode: {self._current_fan_mode}")

        self._target_temperature = state[4] * self._temp_factor
        _LOGGER.debug(f"_target_temperature: {self._target_temperature}")

        self._current_temperature = state[5] * self._temp_factor
        _LOGGER.debug(f"_current_temperature: {self._current_temperature}")

        _LOGGER.debug("Finished updating state")

    @property
    def should_poll(self):
        """Return the polling state."""
        return True

    @property
    def name(self):
        """Return the name of the climate device."""
        return self._name

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return UnitOfTemperature.CELSIUS

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._current_temperature

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temperature

    @property
    def hvac_mode(self):
        """Return current operation ie. heat, cool, idle."""
        return self._current_hvac_mode

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of available hvac operation modes."""
        return self._hvac_modes

    @property
    def fan_mode(self):
        """Return the fan setting."""
        return self._current_fan_mode

    @property
    def fan_modes(self):
        """Return the list of available fan modes."""
        return self._fan_modes

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        if kwargs.get(ATTR_TEMPERATURE) is not None:
            target_temperature = kwargs.get(ATTR_TEMPERATURE)
        else:
            _LOGGER.error("Received invalid temperature")
            return

        register_value = round(target_temperature / self._temp_factor)
        if await self._async_write_int16_to_register(4, register_value):
            self._target_temperature = target_temperature
            self._async_trigger_refresh_after_change()
        else:
            _LOGGER.error("Modbus error setting target temperature to Intesis")

    async def async_set_hvac_mode(self, hvac_mode):
        if hvac_mode == HVACMode.OFF:
            await self._async_write_int16_to_register(0, 0)
        else:
            register_value = HVAC_MODES_MAP.index(hvac_mode)
            if register_value > 0:
                _LOGGER.debug(f"Setting mode to {hvac_mode} ({register_value})")
                # set the mode first
                await self._async_write_int16_to_register(1, register_value)
                # ensure unit is also powered on
                await self._async_write_int16_to_register(0, 1)
            else:
                _LOGGER.error(f"Invalid hvac_mode {hvac_mode}")
                return False

        _LOGGER.debug(f"Updated mode to {hvac_mode}, refreshing state")
        self._current_hvac_mode = hvac_mode
        self._async_trigger_refresh_after_change()

    async def async_set_fan_mode(self, fan_mode):
        """Set new fan mode."""
        register_value = FAN_MODES_MAP.index(fan_mode)
        _LOGGER.debug(f"Setting fan mode to {fan_mode} ({register_value})")
        if await self._async_write_int16_to_register(2, register_value):
            self._current_fan_mode = fan_mode
            self._async_trigger_refresh_after_change()
        else:
            _LOGGER.error(f"Modbus error setting fan mode {fan_mode}")

    async def _async_write_int16_to_register(self, register, value) -> bool:
        value = int(value)
        result = await self._hub.async_pb_call(
            self._slave, register, value, CALL_TYPE_WRITE_REGISTER
        )
        if result == -1:
            return False
        return True

    def _async_trigger_refresh_after_change(self):
        return self.async_schedule_update_ha_state(force_refresh=True)
