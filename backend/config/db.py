#Initializes AWS RDS Credentials
#Updated 3/3/2026 by Ryan Grimes
#Merged into the single shared connection helper 11/11/26 by Obi Achebe

import os
import psycopg2
from psycopg2 import pool
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '../../.env'))

_pool = None


def _conn_kwargs():
    kwargs = {
        "host": os.getenv("DB_HOST"),
        "dbname": os.getenv("DB_NAME"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "port": int(os.getenv("DB_PORT", 5432)),
    }
    sslmode = os.getenv("DB_SSLMODE")
    if sslmode:
        kwargs["sslmode"] = sslmode
    sslrootcert = os.getenv("DB_SSLROOTCERT")
    if sslrootcert:
        kwargs["sslrootcert"] = sslrootcert
    return kwargs


def _get_pool():
    global _pool
    if _pool is None:
        _pool = pool.ThreadedConnectionPool(1, 10, **_conn_kwargs())
    return _pool


class PooledConnection:
    """
    Wraps a pooled connection so that existing code calling conn.close()
    hands the connection back to the pool instead of throwing it away.
    Every call site in the project already does get_connection() ...
    conn.close(), so this keeps all ~80 of them working unchanged.
    """

    def __init__(self, conn, src_pool):
        self._conn = conn
        self._pool = src_pool
        self._closed = False

    def close(self):
        if not self._closed:
            self._pool.putconn(self._conn)
            self._closed = True

    def __getattr__(self, name):
        return getattr(self._conn, name)


def get_connection():
    """
    Returns a PostgreSQL connection from the shared pool.

    Raises on failure instead of returning None, so a database problem
    surfaces as a clear error at the call site rather than an
    AttributeError on None several lines later.
    """
    p = _get_pool()
    return PooledConnection(p.getconn(), p)
