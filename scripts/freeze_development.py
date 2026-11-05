"""Snapshot selected saved observations without executing or modifying the notebook."""
import argparse
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("notebook", type=Path)
args = parser.parse_args()
raw = args.notebook.read_bytes()
nb = json.loads(raw)
selected = [10, 24, 38, 40, 48, 67, 69, 76, 81, 84, 86, 87, 94, 95, 96, 97, 98]
snapshot = {"source": str(args.notebook), "sha256": hashlib.sha256(raw).hexdigest(),
            "status": "historical saved notebook outputs; not reproduced by this script",
            "cell_indexing": "zero-based JSON indices", "cells": {}}
for index in selected:
    cell = nb["cells"][index]
    snapshot["cells"][str(index)] = {"source": "".join(cell["source"]), "outputs": [
        {"text": "".join(o.get("text", o.get("data", {}).get("text/plain", []))),
         "error": o.get("evalue")} for o in cell.get("outputs", [])]}
target = Path("evaluation/fixtures/notebook_snapshot.json")
target.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
print(target)
