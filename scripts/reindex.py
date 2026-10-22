"""Offline rebuild after changing embedding/chunk configuration. Stop the server first."""
import argparse
import json
import re

from app.core.config import Settings
from app.rag import KnowledgeBase, make_embedding
from app.rag.embedding_cache import CachedEmbedding

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


is_pyvi = (settings.embedding_provider == "huggingface" and
           "vietnamese-bi-encoder" in settings.local_embedding_model.lower())
namespace = (f"{settings.embedding_provider}|{settings.embedding_base_url}|"
             f"{settings.embedding_model}|{settings.local_embedding_model}|"
             f"{settings.embedding_revision}|pyvi={is_pyvi}")
embedding = CachedEmbedding(make_embedding(settings), settings.data_dir.resolve() / "embedding-cache.sqlite3", namespace)

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
