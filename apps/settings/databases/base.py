"""Model registry for future Alembic metadata discovery."""

from apps.settings.databases.base_class import Base

# Import each feature's model module here when it is added, so all tables are registered.
target_metadata = Base.metadata

__all__ = ["Base", "target_metadata"]
