"""
Shared database module for catalog imports.

This module provides centralized access to database objects for all catalog loaders.
"""

from typing import Optional

from PiFinder.db.objects_db import ObjectsDatabase

from .catalog_import_utils import init_objects_database

# Global database objects shared across all catalog loaders
objects_db: Optional[ObjectsDatabase] = None


def init_shared_database():
    """Share one catalog connection between the import stages."""
    global objects_db
    if objects_db is None:
        objects_db = init_objects_database()
    return objects_db
