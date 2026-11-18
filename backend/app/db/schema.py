"""FTS and vector-index lifecycle. SQLAlchemy schema via Alembic."""
from sqlalchemy import text
from app.core.config import settings
from app.db.models import Base, Source
from app.db.session import engine, session_factory, vector_loaded


def initialize() -> None:
    eng = engine()
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(text("""CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            text, heading, content='chunks', content_rowid='id', tokenize='unicode61 remove_diacritics 2')"""))
        conn.execute(text("""CREATE TRIGGER IF NOT EXISTS chunk_fts_ins AFTER INSERT ON chunks BEGIN
            INSERT INTO chunks_fts(rowid,text,heading) VALUES (new.id,new.text,new.heading); END"""))
        conn.execute(text("""CREATE TRIGGER IF NOT EXISTS chunk_fts_del AFTER DELETE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts,rowid,text,heading) VALUES ('delete',old.id,old.text,old.heading); END"""))
        conn.execute(text("""CREATE TRIGGER IF NOT EXISTS chunk_fts_update AFTER UPDATE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts,rowid,text,heading) VALUES ('delete',old.id,old.text,old.heading);
            INSERT INTO chunks_fts(rowid,text,heading) VALUES (new.id,new.text,new.heading); END"""))
        if vector_loaded():
            dim = settings().embedding_dim
            conn.execute(text(f"CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors USING vec0(embedding float[{dim}])"))
    with session_factory()() as db:
        for name, url in [("darglobal", "https://darglobal.co.uk/"), ("wasalt", "https://wasalt.sa/")]:
            if not db.get(Source, name):
                db.add(Source(id=name, name="DarGlobal" if name == "darglobal" else "Wasalt", base_url=url))
        db.commit()


def rebuild_fts() -> None:
    with engine().begin() as conn:
        conn.execute(text("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')"))
