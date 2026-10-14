"""Migration-owner CLI: maintain a separate non-owner application role.

No passwords are accepted or created here. Use a private migration DATABASE_URL.
"""

import argparse
import sys

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from src.config import settings


def grant_runtime_permissions(role: str) -> int:
    url = make_url(settings.database_url).set(drivername="postgresql")
    with psycopg.connect(url.render_as_string(hide_password=False)) as db:
        attributes = db.execute(
            "SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls "
            "FROM pg_roles WHERE rolname=%s",
            (role,),
        ).fetchone()
        if attributes is None or any(attributes):
            raise ValueError(
                "Runtime role must exist and have no administrative privileges"
            )
        owns_tables = db.execute(
            "SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "JOIN pg_roles r ON r.oid=c.relowner WHERE n.nspname='public' AND r.rolname=%s)",
            (role,),
        ).fetchone()[0]
        memberships = db.execute(
            "SELECT EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname=%s)",
            (role,),
        ).fetchone()[0]
        if owns_tables or memberships:
            raise ValueError("Runtime role must not own tables or inherit other roles")
        name = sql.Identifier(role)
        db.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(url.database), name
            )
        )
        db.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(name))
        db.execute(
            sql.SQL(
                "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {}"
            ).format(name)
        )
        db.execute(
            sql.SQL(
                "GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {}"
            ).format(name)
        )
        immutable = [
            row[0]
            for row in db.execute(
                "SELECT DISTINCT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE NOT t.tgisinternal "
                "AND n.nspname='public' AND t.tgname LIKE 'immutable_%'"
            )
        ]
        if not {"invoices", "invoice_lines"} <= set(immutable):
            raise ValueError("Invoice immutability migrations must be applied first")
        for table in immutable:
            db.execute(
                sql.SQL(
                    "REVOKE UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER ON TABLE public.{} FROM {}"
                ).format(sql.Identifier(table), name)
            )
        db.execute(
            sql.SQL("REVOKE ALL ON TABLE public.alembic_version FROM {}").format(name)
        )
        for table in ("invoices", "invoice_lines"):
            flags = db.execute(
                "SELECT has_table_privilege(%s,%s,'SELECT'),has_table_privilege(%s,%s,'INSERT'),"
                "has_table_privilege(%s,%s,'UPDATE'),has_table_privilege(%s,%s,'DELETE'),has_table_privilege(%s,%s,'TRUNCATE')",
                (role, table) * 5,
            ).fetchone()
            if flags != (True, True, False, False, False):
                raise ValueError(
                    "Effective invoice permissions remain broader than intended"
                )
        return len(immutable)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True)
    args = parser.parse_args()
    try:
        count = grant_runtime_permissions(args.role)
    except (ValueError, psycopg.Error, ArgumentError) as error:
        # Do not emit database URLs, raw SQL or credential-bearing exceptions.
        print(
            f"Runtime permission setup failed: {type(error).__name__}", file=sys.stderr
        )
        raise SystemExit(1) from None
    print(f"Runtime permissions verified; {count} immutable tables restricted")
