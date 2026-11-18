"""Core tables and retrieval indexes.

Revision ID: 0001
Revises:
"""
from alembic import op
from app.db.models import Base
revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    Base.metadata.create_all(bind)
    bind.exec_driver_sql("""CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
        text, heading, content='chunks', content_rowid='id', tokenize='unicode61 remove_diacritics 2')""")
    bind.exec_driver_sql("""CREATE TRIGGER IF NOT EXISTS chunk_fts_ins AFTER INSERT ON chunks BEGIN
        INSERT INTO chunks_fts(rowid,text,heading) VALUES (new.id,new.text,new.heading); END""")
    bind.exec_driver_sql("""CREATE TRIGGER IF NOT EXISTS chunk_fts_del AFTER DELETE ON chunks BEGIN
        INSERT INTO chunks_fts(chunks_fts,rowid,text,heading) VALUES ('delete',old.id,old.text,old.heading); END""")
    bind.exec_driver_sql("""CREATE TRIGGER IF NOT EXISTS chunk_fts_update AFTER UPDATE ON chunks BEGIN
        INSERT INTO chunks_fts(chunks_fts,rowid,text,heading) VALUES ('delete',old.id,old.text,old.heading);
        INSERT INTO chunks_fts(rowid,text,heading) VALUES (new.id,new.text,new.heading); END""")


def downgrade():
    bind = op.get_bind()
    for name in ('chunk_fts_ins','chunk_fts_del','chunk_fts_update'):
        bind.exec_driver_sql(f'DROP TRIGGER IF EXISTS {name}')
    bind.exec_driver_sql('DROP TABLE IF EXISTS chunks_fts')
    Base.metadata.drop_all(bind)
