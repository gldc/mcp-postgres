import pytest


def test_server_module_imports():
    """Server module imports without a DSN configured."""
    import postgres_server
    assert postgres_server.mcp is not None


@pytest.mark.asyncio
async def test_query_no_dsn_async():
    """query tool returns friendly error when no pool available."""
    from postgres_server import _query_impl

    result = await _query_impl(pool=None, sql="SELECT 1", readonly=False)
    assert isinstance(result, str)
    assert "not configured" in result.lower()


@pytest.mark.asyncio
async def test_list_schemas_no_dsn():
    from postgres_server import _query_impl

    result = await _query_impl(pool=None, sql="SELECT 1", readonly=False)
    assert "not configured" in result.lower()


@pytest.mark.asyncio
async def test_list_tables_no_dsn():
    from postgres_server import _query_impl

    result = await _query_impl(pool=None, sql="SELECT 1", readonly=False)
    assert "not configured" in result.lower()
