"""LangGraph Postgres checkpointer (never SQLite).

`setup_checkpointer` creates LangGraph's own checkpoint tables; it is idempotent and is run
by the backend at startup / migration time. `get_checkpointer` returns a saver backed by a
small connection pool that lives for the process.
"""

from __future__ import annotations

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pools: dict[str, ConnectionPool] = {}

# Structured responses can land in checkpoints; allow exactly our own schema types.
_SERDE = JsonPlusSerializer(
    allowed_msgpack_modules=[
        ("app.ai.schemas", name) for name in ("RepricingDecision", "IntakeResolution", "IntakeCandidate")
    ]
)


def to_libpq_url(database_url: str) -> str:
    """SQLAlchemy URLs carry a driver suffix (postgresql+psycopg://) that libpq rejects."""
    scheme, sep, rest = database_url.partition("://")
    return f"{scheme.split('+', 1)[0]}{sep}{rest}"


def setup_checkpointer(database_url: str) -> None:
    with PostgresSaver.from_conn_string(to_libpq_url(database_url)) as saver:
        saver.setup()


def get_checkpointer(database_url: str) -> PostgresSaver:
    url = to_libpq_url(database_url)
    pool = _pools.get(url)
    if pool is None:
        pool = ConnectionPool(
            conninfo=url,
            min_size=1,
            max_size=4,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            open=True,
        )
        _pools[url] = pool
    return PostgresSaver(pool, serde=_SERDE)


def close_checkpointers() -> None:
    for pool in _pools.values():
        pool.close()
    _pools.clear()
