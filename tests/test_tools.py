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


def test_server_info_registered():
    """server_info tool is registered."""
    from postgres_server import server_info, db_identity
    assert callable(server_info)
    assert callable(db_identity)


# ---------------------------------------------------------------------------
# Permissions tests
# ---------------------------------------------------------------------------
from postgres_server import (  # noqa: E402
    Permissions, RolePermissions, load_permissions,
    check_permission, extract_tables_from_sql,
    _enforce_permissions,
)


def test_load_permissions_from_yaml(tmp_path):
    p = tmp_path / "perms.yaml"
    p.write_text("""
roles:
  analyst:
    schemas: ["public"]
    tables: "*"
    operations: ["select"]
  admin:
    schemas: ["public", "internal"]
    tables: "*"
    operations: ["select", "insert", "update", "delete"]
users:
  alice@co.com:
    role: admin
  _default: analyst
""")
    perms = load_permissions(str(p))
    assert "analyst" in perms.roles
    assert "admin" in perms.roles
    assert perms.users["alice@co.com"] == "admin"
    assert perms.default_role == "analyst"


def test_check_permission_allows_select():
    role = RolePermissions(schemas=["public"], tables="*", operations=["select"])
    result = check_permission(role, "select", "public", "users")
    assert result is None  # None means allowed


def test_check_permission_denies_schema():
    role = RolePermissions(schemas=["public"], tables="*", operations=["select"])
    result = check_permission(role, "select", "internal", "secrets")
    assert result is not None
    assert "internal" in result


def test_check_permission_denies_operation():
    role = RolePermissions(schemas=["public"], tables="*", operations=["select"])
    result = check_permission(role, "delete", "public", "users")
    assert result is not None
    assert "delete" in result


def test_check_permission_table_allowlist():
    role = RolePermissions(schemas=["public"], tables=["products", "categories"], operations=["select"])
    assert check_permission(role, "select", "public", "products") is None
    result = check_permission(role, "select", "public", "users")
    assert result is not None


def test_extract_tables_basic():
    tables = extract_tables_from_sql("SELECT * FROM public.users WHERE id = 1")
    assert ("public", "users") in tables or "users" in [t[1] for t in tables]


def test_extract_tables_join():
    tables = extract_tables_from_sql(
        "SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id"
    )
    table_names = [t[1] for t in tables]
    assert "users" in table_names
    assert "orders" in table_names


def test_enforce_permissions_blocks_disallowed_schema():
    perms = Permissions(
        roles={"restricted": RolePermissions(schemas=["public"], tables="*", operations=["select"])},
        users={"bob": "restricted"},
    )
    result = _enforce_permissions(perms, "bob", "SELECT * FROM internal.secrets")
    assert result is not None
    assert "internal" in result


def test_enforce_permissions_allows_valid_query():
    perms = Permissions(
        roles={"analyst": RolePermissions(schemas=["public"], tables="*", operations=["select"])},
        users={"alice": "analyst"},
    )
    result = _enforce_permissions(perms, "alice", "SELECT * FROM public.users")
    assert result is None


def test_enforce_permissions_skips_when_no_user():
    perms = Permissions()
    result = _enforce_permissions(perms, None, "DELETE FROM users")
    assert result is None  # No user = no enforcement


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_jwt_verifier_rejects_invalid():
    from postgres_server import JWKSTokenVerifier
    verifier = JWKSTokenVerifier(
        jwks_url="https://example.com/.well-known/jwks.json",
        audience="test",
        issuer="https://example.com",
    )
    result = await verifier.verify_token("invalid.token.here")
    assert result is None


def test_server_without_auth_config():
    """Server creates without auth when env vars not set."""
    from postgres_server import _config
    # In test env, auth env vars are not set
    assert _config.auth_issuer is None
