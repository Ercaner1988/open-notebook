"""Migration 26 indexes the sources-list sort fields (see its header)."""

from open_notebook.database.async_migrate import AsyncMigrationManager


def test_migration_26_indexes_source_sort_fields():
    manager = AsyncMigrationManager()
    up = open("open_notebook/database/migrations/26.surrealql", encoding="utf-8").read()
    down = open("open_notebook/database/migrations/26_down.surrealql", encoding="utf-8").read()
    assert "idx_source_updated ON source FIELDS updated" in up
    assert "idx_source_created ON source FIELDS created" in up
    assert "REMOVE INDEX IF EXISTS idx_source_updated" in down
    assert len(manager.up_migrations) == len(manager.down_migrations) >= 26
