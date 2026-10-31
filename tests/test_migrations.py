"""Міграції мають збігатися з моделями й коректно відкочуватися."""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

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


def test_upgrade_existing_data_keeps_behaviour(tmp_path: Path) -> None:
    """База зі справжніми даними на 0003 оновлюється до head без втрат і з безпечними дефолтами."""
    db_path = tmp_path / "live.db"
    cfg = _alembic_config(db_path)
    command.upgrade(cfg, "0003")

    sync_engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    with sync_engine.begin() as conn:
        conn.execute(text("INSERT INTO users (telegram_id, first_name) VALUES (1, 'A'), (2, 'B')"))
        conn.execute(
            text(
                "INSERT INTO pools (owner_id, title, total_amount_kop, billing_day, "
                "payment_details, invite_token, active_since) "
                "VALUES (1, 'Netflix', 30000, 5, '4441', 'tok', CURRENT_TIMESTAMP)"
            )
        )
        conn.execute(text("INSERT INTO members (pool_id, user_id, share_kop) VALUES (1, 2, 15000)"))
        conn.execute(
            text(
                "INSERT INTO payments (member_id, period, amount_kop, notified_at) "
                "VALUES (1, '2026-10-01', 15000, CURRENT_TIMESTAMP)"
            )
        )

    command.upgrade(cfg, "head")

    with sync_engine.connect() as conn:
        member = conn.execute(text("SELECT share_kop, weight, is_admin FROM members")).one()
        assert tuple(member) == (15000, 1, 0)
        pool = conn.execute(text("SELECT owner_weight, digest_period FROM pools")).one()
        assert tuple(pool) == (1, None)
        payment = conn.execute(text("SELECT status, snoozed_until FROM payments")).one()
        assert tuple(payment) == ("pending", None)
    sync_engine.dispose()
