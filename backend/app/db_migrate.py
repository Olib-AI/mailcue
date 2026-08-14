"""Operator-facing database migration commands.

Schema upgrades remain Alembic's responsibility.  This module performs the
separate, one-time data transfer from a stopped SQLite/SQLCipher deployment to
an empty PostgreSQL database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy import MetaData, create_engine, inspect, select, text
from sqlalchemy.engine import URL, Connection, Engine, make_url

from alembic import command

EXPECTED_REVISION = "028_deliverability_alerts"


class MigrationError(RuntimeError):
    """A safe, operator-actionable migration failure."""


def _postgres_url_from_environment() -> str:
    configured = os.environ.get("MAILCUE_DATABASE_URL", "")
    if configured:
        url = make_url(configured)
        if url.drivername in {"postgres", "postgresql"}:
            url = url.set(drivername="postgresql+psycopg")
        return url.render_as_string(hide_password=False)

    host = os.environ.get("MAILCUE_DATABASE_HOST", "")
    if not host:
        raise MigrationError("Set --target-url or MAILCUE_DATABASE_HOST/USER/PASSWORD/NAME")
    return URL.create(
        "postgresql+psycopg",
        username=os.environ.get("MAILCUE_DATABASE_USER") or None,
        password=os.environ.get("MAILCUE_DATABASE_PASSWORD") or None,
        host=host,
        port=int(os.environ.get("MAILCUE_DATABASE_PORT", "5432")),
        database=os.environ.get("MAILCUE_DATABASE_NAME", "mailcue"),
        query={"sslmode": os.environ.get("MAILCUE_DATABASE_SSLMODE", "prefer")},
    ).render_as_string(hide_password=False)


def _normalize_target_url(value: str) -> str:
    url = make_url(value)
    if url.get_backend_name() != "postgresql":
        raise MigrationError("The migration target must be PostgreSQL")
    if url.drivername in {"postgres", "postgresql"} or url.drivername == "postgresql+asyncpg":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


def _sqlite_engine(source: Path, key: str) -> Engine:
    engine = create_engine(f"sqlite:///{source}")
    if key:

        @sa.event.listens_for(engine, "connect")
        def _apply_sqlcipher_key(dbapi_connection: Any, _record: Any) -> None:
            escaped = key.replace("'", "''")
            cursor = dbapi_connection.cursor()
            cursor.execute(f"PRAGMA key='{escaped}'")
            cursor.close()

    return engine


def _revision(connection: Connection) -> str | None:
    if "alembic_version" not in inspect(connection).get_table_names():
        return None
    return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()


def _alembic_project_root() -> Path:
    roots = (Path.cwd(), Path(__file__).resolve().parent.parent)
    project_root = next((root for root in roots if (root / "alembic.ini").is_file()), None)
    if project_root is None:
        checked = ", ".join(str(root / "alembic.ini") for root in roots)
        raise MigrationError(f"Alembic configuration not found; checked: {checked}")
    return project_root


def _run_target_schema_upgrade(target_url: str) -> None:
    os.environ["MAILCUE_DATABASE_URL"] = target_url
    project_root = _alembic_project_root()
    config_path = project_root / "alembic.ini"
    config = Config(str(config_path))
    config.set_main_option("script_location", str(project_root / "alembic"))
    command.upgrade(config, "head")


def _checkpoint_and_backup(source_engine: Engine, source: Path, backup: Path) -> None:
    with source_engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.exec_driver_sql("SELECT count(*) FROM sqlite_master").scalar_one()
    if backup.exists():
        raise MigrationError(f"Backup path already exists: {backup}")
    shutil.copy2(source, backup)


def _ensure_empty_target(connection: Connection, table_names: list[str]) -> None:
    for table_name in table_names:
        count = connection.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar_one()
        if count:
            raise MigrationError(
                f"Target table {table_name} is not empty ({count} rows); refusing to overwrite"
            )


def _pk_digest(connection: Connection, table: sa.Table) -> tuple[int, str]:
    primary_keys = list(table.primary_key.columns)
    if not primary_keys:
        count = connection.execute(select(sa.func.count()).select_from(table)).scalar_one()
        return count, "no-primary-key"
    digest = hashlib.sha256()
    count = 0
    statement = select(*primary_keys).order_by(*primary_keys)
    for row in connection.execute(statement):
        digest.update(json.dumps(list(row), default=str, separators=(",", ":")).encode())
        digest.update(b"\n")
        count += 1
    return count, digest.hexdigest()


def _reset_postgres_sequences(connection: Connection, metadata: MetaData) -> None:
    preparer = connection.dialect.identifier_preparer
    for table in metadata.sorted_tables:
        for column in table.primary_key.columns:
            if not isinstance(column.type, sa.Integer):
                continue
            sequence = connection.execute(
                text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
                {"table_name": table.name, "column_name": column.name},
            ).scalar_one_or_none()
            if sequence is None:
                continue
            table_name = preparer.quote(table.name)
            column_name = preparer.quote(column.name)
            connection.execute(
                text(
                    f"SELECT setval(:sequence, "
                    f"COALESCE((SELECT MAX({column_name}) FROM {table_name}), 1), "
                    f"EXISTS(SELECT 1 FROM {table_name}))"
                ),
                {"sequence": sequence},
            )


def migrate_sqlite_to_postgres(args: argparse.Namespace) -> int:
    if not args.confirm_stopped:
        raise MigrationError("Stop MailCue first, then pass --yes-i-have-stopped-mailcue")
    source = Path(args.source).expanduser().resolve()
    if not source.is_file():
        raise MigrationError(f"SQLite source does not exist: {source}")

    target_url = _normalize_target_url(args.target_url or _postgres_url_from_environment())
    source_engine = _sqlite_engine(source, args.sqlite_key or "")
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = Path(args.backup or f"{source}.pre-postgres-{timestamp}.bak").resolve()

    try:
        with source_engine.connect() as source_connection:
            source_revision = _revision(source_connection)
            if source_revision != EXPECTED_REVISION:
                raise MigrationError(
                    f"SQLite is at revision {source_revision!r}; run Alembic upgrade to "
                    f"{EXPECTED_REVISION} before transferring data"
                )
        _checkpoint_and_backup(source_engine, source, backup)
        _run_target_schema_upgrade(target_url)

        target_engine = create_engine(target_url, pool_pre_ping=True)
        report: dict[str, dict[str, object]] = {}
        try:
            source_metadata = MetaData()
            source_metadata.reflect(bind=source_engine)
            target_metadata = MetaData()
            target_metadata.reflect(bind=target_engine)
            table_names = [
                table.name
                for table in target_metadata.sorted_tables
                if table.name != "alembic_version"
            ]
            missing = sorted(set(table_names) - set(source_metadata.tables))
            if missing:
                raise MigrationError(f"Source schema is missing tables: {', '.join(missing)}")

            with source_engine.connect() as source_connection, target_engine.begin() as target:
                _ensure_empty_target(target, table_names)
                for target_table in target_metadata.sorted_tables:
                    if target_table.name == "alembic_version":
                        continue
                    source_table = source_metadata.tables[target_table.name]
                    inserted = 0
                    result = source_connection.execute(select(source_table))
                    while rows := result.mappings().fetchmany(args.batch_size):
                        target.execute(target_table.insert(), [dict(row) for row in rows])
                        inserted += len(rows)
                    source_count, source_digest = _pk_digest(source_connection, source_table)
                    target_count, target_digest = _pk_digest(target, target_table)
                    if source_count != target_count or source_digest != target_digest:
                        raise MigrationError(
                            f"Validation failed for {target_table.name}: "
                            f"source={source_count}/{source_digest}, "
                            f"target={target_count}/{target_digest}"
                        )
                    report[target_table.name] = {
                        "rows": inserted,
                        "primary_key_sha256": source_digest,
                    }
                _reset_postgres_sequences(target, target_metadata)
                if _revision(target) != EXPECTED_REVISION:
                    raise MigrationError("Target Alembic revision changed during migration")
        finally:
            target_engine.dispose()
    finally:
        source_engine.dispose()

    print(
        json.dumps(
            {
                "status": "ok",
                "source": str(source),
                "backup": str(backup),
                "revision": EXPECTED_REVISION,
                "tables": report,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mailcue-db")
    subparsers = parser.add_subparsers(dest="command", required=True)
    migrate = subparsers.add_parser(
        "sqlite-to-postgres", help="copy a stopped SQLite/SQLCipher database to PostgreSQL"
    )
    migrate.add_argument("--source", required=True, help="path to the SQLite database")
    migrate.add_argument(
        "--target-url", help="PostgreSQL SQLAlchemy URL; env settings are fallback"
    )
    migrate.add_argument(
        "--sqlite-key",
        default=os.environ.get("MAILCUE_DATABASE_ENCRYPTION_KEY", ""),
        help="SQLCipher key (defaults to MAILCUE_DATABASE_ENCRYPTION_KEY)",
    )
    migrate.add_argument("--backup", help="explicit backup destination")
    migrate.add_argument("--batch-size", type=int, default=5_000)
    migrate.add_argument(
        "--yes-i-have-stopped-mailcue", dest="confirm_stopped", action="store_true"
    )
    migrate.set_defaults(handler=migrate_sqlite_to_postgres)
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    try:
        raise SystemExit(args.handler(args))
    except MigrationError as exc:
        print(f"mailcue-db: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
