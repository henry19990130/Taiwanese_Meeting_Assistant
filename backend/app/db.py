from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from app import config


def bind_user(conn, user_id) -> None:
    conn.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))
    conn.execute("SELECT set_config('app.system', '', true)")


def _bind_system(conn) -> None:
    conn.execute("SELECT set_config('app.system', 'on', true)")
    conn.execute("SELECT set_config('app.user_id', '', true)")


@contextmanager
def get_conn(user_id=None, *, system: bool = False) -> Iterator[psycopg.Connection]:
    """user_id 只看該使用者的會議。system 只給啟動時收回中斷的會議。"""
    with psycopg.connect(config.DATABASE_URL, row_factory=dict_row) as conn:
        if system:
            _bind_system(conn)
        elif user_id is not None:
            bind_user(conn, user_id)
        yield conn
