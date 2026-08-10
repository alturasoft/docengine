"""DocEngine — Infrastructure: Database Connection Pool.

Provides thread-safe connection pooling for PostgreSQL using psycopg2.
"""

from __future__ import annotations

import contextlib
from typing import Generator

import psycopg2
from psycopg2.pool import ThreadedConnectionPool

from app.config.settings import DatabaseConfig
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class DatabaseManager:
    """Manages PostgreSQL connection pool lifecycle."""

    def __init__(self, config: DatabaseConfig) -> None:
        self._config = config
        self._pool: ThreadedConnectionPool | None = None

    def initialize(self) -> None:
        """Initialize the connection pool."""
        if self._pool is None or self._pool.closed:
            try:
                self._pool = ThreadedConnectionPool(
                    minconn=self._config.pool_min,
                    maxconn=self._config.pool_max,
                    host=self._config.host,
                    port=self._config.port,
                    dbname=self._config.name,
                    user=self._config.user,
                    password=self._config.password,
                )
                logger.info(
                    "PostgreSQL connection pool initialized",
                    host=self._config.host,
                    port=self._config.port,
                    dbname=self._config.name,
                )
            except Exception as e:
                logger.error("Failed to initialize database pool", error=str(e))
                raise

    def close(self) -> None:
        """Close all connections in the pool."""
        if self._pool and not self._pool.closed:
            self._pool.closeall()
            logger.info("PostgreSQL connection pool closed")

    @contextlib.contextmanager
    def get_connection(self) -> Generator[psycopg2.extensions.connection, None, None]:
        """Context manager for acquiring and releasing a connection from the pool.

        Yields:
            psycopg2 connection object.
        """
        if self._pool is None or self._pool.closed:
            self.initialize()

        assert self._pool is not None, "Database pool failed to initialize"
        conn = self._pool.getconn()
        try:
            yield conn
        finally:
            self._pool.putconn(conn)

