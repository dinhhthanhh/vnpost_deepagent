"""Offline rebuild after changing embedding/chunk configuration. Stop the server first."""
import argparse
import json
import re

from app.config import Settings
from app.rag import KnowledgeBase, make_embedding

parser = argparse.ArgumentParser()
parser.add_argument("--tenant", required=True)
args = parser.parse_args()
if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", args.tenant):
    parser.error("Invalid tenant")

settings = Settings()
root = settings.data_dir.resolve() / "kb" / args.tenant
pointer = root / "current.json"
if not pointer.exists():
    raise SystemExit("Tenant has no KB to reindex.")

# Download/load the embedding model before touching any live index data.
embedding = make_embedding(settings)

# Atomic rebuild: KnowledgeBase.reindex() builds the new snapshot in a new revision directory
# and only swaps the live pointer 'current.json' via atomic rename upon complete success.
# If SIGKILL, OOM, or power loss occurs during reindexing, 'current.json' remains untouched
# and points to the previous valid snapshot.
kb = KnowledgeBase(root, settings, embedding, ignore_fingerprint=True)
snapshot = kb.reindex()

print(json.dumps({
    "tenant": args.tenant,
    "documents": len(snapshot.records),
    "chunks": len(snapshot.nodes),
    "revision": snapshot.revision,
}))
