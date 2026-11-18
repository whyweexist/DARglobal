"""SQLite setup. sqlite-vec is loaded per DBAPI connection where installed."""
import logging
from functools import lru_cache
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from app.core.config import settings

log = logging.getLogger(__name__)
_vector_loaded = False


def load_vector_extension(dbapi_conn) -> bool:
    global _vector_loaded
    try:
        import sqlite_vec
        dbapi_conn.enable_load_extension(True)
        try:
            sqlite_vec.load(dbapi_conn)
            _vector_loaded = True
        finally:
            dbapi_conn.enable_load_extension(False)
        return True
    except (ImportError, AttributeError, OSError, RuntimeError) as exc:
        log.warning("sqlite-vec unavailable; lexical search remains active: %s", exc)
        return False


@lru_cache
def engine() -> Engine:
    url = settings().database_url
    if url.startswith("sqlite:////"):
        Path("/" + url.removeprefix("sqlite:////")).parent.mkdir(parents=True, exist_ok=True)
    eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 15}, pool_pre_ping=True)

    @event.listens_for(eng, "connect")
    def on_connect(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")
        dbapi_conn.execute("PRAGMA busy_timeout=15000")
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        load_vector_extension(dbapi_conn)

    return eng


def session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=engine(), expire_on_commit=False)


def vector_loaded() -> bool:
    return _vector_loaded
