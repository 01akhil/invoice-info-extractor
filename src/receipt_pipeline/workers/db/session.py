from __future__ import annotations

import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from config.settings import PROJECT_ROOT

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "invoices.db"


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")


def _create_engine():
    url = _database_url()
    connect_args: dict = {}
    if url.startswith("sqlite"):
        # Multi-process workers: allow connections from any thread + wait on lock (seconds).
        connect_args["check_same_thread"] = False
        connect_args["timeout"] = 60.0

    eng = create_engine(
        url,
        echo=False,
        connect_args=connect_args,
        pool_pre_ping=True,
    )

    if url.startswith("sqlite"):

        @event.listens_for(eng, "connect")
        def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
            cur = dbapi_connection.cursor()
            try:
                # Concurrent readers + serialized writers; reduces "database is locked" vs default rollback journal.
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA synchronous=NORMAL")
                cur.execute("PRAGMA busy_timeout=60000")
            finally:
                cur.close()

    return eng


engine = _create_engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)


def get_engine():
    """Return the shared SQLAlchemy engine (tests and diagnostics)."""
    return engine


def init_db() -> None:
    # Importing Base loads models.py and registers all tables on Base.metadata.
    from receipt_pipeline.workers.db.models import Base

    DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
