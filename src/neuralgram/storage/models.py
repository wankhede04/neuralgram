"""Declarative base for all Neuralgram tables. Concrete models land in M1-1."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared metadata root; Alembic autogenerate diffs against this."""
