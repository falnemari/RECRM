import asyncpg
from typing import AsyncGenerator, Optional
import logging
from app.config import settings

logger = logging.getLogger("recrm.database")

pool: Optional[asyncpg.Pool] = None

async def init_db_pool() -> asyncpg.Pool:
    global pool
    try:
        pool = await asyncpg.create_pool(
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            database=settings.DB_NAME,
            min_size=2,
            max_size=20,
            command_timeout=60,
        )
        logger.info("PostgreSQL asyncpg connection pool initialized successfully.")
        return pool
    except Exception as e:
        logger.error(f"Failed to initialize PostgreSQL pool: {e}")
        raise

async def close_db_pool() -> None:
    global pool
    if pool:
        await pool.close()
        logger.info("PostgreSQL asyncpg connection pool closed.")

async def get_db() -> AsyncGenerator[asyncpg.Connection, None]:
    """Dependency that yields a database connection from the pool."""
    if pool is None:
        raise RuntimeError("Database connection pool is not initialized")
    async with pool.acquire() as conn:
        yield conn

