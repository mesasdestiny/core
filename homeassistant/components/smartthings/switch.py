"""Support for switches through the SmartThings cloud API."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from pysmartthings import Attribute, Capability, Command, SmartThings

from homeassistant.components.switch import (
    DOMAIN as SWITCH_DOMAIN,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FullDevice, SmartThingsConfigEntry
from .const import INVALID_SWITCH_CATEGORIES, MAIN
from .entity import SmartThingsEntity
from .util import deprecate_entity

_LOGGER = logging.getLogger(__name__)

CAPABILITIES = (
    Capability.SWITCH_LEVEL,
    Capability.COLOR_CONTROL,
    Capability.COLOR_TEMPERATURE,
    Capability.FAN_SPEED,
)

AC_CAPABILITIES = (
    Capability.AIR_CONDITIONER_MODE,
    Capability.AIR_CONDITIONER_FAN_MODE,
    Capability.TEMPERATURE_MEASUREMENT,
    Capability.THERMOSTAT_COOLING_SETPOINT,
)

MEDIA_PLAYER_CAPABILITIES = (
    Capability.AUDIO_MUTE,
    Capability.AUDIO_VOLUME,
    Capability.MEDIA_PLAYBACK,
)


@dataclass(frozen=True, kw_only=True)
class SmartThingsSwitchEntityDescription(SwitchEntityDescription):
    """Describe a SmartThings switch entity."""

    status_attribute: Attribute
    component_translation_key: dict[str, str] | None = None


@dataclass(frozen=True, kw_only=True)
class SmartThingsCommandSwitchEntityDescription(SmartThingsSwitchEntityDescription):
    """Describe a SmartThings switch entity."""

    command: Command


SWITCH = SmartThingsSwitchEntityDescription(
    key=Capability.SWITCH,
    status_attribute=Attribute.SWITCH,
    name=None,
)
CAPABILITY_TO_COMMAND_SWITCHES: dict[
    Capability | str, SmartThingsCommandSwitchEntityDescription
] = {
    Capability.CUSTOM_DRYER_WRINKLE_PREVENT: SmartThingsCommandSwitchEntityDescription(
        key=Capability.CUSTOM_DRYER_WRINKLE_PREVENT,
        translation_key="wrinkle_prevent",
        status_attribute=Attribute.DRYER_WRINKLE_PREVENT,
        command=Command.SET_DRYER_WRINKLE_PREVENT,
    )
}
CAPABILITY_TO_SWITCHES: dict[Capability | str, SmartThingsSwitchEntityDescription] = {
    Capability.SAMSUNG_CE_WASHER_BUBBLE_SOAK: SmartThingsSwitchEntityDescription(
        key=Capability.SAMSUNG_CE_WASHER_BUBBLE_SOAK,
        translation_key="bubble_soak",
        status_attribute=Attribute.STATUS,
    ),
    Capability.SWITCH: SmartThingsSwitchEntityDescription(
        key=Capability.SWITCH,
        status_attribute=Attribute.SWITCH,
        component_translation_key={
            "icemaker": "ice_maker",
        },
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartThingsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add switches for a config entry."""
    entry_data = entry.runtime_data
    entities: list[SmartThingsEntity] = [
        SmartThingsCommandSwitch(
            entry_data.client,
            device,
            description,
            Capability(capability),
        )
        for device in entry_data.devices.values()
        for capability, description in CAPABILITY_TO_COMMAND_SWITCHES.items()
        if capability in device.status[MAIN]
    ]
    entities.extend(
        SmartThingsSwitch(
            entry_data.client,
            device,
            description,
            Capability(capability),
            component,
        )
        for device in entry_data.devices.values()
        for capability, description in CAPABILITY_TO_SWITCHES.items()
        for component in device.status
        if capability in device.status[component]
        and (
            (description.component_translation_key is None and component == MAIN)
            or (
                description.component_translation_key is not None
                and component in description.component_translation_key
            )
        )
    )
    entity_registry = er.async_get(hass)
    for device in entry_data.devices.values():
        if (
            Capability.SWITCH in device.status[MAIN]
            and not any(
                capability in device.status[MAIN] for capability in CAPABILITIES
            )
            and not all(
                capability in device.status[MAIN] for capability in AC_CAPABILITIES
            )
        ):
            media_player = all(
                capability in device.status[MAIN]
                for capability in MEDIA_PLAYER_CAPABILITIES
            )
            appliance = (
                device.device.components[MAIN].manufacturer_category
                in INVALID_SWITCH_CATEGORIES
            )
            if media_player or appliance:
                issue = "media_player" if media_player else "appliance"
                if deprecate_entity(
                    hass,
                    entity_registry,
                    SWITCH_DOMAIN,
                    f"{device.device.device_id}_{MAIN}_{Capability.SWITCH}_{Attribute.SWITCH}_{Attribute.SWITCH}",
                    f"deprecated_switch_{issue}",
                ):
                    entities.append(
                        SmartThingsSwitch(
                            entry_data.client,
                            device,
                            SWITCH,
                            Capability.SWITCH,
                        )
                    )
                continue
            entities.append(
                SmartThingsSwitch(
                    entry_data.client,
                    device,
                    SWITCH,
                    Capability.SWITCH,
                )
            )
    # Add custom AC Lighting and AC Beep switches
    for device in entry_data.devices.values():
        main_status = device.status.get(MAIN, {})
        if Capability.SAMSUNG_CE_AIR_CONDITIONER_LIGHTING in main_status:
            _LOGGER.debug(
                "Adding AC Lighting switch for device %s", device.device.label
            )
            entities.append(SmartThingsACLightsSwitch(entry_data.client, device, MAIN))
        if Capability.SAMSUNG_CE_AIR_CONDITIONER_BEEP in main_status:
            _LOGGER.debug("Adding AC Beep switch for device %s", device.device.label)
            entities.append(SmartThingsACBeepSwitch(entry_data.client, device, MAIN))
    async_add_entities(entities)


class SmartThingsSwitch(SmartThingsEntity, SwitchEntity):
    """Define a SmartThings switch."""

    entity_description: SmartThingsSwitchEntityDescription

    def __init__(
        self,
        client: SmartThings,
        device: FullDevice,
        entity_description: SmartThingsSwitchEntityDescription,
        capability: Capability,
        component: str = MAIN,
    ) -> None:
        """Initialize the switch."""
        super().__init__(client, device, {capability}, component=component)
        self.entity_description = entity_description
        self.switch_capability = capability
        self._attr_unique_id = f"{device.device.device_id}_{component}_{capability}_{entity_description.status_attribute}_{entity_description.status_attribute}"
        if (
            translation_keys := entity_description.component_translation_key
        ) is not None and (
            translation_key := translation_keys.get(component)
        ) is not None:
            self._attr_translation_key = translation_key

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self.execute_device_command(
            self.switch_capability,
            Command.OFF,
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self.execute_device_command(
            self.switch_capability,
            Command.ON,
        )

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return (
            self.get_attribute_value(
                self.switch_capability, self.entity_description.status_attribute
            )
            == "on"
        )


class SmartThingsCommandSwitch(SmartThingsSwitch):
    """Define a SmartThings command switch."""

    entity_description: SmartThingsCommandSwitchEntityDescription

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self.execute_device_command(
            self.switch_capability,
            self.entity_description.command,
            "off",
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self.execute_device_command(
            self.switch_capability,
            self.entity_description.command,
            "on",
        )


@dataclass
class SmartThingsSwitchBase(SmartThingsEntity, SwitchEntity):
    """Base class for SmartThings switches."""

    client: SmartThings
    device: FullDevice
    component: str
    capability: Capability
    attribute: Attribute
    unique_suffix: str

    def __post_init__(self) -> None:
        """Initialize the switch."""
        # Pass the capability to the SmartThingsEntity constructor
        super().__init__(
            self.client, self.device, {self.capability}, component=self.component
        )
        self._attr_unique_id = (
            f"{self.device.device.device_id}_{self.component}_{self.unique_suffix}"
        )
        self._attr_is_on: bool | None = None  # Initialize the state as unknown
        _LOGGER.debug(
            "Initializing %s switch for device %s", self.name, self.device.device.label
        )

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on."""
        return self.get_attribute_value(self.capability, self.attribute) == "on"

    async def async_update(self) -> None:
        """Fetch the latest state from the device."""
        value = self.get_attribute_value(self.capability, self.attribute)
        self._attr_is_on = value == "on"
        _LOGGER.debug(
            "Updated %s switch state for device %s: %s",
            self.name,
            self.device.device.label,
            self._attr_is_on,
        )


class SmartThingsACLightsSwitch(SmartThingsSwitchBase):
    """Representation of the AC Lighting control switch for Samsung WindFree AC."""

    def __init__(
        self, client: SmartThings, device: FullDevice, component: str = MAIN
    ) -> None:
        """Initialize the AC Lighting switch."""
        super().__init__(
            client=client,
            device=device,
            component=component,
            capability=Capability.SAMSUNG_CE_AIR_CONDITIONER_LIGHTING,
            attribute=Attribute.LIGHTING,
            unique_suffix="lighting",
        )

    @property
    def name(self) -> str:
        """Return the name of the AC Lighting switch."""
        return "Lighting"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Send command to 'turn on' AC lighting (which sends 'Light_Off')."""
        _LOGGER.debug("Turning ON AC Lighting for device %s", self.device.device.label)
        argument = ["mode/vs/0", {"x.com.samsung.da.options": ["Light_Off"]}]
        await self.execute_device_command(Capability.EXECUTE, Command.EXECUTE, argument)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Send command to 'turn off' AC lighting (which sends 'Light_On')."""
        _LOGGER.debug("Turning OFF AC Lighting for device %s", self.device.device.label)
        argument = ["mode/vs/0", {"x.com.samsung.da.options": ["Light_On"]}]
        await self.execute_device_command(Capability.EXECUTE, Command.EXECUTE, argument)
        self._attr_is_on = False
        self.async_write_ha_state()


class SmartThingsACBeepSwitch(SmartThingsSwitchBase):
    """Representation of the AC Beep control switch for Samsung WindFree AC."""

    def __init__(
        self, client: SmartThings, device: FullDevice, component: str = MAIN
    ) -> None:
        """Initialize the AC Beep switch."""
        super().__init__(
            client=client,
            device=device,
            component=component,
            capability=Capability.SAMSUNG_CE_AIR_CONDITIONER_BEEP,
            attribute=Attribute.BEEP,
            unique_suffix="beep",
        )

    @property
    def name(self) -> str:
        """Return the name of the AC Beep switch."""
        return "Beep"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Send command to enable beep (using 'Volume_100')."""
        _LOGGER.debug("Turning ON AC Beep for device %s", self.device.device.label)
        argument = ["mode/vs/0", {"x.com.samsung.da.options": ["Volume_100"]}]
        await self.execute_device_command(Capability.EXECUTE, Command.EXECUTE, argument)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Send command to disable beep (using 'Volume_Mute')."""
        _LOGGER.debug("Turning OFF AC Beep for device %s", self.device.device.label)
        argument = ["mode/vs/0", {"x.com.samsung.da.options": ["Volume_Mute"]}]
        await self.execute_device_command(Capability.EXECUTE, Command.EXECUTE, argument)
        self._attr_is_on = False
        self.async_write_ha_state()
