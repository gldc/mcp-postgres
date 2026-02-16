import pytest


def test_server_module_imports():
    """Server module imports without a DSN configured."""
    import postgres_server
    assert postgres_server.mcp is not None
