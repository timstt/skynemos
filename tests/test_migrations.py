"""Міграції мають збігатися з моделями й коректно відкочуватися."""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from bot.db.models import Base

ROOT = Path(__file__).resolve().parent.parent


def _alembic_config(db_path: Path) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.attributes["database_url"] = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    cfg.attributes["configure_logger"] = False
    return cfg


def test_upgrade_matches_models_and_downgrades(tmp_path: Path) -> None:
    db_path = tmp_path / "migrations.db"
    cfg = _alembic_config(db_path)

    command.upgrade(cfg, "head")

    sync_engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    with sync_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        assert diff == [], f"Міграції розходяться з моделями: {diff}"

    command.downgrade(cfg, "base")
    with sync_engine.connect() as conn:
        assert set(inspect(conn).get_table_names()) == {"alembic_version"}
    sync_engine.dispose()
