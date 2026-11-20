"""Single declarative base shared by every feature model."""

from sqlalchemy import MetaData
from sqlalchemy.orm import declarative_base

from apps.settings.config import get_settings

settings = get_settings()
metadata = MetaData(schema=settings.db_schema)
Base = declarative_base(metadata=metadata)
