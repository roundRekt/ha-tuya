"""Support for Tuya Fan."""

from dataclasses import dataclass
import json
import math
from typing import Any, override

from tuya_device_handlers.definition.fan import FanDefinition, get_default_definition
from tuya_device_handlers.device_wrapper.common import (
    DPCodeBooleanWrapper,
    DPCodeEnumWrapper,
)
from tuya_device_handlers.device_wrapper.fan import (
    FanDirectionEnumWrapper,
    FanSpeedEnumWrapper,
    FanSpeedIntegerWrapper,
)
from tuya_device_handlers.helpers.homeassistant import TuyaFanDirection
from tuya_device_handlers.type_information import (
    EnumTypeInformation,
    IntegerTypeInformation,
)
from tuya_sharing import CustomerDevice, Manager

from homeassistant.components.fan import (
    DIRECTION_FORWARD,
    DIRECTION_REVERSE,
    FanEntity,
    FanEntityDescription,
    FanEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DPCode, TUYA_DISCOVERY_NEW, DeviceCategory
from .coordinator import TuyaConfigEntry
from .entity import TuyaEntity, TuyaEntityDescription

PRESET_AUTO = "auto"
PRESET_PURIFY = "purify"
PRESET_VENTILATION = "ventilation"
PRESET_SLEEP = "sleep"
PRESET_MANUAL = "manual"

_EXPANDED_SWITCH_DPCODES = (
    "switch_fan",
    "fan_switch",
    "switch",
    "switch_ventilate",
    "power",
)
_EXPANDED_SPEED_DPCODES = (
    "fan_speed_percent",
    "fan_speed",
    "speed",
    "fan_speed_enum",
    "supply_fan_speed",
    "exhaust_fan_speed",
    "windspeed",
    "air_volume",
    "level",
)
_EXPANDED_MODE_DPCODES = (
    "mode",
    "fan_mode",
    "work_mode",
    "loop_mode",
)


@dataclass(frozen=True)
class TuyaFanEntityDescription(TuyaEntityDescription, FanEntityDescription):
    """Describes a Tuya fan entity."""


FANS: dict[DeviceCategory, TuyaFanEntityDescription] = {
    DeviceCategory.CS: TuyaFanEntityDescription(key=""),
    DeviceCategory.FS: TuyaFanEntityDescription(key=""),
    DeviceCategory.FSD: TuyaFanEntityDescription(key=""),
    DeviceCategory.FSKG: TuyaFanEntityDescription(key=""),
    DeviceCategory.KJ: TuyaFanEntityDescription(key="", translation_key="fresh_air"),
    DeviceCategory.KS: TuyaFanEntityDescription(key=""),
    DeviceCategory.XFJ: TuyaFanEntityDescription(key="", translation_key="fresh_air"),
}

_TUYA_TO_HA_DIRECTION_MAPPINGS = {
    TuyaFanDirection.FORWARD: DIRECTION_FORWARD,
    TuyaFanDirection.REVERSE: DIRECTION_REVERSE,
}
_HA_TO_TUYA_DIRECTION_MAPPINGS = {
    v: k for k, v in _TUYA_TO_HA_DIRECTION_MAPPINGS.items()
}


def get_fan_definition(device: CustomerDevice) -> FanDefinition | None:
    """Get the fan definition for a device, with fresh air and extended DP support."""
    definition = get_default_definition(device)
    if definition is not None:
        if definition.speed_wrapper is None:
            definition.speed_wrapper = (
                FanSpeedIntegerWrapper.find_dpcode(
                    device, _EXPANDED_SPEED_DPCODES, prefer_function=True
                )
                or FanSpeedEnumWrapper.find_dpcode(
                    device, _EXPANDED_SPEED_DPCODES, prefer_function=True
                )
            )
        if definition.mode_wrapper is None:
            definition.mode_wrapper = DPCodeEnumWrapper.find_dpcode(
                device, _EXPANDED_MODE_DPCODES, prefer_function=True
            )
        if definition.switch_wrapper is None:
            definition.switch_wrapper = DPCodeBooleanWrapper.find_dpcode(
                device, _EXPANDED_SWITCH_DPCODES, prefer_function=True
            )
        return definition

    properties_to_check: set[str] = {
        *_EXPANDED_SWITCH_DPCODES,
        *_EXPANDED_SPEED_DPCODES,
        *_EXPANDED_MODE_DPCODES,
    }
    if not any(
        (code in device.function or code in device.status or code in device.status_range)
        for code in properties_to_check
    ):
        return None

    return FanDefinition(
        direction_wrapper=FanDirectionEnumWrapper.find_dpcode(
            device, ("fan_direction",), prefer_function=True
        ),
        mode_wrapper=DPCodeEnumWrapper.find_dpcode(
            device, _EXPANDED_MODE_DPCODES, prefer_function=True
        ),
        oscillate_wrapper=DPCodeBooleanWrapper.find_dpcode(
            device, ("switch_horizontal", "switch_vertical"), prefer_function=True
        ),
        speed_wrapper=FanSpeedIntegerWrapper.find_dpcode(
            device, _EXPANDED_SPEED_DPCODES, prefer_function=True
        )
        or FanSpeedEnumWrapper.find_dpcode(
            device, _EXPANDED_SPEED_DPCODES, prefer_function=True
        ),
        switch_wrapper=DPCodeBooleanWrapper.find_dpcode(
            device, _EXPANDED_SWITCH_DPCODES, prefer_function=True
        ),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TuyaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up tuya fan dynamically through tuya discovery."""
    manager = entry.runtime_data.manager

    @callback
    def async_discover_device(device_ids: list[str]) -> None:
        """Discover and add a discovered tuya fan."""
        entities: list[TuyaFanEntity] = []
        for device_id in device_ids:
            device = manager.device_map[device_id]
            if (description := FANS.get(device.category)) and (
                definition := get_fan_definition(device)
            ):
                entities.append(TuyaFanEntity(device, manager, description, definition))
        async_add_entities(entities)

    async_discover_device([*manager.device_map])

    entry.async_on_unload(
        async_dispatcher_connect(hass, TUYA_DISCOVERY_NEW, async_discover_device)
    )


class TuyaFanEntity(TuyaEntity, FanEntity):
    """Tuya Fan Device."""

    _attr_name = None

    def __init__(
        self,
        device: CustomerDevice,
        device_manager: Manager,
        description: TuyaFanEntityDescription,
        definition: FanDefinition,
    ) -> None:
        """Init Tuya Fan Device."""
        super().__init__(device, device_manager, description)
        self._direction_wrapper = definition.direction_wrapper
        self._mode_wrapper = definition.mode_wrapper
        self._oscillate_wrapper = definition.oscillate_wrapper
        self._speed_wrapper = definition.speed_wrapper
        self._switch_wrapper = definition.switch_wrapper

        self._speed_dp: str | None = None
        self._speed_type: str | None = None
        self._speed_min: int = 1
        self._speed_max: int = 6
        self._speed_options: list[str] = []
        self._attr_preset_mode: str | None = None
        self._current_speed: int = 1

        # For fresh air systems (XFJ / KJ / CS fresh air)
        is_fresh_air = (
            device.category in (DeviceCategory.XFJ, DeviceCategory.KJ)
            or any(dp in self.device.status for dp in ("loop_mode", "switch_ventilate"))
            or "fresh" in getattr(device, "product_name", "").lower()
            or "新风" in getattr(device, "name", "")
            or "新风" in getattr(device, "product_name", "")
        )

        # Detect speed DP from device specs
        for dp in _EXPANDED_SPEED_DPCODES:
            if (
                dp in self.device.status_range
                or dp in self.device.function
                or dp in self.device.status
            ):
                self._speed_dp = dp
                break

        if self._speed_dp is None and definition.speed_wrapper:
            self._speed_dp = getattr(definition.speed_wrapper, "dpcode", None)

        if self._speed_dp:
            self._attr_supported_features |= FanEntityFeature.SET_SPEED
            int_info = IntegerTypeInformation.find_dpcode(self.device, self._speed_dp)
            enum_info = EnumTypeInformation.find_dpcode(self.device, self._speed_dp)

            if int_info:
                self._speed_type = "integer"
                self._speed_min = int(int_info.min)
                self._speed_max = int(int_info.max)
                if self._speed_max <= 10:
                    self._attr_speed_count = (
                        int(self._speed_max - self._speed_min + 1)
                        if self._speed_min > 0
                        else int(self._speed_max)
                    )
                elif is_fresh_air:
                    self._attr_speed_count = 6
                    self._speed_min = 1
                    self._speed_max = 6
                else:
                    self._attr_speed_count = 100
            elif enum_info:
                self._speed_type = "enum"
                self._speed_options = enum_info.range
                self._attr_speed_count = len(enum_info.range)
            elif is_fresh_air:
                self._speed_type = "integer"
                self._speed_min = 1
                self._speed_max = 6
                self._attr_speed_count = 6
            else:
                self._attr_speed_count = 100
        elif is_fresh_air or definition.speed_wrapper:
            self._attr_supported_features |= FanEntityFeature.SET_SPEED
            if definition.speed_wrapper and hasattr(definition.speed_wrapper, "options"):
                self._attr_speed_count = len(definition.speed_wrapper.options)
            elif is_fresh_air:
                self._attr_speed_count = 6
                self._speed_type = "integer"
                self._speed_min = 1
                self._speed_max = 6
                self._speed_dp = (
                    getattr(definition.speed_wrapper, "dpcode", None)
                    if definition.speed_wrapper
                    else "speed"
                )
            else:
                self._attr_speed_count = 100

        # Collect preset modes
        modes: list[str] = []
        if definition.mode_wrapper and definition.mode_wrapper.options:
            for opt in definition.mode_wrapper.options:
                if opt not in modes:
                    modes.append(opt)

        for dp in ("mode", "work_mode", "loop_mode"):
            for container in (self.device.status_range, self.device.function):
                if dp in container and (spec := container[dp]):
                    try:
                        vals = (
                            json.loads(spec.values)
                            if isinstance(spec.values, str)
                            else spec.values
                        )
                        if isinstance(vals, dict) and "range" in vals:
                            for m in vals["range"]:
                                if m not in modes:
                                    modes.append(m)
                    except Exception:
                        pass

        if is_fresh_air or len(modes) <= 1:
            for std_mode in (
                PRESET_AUTO,
                PRESET_PURIFY,
                PRESET_VENTILATION,
                PRESET_SLEEP,
                PRESET_MANUAL,
            ):
                if std_mode not in modes:
                    modes.append(std_mode)

        if modes:
            self._attr_supported_features |= FanEntityFeature.PRESET_MODE
            self._attr_preset_modes = modes

        if definition.oscillate_wrapper:
            self._attr_supported_features |= FanEntityFeature.OSCILLATE

        if definition.direction_wrapper:
            self._attr_supported_features |= FanEntityFeature.DIRECTION
        if definition.switch_wrapper:
            self._attr_supported_features |= (
                FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
            )
        elif is_fresh_air or "switch" in self.device.status or "switch_fan" in self.device.status:
            self._attr_supported_features |= (
                FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
            )

    @override
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode of the fan."""
        commands: list[dict[str, Any]] = []

        mode_dp = next(
            (
                dp
                for dp in ("mode", "work_mode", "fan_mode")
                if dp in self.device.status
                or dp in self.device.function
                or dp in self.device.status_range
            ),
            "mode",
        )
        has_loop_mode = (
            "loop_mode" in self.device.status
            or "loop_mode" in self.device.function
            or "loop_mode" in self.device.status_range
        )
        has_ventilate = (
            "switch_ventilate" in self.device.status
            or "switch_ventilate" in self.device.function
            or "switch_ventilate" in self.device.status_range
        )

        mode_range: list[str] = []
        for container in (self.device.status_range, self.device.function):
            if mode_dp in container and (spec := container[mode_dp]):
                try:
                    vals = (
                        json.loads(spec.values)
                        if isinstance(spec.values, str)
                        else spec.values
                    )
                    if isinstance(vals, dict) and "range" in vals:
                        mode_range.extend(vals["range"])
                except Exception:
                    pass

        if preset_mode == PRESET_AUTO:
            if has_loop_mode:
                commands.append({"code": "loop_mode", "value": "auto"})
            commands.append({"code": mode_dp, "value": "auto"})
        elif preset_mode == PRESET_PURIFY:
            if has_loop_mode:
                commands.append({"code": "loop_mode", "value": "indoor_loop"})
            if has_ventilate:
                commands.append({"code": "switch_ventilate", "value": False})
            target = next(
                (
                    m
                    for m in (
                        "purify",
                        "clean",
                        "purification",
                        "indoor_loop",
                        "manual",
                    )
                    if m in mode_range
                ),
                "purify",
            )
            commands.append({"code": mode_dp, "value": target})
        elif preset_mode == PRESET_VENTILATION:
            if has_loop_mode:
                commands.append({"code": "loop_mode", "value": "outdoor_loop"})
            if has_ventilate:
                commands.append({"code": "switch_ventilate", "value": True})
            target = next(
                (
                    m
                    for m in (
                        "ventilation",
                        "ventilate",
                        "wind",
                        "exhaust",
                        "outdoor_loop",
                        "manual",
                    )
                    if m in mode_range
                ),
                "ventilation",
            )
            commands.append({"code": mode_dp, "value": target})
        elif preset_mode == PRESET_SLEEP:
            commands.append({"code": mode_dp, "value": "sleep"})
        elif preset_mode == PRESET_MANUAL:
            commands.append({"code": mode_dp, "value": "manual"})
        else:
            commands.append({"code": mode_dp, "value": preset_mode})

        self._attr_preset_mode = preset_mode
        if commands:
            try:
                await self._async_send_commands(commands)
            except Exception:
                pass
        self.async_write_ha_state()

    @override
    async def async_set_direction(self, direction: str) -> None:
        """Set the direction of the fan."""
        if tuya_value := _HA_TO_TUYA_DIRECTION_MAPPINGS.get(direction):
            await self._async_send_wrapper_updates(self._direction_wrapper, tuya_value)

    @override
    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed of the fan, as a percentage."""
        if percentage == 0:
            if self._switch_wrapper is not None:
                await self.async_turn_off()
                return
            if self._speed_dp:
                try:
                    await self._async_send_commands([{"code": self._speed_dp, "value": 0}])
                except Exception:
                    pass
                return

        if (
            self._speed_dp
            and self._speed_type == "integer"
            and self._attr_speed_count <= 10
        ):
            step = math.ceil(percentage / (100 / self._attr_speed_count))
            val = max(self._speed_min, min(self._speed_max, step))
            self._current_speed = int(val)
            for code in (self._speed_dp, DPCode.FAN_SPEED, DPCode.SPEED, DPCode.WINDSPEED, DPCode.AIR_VOLUME):
                if code:
                    try:
                        await self._async_send_commands(
                            [{"code": code, "value": int(val)}]
                        )
                        break
                    except Exception:
                        pass
            self.async_write_ha_state()
            return

        if self._speed_dp and self._speed_type == "enum" and self._speed_options:
            step = math.ceil(percentage / (100 / self._attr_speed_count))
            idx = max(0, min(len(self._speed_options) - 1, step - 1))
            await self._async_send_commands(
                [{"code": self._speed_dp, "value": self._speed_options[idx]}]
            )
            return

        await self._async_send_wrapper_updates(self._speed_wrapper, percentage)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the fan off."""
        if self._switch_wrapper:
            await self._async_send_wrapper_updates(self._switch_wrapper, False)
        elif "switch" in self.device.status:
            await self._async_send_commands([{"code": "switch", "value": False}])
        elif "switch_fan" in self.device.status:
            await self._async_send_commands([{"code": "switch_fan", "value": False}])

    @override
    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan."""
        commands: list[dict[str, Any]] = []
        if self._switch_wrapper:
            commands.extend(self._switch_wrapper.get_update_commands(self.device, True))
        elif "switch" in self.device.status:
            commands.append({"code": "switch", "value": True})
        elif "switch_fan" in self.device.status:
            commands.append({"code": "switch_fan", "value": True})

        if percentage is not None:
            if (
                self._speed_dp
                and self._speed_type == "integer"
                and self._attr_speed_count <= 10
            ):
                step = math.ceil(percentage / (100 / self._attr_speed_count))
                val = max(self._speed_min, min(self._speed_max, step))
                commands.append({"code": self._speed_dp, "value": int(val)})
            elif self._speed_dp and self._speed_type == "enum" and self._speed_options:
                step = math.ceil(percentage / (100 / self._attr_speed_count))
                idx = max(0, min(len(self._speed_options) - 1, step - 1))
                commands.append(
                    {"code": self._speed_dp, "value": self._speed_options[idx]}
                )
            elif self._speed_wrapper is not None:
                commands.extend(
                    self._speed_wrapper.get_update_commands(self.device, percentage)
                )

        if commands:
            await self._async_send_commands(commands)

        if preset_mode is not None:
            await self.async_set_preset_mode(preset_mode)

    @override
    async def async_oscillate(self, oscillating: bool) -> None:
        """Oscillate the fan."""
        await self._async_send_wrapper_updates(self._oscillate_wrapper, oscillating)

    @property
    @override
    def is_on(self) -> bool | None:
        """Return true if fan is on."""
        val = self._read_wrapper(self._switch_wrapper)
        if val is None:
            for dp in ("switch", "switch_fan"):
                if dp in self.device.status:
                    return bool(self.device.status[dp])
        return val

    @property
    @override
    def current_direction(self) -> str | None:
        """Return the current direction of the fan."""
        tuya_value = self._read_wrapper(self._direction_wrapper)
        return _TUYA_TO_HA_DIRECTION_MAPPINGS.get(tuya_value) if tuya_value else None

    @property
    @override
    def oscillating(self) -> bool | None:
        """Return true if the fan is oscillating."""
        return self._read_wrapper(self._oscillate_wrapper)

    @property
    @override
    def preset_mode(self) -> str | None:
        """Return the current preset_mode."""
        if hasattr(self, "_attr_preset_mode") and self._attr_preset_mode is not None:
            return self._attr_preset_mode

        if "loop_mode" in self.device.status:
            loop_val = self.device.status["loop_mode"]
            if loop_val in ("indoor_loop", "purify"):
                return PRESET_PURIFY
            if loop_val in ("outdoor_loop", "ventilation"):
                return PRESET_VENTILATION
            if loop_val == "auto":
                return PRESET_AUTO

        for dp in ("mode", "work_mode", "fan_mode"):
            if dp in self.device.status:
                raw_mode = self.device.status[dp]
                if raw_mode in ("purify", "clean", "purification", "indoor_loop"):
                    return PRESET_PURIFY
                if raw_mode in (
                    "ventilation",
                    "ventilate",
                    "wind",
                    "exhaust",
                    "outdoor_loop",
                ):
                    return PRESET_VENTILATION
                if raw_mode in ("auto", "sleep", "manual"):
                    return raw_mode
                if raw_mode in (self._attr_preset_modes or []):
                    return raw_mode

        if self.device.status.get("switch_ventilate") is True:
            return PRESET_VENTILATION

        return self._read_wrapper(self._mode_wrapper)

    @property
    @override
    def percentage(self) -> int | None:
        """Return the current speed as a percentage."""
        if (
            self._speed_dp
            and self._speed_type == "integer"
            and self._attr_speed_count <= 10
        ):
            raw_val = self.device.status.get(self._speed_dp)
            if raw_val is None:
                for alt in _EXPANDED_SPEED_DPCODES:
                    if alt in self.device.status:
                        raw_val = self.device.status[alt]
                        break
            if raw_val is None:
                raw_val = getattr(self, "_current_speed", 1)
            if raw_val == 0:
                return 0
            try:
                val = int(raw_val)
                return round(val * 100 / self._attr_speed_count)
            except (ValueError, TypeError):
                pass
        elif self._speed_dp and self._speed_type == "enum" and self._speed_options:
            raw_val = self.device.status.get(self._speed_dp)
            if raw_val in self._speed_options:
                pos = self._speed_options.index(raw_val) + 1
                return round(pos * 100 / len(self._speed_options))
            return 0

        return self._read_wrapper(self._speed_wrapper)

