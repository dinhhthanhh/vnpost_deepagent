"""Offline rebuild after changing embedding/chunk configuration. Stop the server first."""
import argparse
import json

from app.config import Settings
from app.rag import KnowledgeBase, make_embedding

parser = argparse.ArgumentParser()
parser.add_argument("--tenant", required=True)
args = parser.parse_args()
if not __import__("re").fullmatch(r"[a-zA-Z0-9_-]{1,64}", args.tenant):
    parser.error("Invalid tenant")
settings = Settings()
root = settings.data_dir.resolve() / "kb" / args.tenant
pointer = root / "current.json"
if not pointer.exists():
    raise SystemExit("Tenant has no KB")
manifest = json.loads(pointer.read_text())
backup = root / "current.backup.json"
backup.write_bytes(pointer.read_bytes())
pointer.unlink()
try:
    kb = KnowledgeBase(root, settings, make_embedding(settings))
    with kb.lock:
        kb._commit(manifest["records"])
except Exception:
    pointer.write_bytes(backup.read_bytes())
    raise
print(json.dumps({"tenant": args.tenant, "documents": len(kb.snapshot.records),
                  "chunks": len(kb.snapshot.nodes), "revision": kb.snapshot.revision}))
