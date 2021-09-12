"""Support for Intesis Modbus RTU gateways, tested with Hitachi."""
from __future__ import annotations

import logging
import time

import voluptuous as vol

from homeassistant.components.climate import PLATFORM_SCHEMA, ClimateEntity
from homeassistant.components.climate.const import (
    HVAC_MODE_OFF,
    HVAC_MODE_AUTO,
    HVAC_MODE_HEAT,
    HVAC_MODE_COOL,
    HVAC_MODE_DRY,
    HVAC_MODE_FAN_ONLY,
    FAN_AUTO,
    FAN_LOW,
    FAN_MEDIUM,
    FAN_HIGH,
    SUPPORT_FAN_MODE,
    SUPPORT_TARGET_TEMPERATURE,
)
from homeassistant.components.modbus import get_hub
from homeassistant.components.modbus.const import (
    CALL_TYPE_REGISTER_HOLDING,
    CALL_TYPE_REGISTER_INPUT,
    CALL_TYPE_WRITE_REGISTER,
    CONF_HUB,
    DEFAULT_HUB,
)
from homeassistant.components.modbus.modbus import ModbusHub
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_NAME,
    CONF_SLAVE,
    DEVICE_DEFAULT_NAME,
    TEMP_CELSIUS,
    PRECISION_WHOLE
)
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_HUB, default=DEFAULT_HUB): cv.string,
        vol.Required(CONF_SLAVE): vol.All(int, vol.Range(min=0, max=32)),
        vol.Optional(CONF_NAME, default=DEVICE_DEFAULT_NAME): cv.string,
    }
)

_LOGGER = logging.getLogger(__name__)

SUPPORT_FLAGS = SUPPORT_TARGET_TEMPERATURE | SUPPORT_FAN_MODE

HVAC_MODES_MAP = [
    HVAC_MODE_AUTO,
    HVAC_MODE_HEAT,
    HVAC_MODE_DRY,
    HVAC_MODE_FAN_ONLY,
    HVAC_MODE_COOL
]

FAN_MODES_MAP = [
    FAN_AUTO,
    FAN_LOW,
    FAN_MEDIUM,
    FAN_HIGH,
    'super_high'
]


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities,
    discovery_info: DiscoveryInfoType = None,
):
    """Set up the Intesis Modbus RTU Platform."""
    modbus_slave = config.get(CONF_SLAVE)
    name = config.get(CONF_NAME)
    hub = get_hub(hass, config[CONF_HUB])
    async_add_entities([IntesisModbusRTU(hub, modbus_slave, name)], True)


class IntesisModbusRTU(ClimateEntity):
    """Representation of an Intesis AC unit."""

    _attr_min_temp = 17
    _attr_max_temp = 30
    _attr_precision = 1.0
    _attr_target_temperature_step = 1.0

    def __init__(
        self, hub: ModbusHub, modbus_slave: int | None, name: str | None
    ) -> None:
        """Initialize the unit."""
        self._hub = hub
        self._name = name
        self._slave = modbus_slave
        self._target_temperature = None
        self._current_temperature = None
        self._current_fan_mode = None
        self._fan_modes = [FAN_LOW, FAN_MEDIUM, FAN_HIGH]
        self._current_hvac_mode = None
        self._hvac_modes = [
            HVAC_MODE_OFF, 
            HVAC_MODE_HEAT, 
            HVAC_MODE_COOL, 
            HVAC_MODE_DRY, 
            HVAC_MODE_FAN_ONLY
            ]
        _LOGGER.debug("Initialised Intesis AC unit")    

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return SUPPORT_FLAGS

    async def async_update(self):
        """Update unit attributes."""
        _LOGGER.debug("Updating state")
        result = await self._hub.async_pymodbus_call(
            self._slave, 0, 24, CALL_TYPE_REGISTER_HOLDING
        )
        _LOGGER.debug(result.registers)

        state = result.registers

        if(state[0] == 0):
            self._current_hvac_mode = HVAC_MODE_OFF
        else:
            self._current_hvac_mode = HVAC_MODES_MAP[state[1]]
        _LOGGER.debug(f"_current_hvac_mode: {self._current_hvac_mode}")

        self._current_fan_mode = FAN_MODES_MAP[state[2]]
        _LOGGER.debug(f"_current_fan_mode: {self._current_fan_mode}")

        self._target_temperature = state[4]
        _LOGGER.debug(f"_target_temperature: {self._target_temperature}")

        self._current_temperature = state[5]
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
        return TEMP_CELSIUS

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
    def hvac_modes(self) -> list[str]:
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

        if await self._async_write_int16_to_register(4, target_temperature):
            self._target_temperature = target_temperature
            self._async_trigger_refresh_after_change()
        else:
            _LOGGER.error("Modbus error setting target temperature to Intesis")

    async def async_set_hvac_mode(self, hvac_mode):
        if(hvac_mode == HVAC_MODE_OFF):
            await self._async_write_int16_to_register(0, 0)
        else:
            register_value = HVAC_MODES_MAP.index(hvac_mode)
            if(register_value > 0):
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
        result = await self._hub.async_pymodbus_call(
            self._slave, register, value, CALL_TYPE_WRITE_REGISTER
        )
        if result == -1:
            return False
        return True

    def _async_trigger_refresh_after_change(self):
        time.sleep(1)
        return self.async_schedule_update_ha_state(force_refresh=True)