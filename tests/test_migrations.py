from alembic.config import Config
from alembic.script import ScriptDirectory


def _script() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config("alembic.ini"))


def test_migrations_have_a_single_head() -> None:
    """Two branches adding migrations on the same parent would leave two heads and break deploys."""
    assert len(_script().get_heads()) == 1


def test_migration_history_starts_at_baseline() -> None:
    revisions = list(_script().walk_revisions())

    assert revisions[-1].revision == "0000"
    assert revisions[-1].down_revision is None
