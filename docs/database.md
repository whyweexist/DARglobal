# SQLite data model

Database: `/data/estate.db` inside API/worker containers, on Docker named volume `estate_data` in Codespaces and persistent bind mount on VPS. SQLite WAL, FK enforcement, 15-second busy timeout, one API worker and a separate controlled ingestion worker.

Core tables: `sources`, `documents`, `chunks`, `ingestion_runs`, `properties`, `conversations`, `messages`, `model_cache`.

- `documents.url` unique, with source ID, content SHA-256, language, timestamp and ingestion method.
- `chunks(document_id, ordinal)` unique, text, heading, checksum, token count and embedding-model identity.
- `chunks_fts`: external-content FTS5 virtual table; insert, delete and update triggers keep lexical search synchronized.
- `chunk_vectors`: sqlite-vec virtual table, row IDs correspond to `chunks.id`, using the dimension configured by `EMBEDDING_DIM`.
- `properties`: structured JSON-LD extracted fields; nulls for absent fields; no implied availability.
- `conversations`: ID + SHA-256 token digest; client token is required to retrieve or delete messages.

Alembic migrations create relational and lexical structures. `app.db.schema.initialize` additionally verifies/creates the compatible sqlite-vec table. Changing the embedding model/dimension requires a controlled index migration and rebuild; never mix dimensions.

For backup use `python -m app.cli backup --path /data/backups/date.db`, which uses the SQLite backup API; see [operations](operations.md).
