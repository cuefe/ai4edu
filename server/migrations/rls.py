"""迁移里复用的行级安全与授权语句。新增带 tenant_id 的表时，在迁移里调用 enable_tenant_rls。"""

from alembic import op

from app.core.config import get_settings

_POLICY = (
    "current_setting('app.bypass_rls', true) = 'on' "
    "OR tenant_id::text = current_setting('app.tenant_id', true)"
)


def enable_tenant_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({_POLICY}) WITH CHECK ({_POLICY})")


def disable_tenant_rls(table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def grant_app_role() -> None:
    """给应用账号授予增删改查权限。账号不存在时跳过（由部署脚本或 cli dev-db 创建）。"""
    role = get_settings().app_db_role
    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
            GRANT USAGE ON SCHEMA public TO {role};
            GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role};
            GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role};
          END IF;
        END $$;
        """
    )
