#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from app.db.schema import initialize
from app.ingestion.importer import import_authorized_file

p = argparse.ArgumentParser(description="Import authorized CSV/JSON source export")
p.add_argument("file", type=Path)
p.add_argument("--source", choices=["wasalt", "darglobal"], required=True)
p.add_argument("--authorization-reference", required=True)
a = p.parse_args()
initialize()
print(json.dumps(import_authorized_file(a.file, a.source, a.authorization_reference), indent=2))
