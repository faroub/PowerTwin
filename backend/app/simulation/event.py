"""Simulation Event Definition and In-Memory Dispatcher."""

import uuid
from collections.abc import Callable
from typing import Any
from pydantic import BaseModel, Field


class SimulationEvent(BaseModel):
    """Event representation dispatched during simulation ticks."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(description="Name/topic of the event, e.g. 'ALARM_RAISED'")
    timestamp_ns: int = Field(description="Simulation tick timestamp in nanoseconds")
    source: str = Field(description="Source component ID emitting the event")
    payload: dict[str, Any] = Field(default_factory=dict, description="Event payload data")


EventHandler = Callable[[SimulationEvent], None]


class EventDispatcher:
    """In-memory event bus for simulation event publication and subscription."""

    def __init__(self) -> None:
        self._listeners: dict[str, list[EventHandler]] = {}
        self._global_listeners: list[EventHandler] = []
        self._published_history: list[SimulationEvent] = []

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        """Subscribe handler to a specific event topic."""
        if event_name not in self._listeners:
            self._listeners[event_name] = []
        if handler not in self._listeners[event_name]:
            self._listeners[event_name].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe handler to all events globally."""
        if handler not in self._global_listeners:
            self._global_listeners.append(handler)

    def unsubscribe(self, event_name: str, handler: EventHandler) -> None:
        """Unsubscribe handler from an event topic."""
        if event_name in self._listeners and handler in self._listeners[event_name]:
            self._listeners[event_name].remove(handler)

    def publish(self, event: SimulationEvent) -> None:
        """Publish event to all subscribed topic handlers and global listeners."""
        self._published_history.append(event)

        # Notify topic-specific subscribers
        if event.name in self._listeners:
            for handler in self._listeners[event.name]:
                handler(event)

        # Notify global subscribers
        for handler in self._global_listeners:
            handler(event)

    def get_history(() -> list[SimulationEvent]: ...
    def clear(self) -> None:
        """Clear listeners and event history."""
        self._listeners.clear()
        self._global_listeners.clear()
        self._published_history.clear()

    @property
    def published_history(self) -> list[SimulationEvent]:
        """Return history of all published events."""
        return self._published_history
