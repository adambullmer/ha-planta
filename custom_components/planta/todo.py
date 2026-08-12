"""Planta todo entity."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
import json
import logging
from typing import Final

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import homeassistant.util.dt as dt_util

from . import PlantaConfigEntry
from .coordinator import PlantaCoordinator
from .entity import get_plant_name

_LOGGER = logging.getLogger(__name__)

ACTION_TYPE_MAP: Final[dict[str, str]] = {
    "cleaning": "✨🍃 (Clean)",
    "fertilizing": "🌱💩 (Fertilize)",
    "misting": "💦🌿 (Mist)",
    "progressUpdate": "📸🌸 (Progress update)",
    "repotting": "🪴🔄 (Repot)",
    "watering": "🪴💧 (Water)",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PlantaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Planta todo using config entry."""
    async_add_entities([PlantaTodoListEntity(entry.runtime_data, TODO)])


TODO = EntityDescription(key="todo", translation_key="tasks")


class PlantaTodoListEntity(CoordinatorEntity[PlantaCoordinator], TodoListEntity):
    """Planta todo list entity."""

    _attr_has_entity_name = True
    _attr_supported_features = TodoListEntityFeature.UPDATE_TODO_ITEM

    def __init__(
        self, coordinator: PlantaCoordinator, description: EntityDescription
    ) -> None:
        """Construct a Planta to-do list entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}-{description.key}"

    def _todo_items(self) -> Iterator[TodoItem]:
        today = dt_util.now().date()

        for plant_id, plant in self.coordinator.data.items():
            if not (actions := plant.get("actions")) or not isinstance(actions, dict):
                continue

            plant_name = get_plant_name(plant)
            site_name = plant.get("site", {}).get("name")

            for action_type, details in actions.items():
                if not isinstance(details, dict):
                    continue

                status = TodoItemStatus.NEEDS_ACTION
                completed: datetime | None = None
                if (
                    (completed_str := (details.get("completed") or {}).get("date"))
                    and (completed := dt_util.parse_datetime(completed_str))
                    and completed.astimezone(dt_util.DEFAULT_TIME_ZONE).date() == today
                ):
                    due = today
                    status = TodoItemStatus.COMPLETED
                elif (
                    not (next_action := details.get("next"))
                    or not (date_str := next_action.get("date"))
                    or not (due := dt_util.parse_date(date_str[:10]))
                    or due > today
                ):
                    continue

                action_name = ACTION_TYPE_MAP.get(action_type, action_type.title())

                yield TodoItem(
                    summary=f"{plant_name}: {action_name}",
                    uid=json.dumps((plant_id, action_type)),
                    status=status,
                    due=due,
                    description=site_name,
                    completed=completed,
                )

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Update a To-do item."""
        if not item.status == TodoItemStatus.COMPLETED:
            raise ServiceValidationError(
                "Currently, only marking a task as complete is supported"
            )
        plant_id, action_type = json.loads(item.uid)
        await self.coordinator.client.plant_action_complete(plant_id, action_type)
        await self.coordinator.async_refresh_plant(plant_id)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        items = list(self._todo_items())
        items = sorted(items, key=lambda t: (t.due, t.description, t.summary))
        self._attr_todo_items = items
        super()._handle_coordinator_update()

    async def async_added_to_hass(self) -> None:
        self._handle_coordinator_update()
        await super().async_added_to_hass()
