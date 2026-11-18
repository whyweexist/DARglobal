# Source-grounded retrieval evaluation input

This directory intentionally has **no made-up evaluation queries**. After permitted ingestion, create `retrieval/queries.jsonl`, with each line containing a question and a list of **real** official source URLs present in the SQLite index. For example, the format is `{"question":"<an actual sourced question>","relevant_urls":["<a verified official URL>"]}`; the angle-bracket values are syntax guidance, not dataset entries.

Run `make eval`. The Makefile mounts this directory read-only into the evaluation container so the optional, locally created corpus does not need to be baked into the production Docker image. Without a labeled corpus, evaluation exits with an explicit error rather than inventing metrics.
