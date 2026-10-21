"""Bulk-import a crawled corpus into one tenant with one atomic BKAI index rebuild.

This is intentionally separate from the HTTP upload endpoint: importing many files one
by one would rebuild the full vector index for every document.  The current snapshot
stays live until the new, fully embedded snapshot is committed.
"""

import argparse
import hashlib
import json
import re
import threading
from pathlib import Path

from app.core.config import Settings
from app.rag import KnowledgeBase, make_embedding, read_document


def content_id(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_records(pointer: Path) -> list[dict]:
    if not pointer.exists():
        return []
    manifest = json.loads(pointer.read_text(encoding="utf-8"))
    records = manifest.get("records")
    if not isinstance(records, list):
        raise ValueError(f"Manifest không có danh sách records hợp lệ: {pointer}")
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a crawler TXT corpus into a RAG tenant")
    parser.add_argument("--tenant", default="vnpost")
    parser.add_argument("--dataset", type=Path, default=Path("datasets/vnpost_rag_100/documents"))
    parser.add_argument("--dry-run", action="store_true", help="Validate and show the import plan without writing")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", args.tenant):
        parser.error("Invalid tenant")

    settings = Settings()
    expected_model = "bkai-foundation-models/vietnamese-bi-encoder"
    if settings.embedding_provider != "huggingface" or settings.local_embedding_model.lower() != expected_model:
        raise SystemExit(
            "This importer requires EMBEDDING_PROVIDER=huggingface and "
            f"LOCAL_EMBEDDING_MODEL={expected_model}."
        )
    if settings.chunk_size > settings.embedding_max_length:
        raise SystemExit("CHUNK_SIZE must not exceed EMBEDDING_MAX_LENGTH for BKAI.")

    dataset = args.dataset.resolve()
    if not dataset.is_dir():
        raise SystemExit(f"Dataset folder not found: {dataset}")
    source_files = sorted(dataset.glob("*.txt"), key=lambda item: item.name.casefold())
    if not source_files:
        raise SystemExit(f"No TXT files found in: {dataset}")

    root = settings.data_dir.resolve() / "kb" / args.tenant
    pointer = root / "current.json"
    existing_records = load_records(pointer)
    existing_ids = {record["id"] for record in existing_records}

    imported_records: list[dict] = []
    preloaded: dict[str, list] = {}
    structural_units = 0
    for source in source_files:
        raw = source.read_bytes()
        document_id = content_id(raw)
        if document_id in existing_ids:
            continue
        loaded = read_document(source.name, raw, document_id, settings, extra_metadata={"is_global": True})
        structural_units += len(loaded)
        preloaded[document_id] = loaded
        imported_records.append({
            "id": document_id,
            "filename": source.name,
            "stored_name": document_id + ".txt",
            "bytes": len(raw),
            "is_global": True,
            "session_id": None,
            "user_id": None,
        })

    all_records = [*existing_records, *imported_records]
    if len(all_records) > settings.max_documents:
        raise SystemExit(f"Import would exceed MAX_DOCUMENTS ({settings.max_documents}).")
    plan = {
        "tenant": args.tenant,
        "dataset": str(dataset),
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.local_embedding_model,
        "embedding_max_length": settings.embedding_max_length,
        "chunk_size": settings.chunk_size,
        "existing_documents": len(existing_records),
        "new_documents": len(imported_records),
        "total_documents": len(all_records),
        "new_structural_units_before_long_unit_split": structural_units,
    }
    if args.dry_run:
        print(json.dumps({**plan, "dry_run": True}, ensure_ascii=False))
        return
    if not imported_records:
        print(json.dumps({**plan, "skipped": "all dataset files already exist"}, ensure_ascii=False))
        return

    # Load BKAI before writing into the live tenant.  If model loading fails, no
    # document or pointer is changed.
    embedding = make_embedding(settings)
    root.mkdir(parents=True, exist_ok=True)
    raw_dir = root / "documents"
    raw_dir.mkdir(parents=True, exist_ok=True)
    created_paths: list[Path] = []
    try:
        for record in imported_records:
            target = raw_dir / record["stored_name"]
            if target.exists():
                if content_id(target.read_bytes()) != record["id"]:
                    raise RuntimeError(f"Storage collision at {target}")
                continue
            target.write_bytes((dataset / record["filename"]).read_bytes())
            created_paths.append(target)

        # Build only once.  _commit atomically switches current.json after BKAI
        # embeddings and the vector index have been persisted successfully.
        kb = KnowledgeBase.__new__(KnowledgeBase)
        kb.root = root
        kb.settings = settings
        kb.embedding = embedding
        kb.reranker = None
        kb.lock = threading.RLock()
        kb.raw_dir = raw_dir
        kb._commit(all_records, preloaded)
    except BaseException:
        for created in created_paths:
            created.unlink(missing_ok=True)
        raise

    print(json.dumps({
        **plan,
        "chunks": len(kb.snapshot.nodes),
        "revision": kb.snapshot.revision,
        "status": "imported",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()