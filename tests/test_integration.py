"""Integration tests — require a real PostgreSQL database.

Run: DATABASE_URL=postgresql://... pytest tests/test_integration.py -v
"""

import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL not set",
)


@pytest.mark.asyncio
async def test_query_select_one():
    """Basic SELECT 1 against a real database."""
    os.environ["DATABASE_URL"] = os.getenv("DATABASE_URL", "")
    from postgres_server import _query_impl
    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(conninfo=os.environ["DATABASE_URL"], min_size=1, max_size=2, open=False)
    await pool.open()
    try:
        result = await _query_impl(pool=pool, sql="SELECT 1 AS n", readonly=False)
        assert "1" in str(result)
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_list_schemas_returns_public():
    """list_schemas includes 'public' schema."""
    # This would require setting up a full server context — stub for now
    pass
