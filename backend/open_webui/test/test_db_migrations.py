from sqlalchemy import create_engine, text

from open_webui.config import _read_alembic_version, _unknown_migration_revisions

LOCAL_HEAD = 'd4c1a8e37b62'
UPSTREAM_HEADS = ['0bd252b206fb', 'e42c8f710a36']


def test_known_local_revisions_are_supported():
    assert _unknown_migration_revisions([LOCAL_HEAD], {LOCAL_HEAD}) == []
    assert _unknown_migration_revisions([], {LOCAL_HEAD}) == []


def test_upstream_revisions_are_reported_and_sorted():
    known = {LOCAL_HEAD}
    assert _unknown_migration_revisions([UPSTREAM_HEADS[1], LOCAL_HEAD, UPSTREAM_HEADS[0]], known) == sorted(
        UPSTREAM_HEADS
    )


def test_fresh_database_has_no_revision(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path / "fresh.db"}')
    try:
        assert _read_alembic_version(engine) == []
    finally:
        engine.dispose()


def test_database_revision_is_read(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path / "webui.db"}')
    try:
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)'))
            connection.execute(
                text('INSERT INTO alembic_version (version_num) VALUES (:version)'),
                {'version': UPSTREAM_HEADS[0]},
            )

        assert _read_alembic_version(engine) == [UPSTREAM_HEADS[0]]
    finally:
        engine.dispose()
