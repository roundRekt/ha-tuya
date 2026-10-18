"""Support for Tuya (de)humidifiers."""

from dataclasses import dataclass
from typing import Any, override

from tuya_device_handlers.definition.humidifier import (
    HumidifierDefinition,
    get_default_definition,
)
from tuya_sharing import CustomerDevice, Manager

from homeassistant.components.humidifier import (
    HumidifierDeviceClass,
    HumidifierEntity,
    HumidifierEntityDescription,
    HumidifierEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import TUYA_DISCOVERY_NEW, DeviceCategory, DPCode
from .coordinator import TuyaConfigEntry
from .entity import TuyaEntity, TuyaEntityDescription
from .util import ActionDPCodeNotFoundError


@dataclass(frozen=True)
class TuyaHumidifierEntityDescription(
    TuyaEntityDescription, HumidifierEntityDescription
):
    """Describe an Tuya (de)humidifier entity."""

    # DPCode, to use. If None, the key will be used as DPCode
    dpcode: DPCode | tuple[DPCode, ...] | None = None

    current_humidity: DPCode | tuple[DPCode, ...] | None = None
    humidity: DPCode | tuple[DPCode, ...] | None = None


HUMIDIFIERS: dict[DeviceCategory, TuyaHumidifierEntityDescription] = {
    DeviceCategory.CS: TuyaHumidifierEntityDescription(
        key=DPCode.SWITCH,
        dpcode=(DPCode.SWITCH, DPCode.SWITCH_SPRAY),
        current_humidity=(
            DPCode.HUMIDITY_INDOOR,
            DPCode.HUMIDITY_CURRENT,
            DPCode.HUMIDITY_VALUE,
        ),
        humidity=(
            DPCode.DEHUMIDITY_SET_VALUE,
            DPCode.HUMIDITY_SET,
        ),
        device_class=HumidifierDeviceClass.DEHUMIDIFIER,
    ),
    DeviceCategory.JSQ: TuyaHumidifierEntityDescription(
        key=DPCode.SWITCH,
        dpcode=(DPCode.SWITCH, DPCode.SWITCH_SPRAY),
        current_humidity=DPCode.HUMIDITY_CURRENT,
        humidity=DPCode.HUMIDITY_SET,
        device_class=HumidifierDeviceClass.HUMIDIFIER,
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TuyaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Tuya (de)humidifier dynamically through Tuya discovery."""
    manager = entry.runtime_data.manager

    @callback
    def async_discover_device(device_ids: list[str]) -> None:
        """Discover and add a discovered Tuya (de)humidifier."""
        entities: list[TuyaHumidifierEntity] = []
        for device_id in device_ids:
            device = manager.device_map[device_id]
            if (description := HUMIDIFIERS.get(device.category)) and (
                definition := get_default_definition(
                    device,
                    switch_dpcode=description.dpcode or description.key,
                    current_humidity_dpcode=description.current_humidity,
                    humidity_dpcode=description.humidity,
                )
            ):
                entities.append(
                    TuyaHumidifierEntity(device, manager, description, definition)
                )
        async_add_entities(entities)

    async_discover_device([*manager.device_map])

    entry.async_on_unload(
        async_dispatcher_connect(hass, TUYA_DISCOVERY_NEW, async_discover_device)
    )


class TuyaHumidifierEntity(TuyaEntity, HumidifierEntity):
    """Tuya (de)humidifier Device."""

    entity_description: TuyaHumidifierEntityDescription
    _attr_name = None

    def __init__(
        self,
        device: CustomerDevice,
        device_manager: Manager,
        description: TuyaHumidifierEntityDescription,
        definition: HumidifierDefinition,
    ) -> None:
        """Init Tuya (de)humidifier."""
        super().__init__(device, device_manager, description)

        self._attr_translation_key = "dehumidifier"
        self._attr_mode: str | None = None
        self._attr_target_humidity: int | None = None
        self._current_humidity_wrapper = definition.current_humidity_wrapper
        self._mode_wrapper = definition.mode_wrapper
        self._switch_wrapper = definition.switch_wrapper
        self._target_humidity_wrapper = definition.target_humidity_wrapper

        # Determine humidity parameters
        if definition.target_humidity_wrapper:
            self._attr_min_humidity = round(
                definition.target_humidity_wrapper.min_value
            )
            self._attr_max_humidity = round(
                definition.target_humidity_wrapper.max_value
            )
        elif (
            "humidity_set" in self.device.status_range
            or "humidity_set" in self.device.function
            or "humidity_set" in self.device.status
        ):
            self._attr_min_humidity = 20
            self._attr_max_humidity = 100

        # Determine mode support and provided modes
        is_fresh_air = (
            device.category in (DeviceCategory.XFJ, DeviceCategory.KJ, DeviceCategory.CS)
            or any(dp in self.device.status for dp in ("loop_mode", "switch_ventilate"))
            or "fresh" in getattr(device, "product_name", "").lower()
            or "新风" in getattr(device, "name", "")
            or "新风" in getattr(device, "product_name", "")
        )
        if is_fresh_air or (definition.mode_wrapper and len(definition.mode_wrapper.options) <= 1):
            self._attr_supported_features |= HumidifierEntityFeature.MODES
            self._attr_available_modes = ["dehumidify", "purify", "ventilation", "auto"]
        elif definition.mode_wrapper:
            self._attr_supported_features |= HumidifierEntityFeature.MODES
            self._attr_available_modes = definition.mode_wrapper.options

    @property
    @override
    def is_on(self) -> bool | None:
        """Return the device is on or off."""
        val = self._read_wrapper(self._switch_wrapper)
        if val is None:
            if "switch" in self.device.status:
                return bool(self.device.status["switch"])
            if "switch_spray" in self.device.status:
                return bool(self.device.status["switch_spray"])
        return val

    @property
    @override
    def mode(self) -> str | None:
        """Return the current mode."""
        raw = self._read_wrapper(self._mode_wrapper)
        if raw is None:
            for dp in ("mode", "work_mode"):
                if dp in self.device.status:
                    raw = self.device.status[dp]
                    break
        if raw is None and hasattr(self, "_attr_mode"):
            return self._attr_mode
        return raw

    @property
    @override
    def target_humidity(self) -> int | None:
        """Return the humidity we try to reach."""
        if hasattr(self, "_attr_target_humidity") and self._attr_target_humidity is not None:
            return self._attr_target_humidity
        val = self._read_wrapper(self._target_humidity_wrapper)
        if val is None:
            val = self.device.status.get(DPCode.HUMIDITY_SET) or self.device.status.get("humidity_set")
        return val

    @property
    @override
    def current_humidity(self) -> int | None:
        """Return the current humidity."""
        val = self._read_wrapper(self._current_humidity_wrapper)
        if val is None or val >= 30000 or val in (32767, 3276.7):
            for alt_key in (DPCode.HUMIDITY_CURRENT, DPCode.HUMIDITY_VALUE, DPCode.HUMIDITY):
                alt_val = self.device.status.get(alt_key)
                if alt_val is not None and alt_val < 30000:
                    val = alt_val
                    break
            else:
                return None if val is not None and (val >= 30000 or val in (32767, 3276.7)) else val

        if val is not None and val > 100:
            val = int(round(val / 10.0))
        return val

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the device on."""
        if self._switch_wrapper is None:
            for code in (self.entity_description.dpcode or self.entity_description.key, "switch"):
                if isinstance(code, tuple):
                    code = code[0]
                if code in self.device.function or code in self.device.status:
                    await self._async_send_commands([{"code": code, "value": True}])
                    return
            raise ActionDPCodeNotFoundError(
                self.device,
                self.entity_description.dpcode or self.entity_description.key,
            )
        await self._async_send_wrapper_updates(self._switch_wrapper, True)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the device off."""
        if self._switch_wrapper is None:
            for code in (self.entity_description.dpcode or self.entity_description.key, "switch"):
                if isinstance(code, tuple):
                    code = code[0]
                if code in self.device.function or code in self.device.status:
                    await self._async_send_commands([{"code": code, "value": False}])
                    return
            raise ActionDPCodeNotFoundError(
                self.device,
                self.entity_description.dpcode or self.entity_description.key,
            )
        await self._async_send_wrapper_updates(self._switch_wrapper, False)

    @override
    async def async_set_humidity(self, humidity: int) -> None:
        """Set new target humidity."""
        self._attr_target_humidity = int(humidity)
        if self._target_humidity_wrapper is not None:
            try:
                await self._async_send_wrapper_updates(self._target_humidity_wrapper, humidity)
            except Exception:
                pass
        else:
            for code in (DPCode.DEHUMIDITY_SET_VALUE, DPCode.HUMIDITY_SET, "humidity_set"):
                if code in self.device.function or code in self.device.status:
                    try:
                        await self._async_send_commands([{"code": code, "value": int(humidity)}])
                    except Exception:
                        pass
                    break

        self.async_write_ha_state()

    @override
    async def async_set_mode(self, mode: str) -> None:
        """Set new target preset mode."""
        self._attr_mode = mode
        mode_dp = next(
            (
                dp
                for dp in ("mode", "work_mode")
                if dp in self.device.status
                or dp in self.device.function
                or dp in self.device.status_range
            ),
            "mode",
        )
        commands: list[dict[str, Any]] = [{"code": mode_dp, "value": mode}]
        if "loop_mode" in self.device.status or "loop_mode" in self.device.function:
            if mode == "auto":
                commands.append({"code": "loop_mode", "value": "auto"})
            elif mode == "purify":
                commands.append({"code": "loop_mode", "value": "indoor_loop"})
            elif mode == "ventilation":
                commands.append({"code": "loop_mode", "value": "outdoor_loop"})
        if "switch_ventilate" in self.device.status or "switch_ventilate" in self.device.function:
            if mode == "purify":
                commands.append({"code": "switch_ventilate", "value": False})
            elif mode == "ventilation":
                commands.append({"code": "switch_ventilate", "value": True})

        success = False
        if self._mode_wrapper is not None:
            try:
                await self._async_send_wrapper_updates(self._mode_wrapper, mode)
                success = True
            except Exception:
                success = False
        if not success:
            try:
                await self._async_send_commands(commands)
            except Exception:
                pass
        self.async_write_ha_state()
