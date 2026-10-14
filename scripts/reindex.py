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

# Download/load the embedding model before touching the live manifest.  If this
# fails, the existing KB remains available.  KnowledgeBase validates a manifest
# fingerprint on load, so stage a compatible pointer only for the rebuild.
embedding = make_embedding(settings)
probe = KnowledgeBase.__new__(KnowledgeBase)
probe.settings, probe.embedding = settings, embedding
compatible_manifest = {**manifest, "fingerprint": probe._fingerprint()}
staged = root / "current.reindex.json"
staged.write_text(json.dumps(compatible_manifest, ensure_ascii=False), encoding="utf-8")
staged.replace(pointer)
try:
    kb = KnowledgeBase(root, settings, embedding)
    with kb.lock:
        kb._commit(manifest["records"])
except BaseException:
    # Includes Ctrl+C and timeouts: never leave a tenant without current.json.
    pointer.write_bytes(backup.read_bytes())
    raise
print(json.dumps({"tenant": args.tenant, "documents": len(kb.snapshot.records),
                  "chunks": len(kb.snapshot.nodes), "revision": kb.snapshot.revision}))
