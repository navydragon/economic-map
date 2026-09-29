from functools import lru_cache

from sqlalchemy import Engine, create_engine, text

from .config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def check_database() -> str:
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
        return str(connection.scalar(text("SELECT PostGIS_Version()")))
