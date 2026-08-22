"""Storage manager package: the abstraction over iPad app Documents storage."""

from ipad_sync.storage.base import SimulationStorageManager, StorageManager

__all__ = ["SimulationStorageManager", "StorageManager"]
