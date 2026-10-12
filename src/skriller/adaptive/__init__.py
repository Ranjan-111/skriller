"""Tenant-scoped adapters for the copied Scrapling fingerprint storage contract."""

from .storage import PostgreSQLStorageSystem, StorageScope, storage_arguments

__all__ = ["PostgreSQLStorageSystem", "StorageScope", "storage_arguments"]
