from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from app import config


@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    with psycopg.connect(config.DATABASE_URL, row_factory=dict_row) as conn:
        yield conn
