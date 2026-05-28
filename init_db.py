"""Initialize database schema for local SEC-backed cache."""

from __future__ import annotations

from db import engine
from logging_setup import configure_logging
from models import Base


def main() -> None:
    configure_logging()
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    main()
