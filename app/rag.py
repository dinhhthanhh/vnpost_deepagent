import hashlib
import io
import json
import math
import os
import re
import shutil
import threading
import unicodedata
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from docx import Document as WordDocument
from docx.table import Table
from docx.text.paragraph import Paragraph
from llama_index.core import Document, StorageContext, VectorStoreIndex, load_index_from_storage
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import MetadataMode, TextNode
from llama_index.core.vector_stores import FilterCondition, FilterOperator, MetadataFilter, MetadataFilters
from rank_bm25 import BM25Plus

from app.config import Settings
from app.embedding_cache import CachedEmbedding
from app.providers import ProviderClients

STOPWORDS = set("va la cua co cho cac nhung mot trong voi duoc den tu thi nay do ve theo hay toi ban gi nao bao nhieu tai lieu xin hay the khong thong tin".split())


def tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower().replace("đ", "d"))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return [t for t in re.findall(r"\w+", text) if t not in STOPWORDS]


class DemoHashEmbedding(BaseEmbedding):
    """Deterministic token hashing, ONLY for offline plumbing tests; not semantic AI."""
    model_name: str = "demo-hash-v1"
    dimensions: int = 256

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in tokens(text):
            value = int.from_bytes(hashlib.sha256(token.encode()).digest()[:8], "big")
            vector[value % self.dimensions] += 1
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._vector(query)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._vector(query)

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._vector(text)


def make_embedding(settings: Settings, clients: ProviderClients | None = None) -> BaseEmbedding:
    if settings.embedding_provider == "hash":
        return DemoHashEmbedding()
    if settings.embedding_provider == "huggingface":
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding
        is_e5 = "e5" in settings.local_embedding_model.lower()
        return HuggingFaceEmbedding(model_name=settings.local_embedding_model,
                                   query_instruction="query: " if is_e5 else "",
                                   text_instruction="passage: " if is_e5 else "",
                                   normalize=True, embed_batch_size=16)
    from llama_index.embeddings.openai import OpenAIEmbedding
    # model_name selects a custom engine on OpenAI-compatible embedding servers.
    return OpenAIEmbedding(model_name=settings.embedding_model,
                           api_key=settings.embedding_api_key.get_secret_value(),
                           api_base=settings.embedding_base_url, max_retries=1,
                           timeout=settings.llm_timeout_seconds, embed_batch_size=32,
                           additional_kwargs={"encoding_format": "float"},
                           http_client=clients.sync if clients else None,
                           async_http_client=clients.async_ if clients else None)


def read_document(filename: str, raw: bytes, document_id: str, settings: Settings, extra_metadata: dict | None = None) -> list[Document]:
    suffix = Path(filename).suffix.lower()
    is_global = extra_metadata.get("is_global", True) if extra_metadata else True
    session_id = extra_metadata.get("session_id") if extra_metadata else None
    user_id = extra_metadata.get("user_id") if extra_metadata else None
    metadata = {
        "filename": filename,
        "document_id": document_id,
        "is_global": "true" if is_global else "false",
        "session_id": str(session_id) if session_id else "",
        "user_id": str(user_id) if user_id else "",
        "scope": "global" if is_global else "session",
    }
    excluded = ["filename", "document_id", "location", "is_global", "session_id", "user_id", "scope"]

    def doc(text, location):
        return Document(text=text, metadata={**metadata, "location": location},
                        excluded_embed_metadata_keys=excluded, excluded_llm_metadata_keys=excluded)

    if suffix == ".txt":
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("TXT phải dùng UTF-8; hãy lưu lại bằng UTF-8.") from exc
        if "\x00" in text or not text.strip():
            raise ValueError("TXT không có nội dung văn bản hợp lệ.")
        # Paragraph ranges, not invented page numbers.
        groups, lines = [], text.splitlines()
        for start in range(0, len(lines), 40):
            content = "\n".join(lines[start:start + 40]).strip()
            if content:
                groups.append(doc(content, f"Dòng {start + 1}–{min(start + 40, len(lines))}"))
        return groups
    if suffix == ".pdf":
        import pypdf
        try:
            reader = pypdf.PdfReader(io.BytesIO(raw))
            documents = []
            for i, page in enumerate(reader.pages, 1):
                page_text = (page.extract_text() or "").strip()
                if page_text:
                    page_text = re.sub(r"\n{3,}", "\n\n", page_text)
                    documents.append(doc(page_text, f"Trang {i}"))
            if not documents:
                raise ValueError("PDF không có văn bản (có thể là file scan ảnh cần OCR).")
            return documents
        except Exception as exc:
            if isinstance(exc, ValueError):
                raise
            raise ValueError("Không đọc được PDF; file có thể hỏng hoặc bị mã hóa.") from exc
    if suffix != ".docx":
        raise ValueError("Chỉ hỗ trợ .docx, .txt và .pdf; hãy chuyển đổi file sang các định dạng này.")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > 3000 or sum(e.file_size for e in entries) > settings.max_docx_expanded_bytes:
                raise ValueError("DOCX quá lớn sau giải nén.")
            if "word/document.xml" not in archive.namelist():
                raise ValueError("File không phải DOCX hợp lệ.")
        word = WordDocument(io.BytesIO(raw))
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ValueError("Không đọc được DOCX; file có thể hỏng hoặc được mã hóa.") from exc
    documents, buffer = [], []
    paragraph_number, table_number, start, section = 0, 0, 1, "Nội dung"

    def flush():
        nonlocal buffer, start
        if buffer:
            documents.append(doc("\n".join(buffer), f"{section}; đoạn {start}–{paragraph_number}"))
            buffer = []
        start = paragraph_number + 1

    for element in word.element.body.iterchildren():
        if element.tag.endswith("}p"):
            paragraph_number += 1
            paragraph = Paragraph(element, word)
            if paragraph.style and paragraph.style.name.startswith("Heading"):
                flush()
                section = paragraph.text.strip() or section
                start = paragraph_number
            if paragraph.text.strip():
                buffer.append(paragraph.text.strip())
            if len(buffer) >= 12:
                flush()
        elif element.tag.endswith("}tbl"):
            flush()
            table_number += 1
            table = Table(element, word)
            header = " | ".join(c.text.strip() for c in table.rows[0].cells) if table.rows else ""
            for row_number, row in enumerate(table.rows, 1):
                row_text = " | ".join(c.text.strip() for c in row.cells)
                if row_text.strip(" |"):
                    text = row_text if row_number == 1 else f"Cột: {header}\nDữ liệu: {row_text}"
                    documents.append(doc(text, f"{section}; bảng {table_number}, hàng {row_number}"))
    flush()
    if not documents:
        raise ValueError("DOCX không có văn bản; ảnh scan cần OCR trước khi nhập.")
    return documents


@dataclass(frozen=True)
class Snapshot:
    index: VectorStoreIndex | None
    nodes: list[TextNode]
    bm25: BM25Plus | None
    token_sets: list[set[str]]
    records: list[dict]
    revision: str


class KnowledgeBase:
    """Immutable read snapshots, serialized writes; intended for a small/medium pilot."""

    def __init__(self, root: Path, settings: Settings, embedding: BaseEmbedding):
        self.root, self.settings, self.embedding = root, settings, embedding
        self.lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        self.raw_dir = self.root / "documents"
        self.raw_dir.mkdir(exist_ok=True)
        self.snapshot = self._load()

    def _fingerprint(self):
        value = {"provider": self.settings.embedding_provider,
                 "endpoint": self.settings.embedding_base_url,
                 "revision": self.settings.embedding_revision,
                 "model": self.embedding.model_name, "chunk_size": self.settings.chunk_size,
                 "chunk_overlap": self.settings.chunk_overlap, "parser": "v1"}
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def _snapshot(self, index, nodes, records, revision):
        term_lists = [tokens(n.text) or ["__empty__"] for n in nodes]
        return Snapshot(index, nodes, BM25Plus(term_lists) if nodes else None,
                        [set(t) for t in term_lists], records, revision)

    def _load(self):
        pointer = self.root / "current.json"
        if not pointer.exists():
            return self._snapshot(None, [], [], "empty")
        manifest = json.loads(pointer.read_text())
        if manifest["fingerprint"] != self._fingerprint():
            raise ValueError("Embedding/chunk config đã đổi; chạy scripts/reindex.py để dựng lại KB.")
        folder = self.root / "snapshots" / manifest["revision"]
        index = load_index_from_storage(StorageContext.from_defaults(persist_dir=str(folder)),
                                        embed_model=self.embedding) if manifest["records"] else None
        nodes = list(index.docstore.docs.values()) if index else []
        if index and hasattr(index.vector_store, "_data"):
            for nid, meta in index.vector_store._data.metadata_dict.items():
                if "is_global" not in meta:
                    meta["is_global"] = "true"
                    meta["scope"] = "global"
                    meta["session_id"] = ""
                    meta["user_id"] = ""
        for node in nodes:
            if "is_global" not in node.metadata:
                node.metadata["is_global"] = "true"
                node.metadata["scope"] = "global"
                node.metadata["session_id"] = ""
                node.metadata["user_id"] = ""
        return self._snapshot(index, nodes, manifest["records"], manifest["revision"])

    def _commit(self, records: list[dict], preloaded: dict[str, list[Document]] | None = None):
        documents = []
        for record in records:
            loaded = (preloaded or {}).get(record["id"])
            extra_meta = {
                "is_global": record.get("is_global", True),
                "session_id": record.get("session_id"),
                "user_id": record.get("user_id"),
            }
            documents.extend(loaded if loaded is not None else read_document(
                record["filename"], (self.raw_dir / record["stored_name"]).read_bytes(),
                record["id"], self.settings, extra_metadata=extra_meta))
        if sum(len(d.text) for d in documents) > self.settings.max_corpus_characters:
            raise ValueError("Kho tài liệu vượt MAX_CORPUS_CHARACTERS.")
        splitter = SentenceSplitter(chunk_size=self.settings.chunk_size,
                                    chunk_overlap=self.settings.chunk_overlap,
                                    tokenizer=lambda s: re.findall(r"\w+|[^\w\s]", s),
                                    chunking_tokenizer_fn=lambda s: re.split(r"(?<=[.!?;])\s+", s),
                                    include_metadata=True)
        nodes = splitter.get_nodes_from_documents(documents, show_progress=False)
        for node in nodes:
            identity = f"{node.metadata['document_id']}|{node.metadata['location']}|{node.text}"
            node.id_ = hashlib.sha256(identity.encode()).hexdigest()
        revision = uuid.uuid4().hex
        folder = self.root / "snapshots" / revision
        folder.mkdir(parents=True)
        try:
            index = VectorStoreIndex(nodes, embed_model=self.embedding, show_progress=False) if nodes else None
            if index:
                index.storage_context.persist(persist_dir=str(folder))
            manifest = {"revision": revision, "fingerprint": self._fingerprint(), "records": records}
            staged = self.root / "current.tmp"
            staged.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            os.replace(staged, self.root / "current.json")
            self.snapshot = self._snapshot(index, nodes, records, revision)
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        # In-flight readers have immutable in-memory references to the previous snapshot.
        for old in folder.parent.iterdir():
            if old != folder and old.is_dir():
                shutil.rmtree(old, ignore_errors=True)

    def ingest(self, filename: str, raw: bytes, is_global: bool | None = None,
               session_id: str | None = None, user_id: str | None = None) -> dict:
        # Client filenames are display metadata; storage names are generated IDs.
        filename = Path(filename.replace("\\", "/")).name[:180]
        if len(raw) > self.settings.max_upload_bytes:
            raise ValueError("File vượt giới hạn upload.")
        document_id = hashlib.sha256(raw).hexdigest()
        if is_global is None:
            is_global = False if (session_id or user_id) else True
        with self.lock:
            existing = next((r for r in self.snapshot.records if r["id"] == document_id), None)
            if existing:
                return {**existing, "duplicate": True}
            if len(self.snapshot.records) >= self.settings.max_documents:
                raise ValueError("Kho tài liệu đã đạt MAX_DOCUMENTS.")
            extra_meta = {
                "is_global": is_global,
                "session_id": str(session_id) if session_id else None,
                "user_id": str(user_id) if user_id else None,
            }
            loaded = read_document(filename, raw, document_id, self.settings, extra_metadata=extra_meta)
            record = {"id": document_id, "filename": filename,
                      "stored_name": document_id + Path(filename).suffix.lower(), "bytes": len(raw),
                      "is_global": is_global,
                      "session_id": str(session_id) if session_id else None,
                      "user_id": str(user_id) if user_id else None}
            path = self.raw_dir / record["stored_name"]
            path.write_bytes(raw)
            try:
                self._commit([*self.snapshot.records, record], {document_id: loaded})
            except Exception:
                path.unlink(missing_ok=True)
                raise
            return {**record, "duplicate": False}

    def remove(self, document_id: str) -> bool:
        with self.lock:
            record = next((r for r in self.snapshot.records if r["id"] == document_id), None)
            if not record:
                return False
            self._commit([r for r in self.snapshot.records if r["id"] != document_id])
            (self.raw_dir / record["stored_name"]).unlink(missing_ok=True)
            return True

    def retrieve(self, query: str, top_k: int | None = None,
                 session_id: str | None = None, user_id: str | None = None) -> list[dict]:
        snapshot = self.snapshot
        if not snapshot.nodes:
            return []
        k = min(top_k or self.settings.retrieval_top_k, 15)
        query_terms = set(tokens(query))
        if not query_terms:
            return []

        def matches_scope(node_meta: dict) -> bool:
            if node_meta.get("is_global") in (True, "true"):
                return True
            if session_id and str(node_meta.get("session_id", "")) == str(session_id):
                return True
            if user_id and str(node_meta.get("user_id", "")) == str(user_id):
                return True
            return False

        scores = snapshot.bm25.get_scores(list(query_terms))
        lexical = sorted((i for i, terms in enumerate(snapshot.token_sets)
                          if (terms & query_terms) and matches_scope(snapshot.nodes[i].metadata)),
                         key=lambda i: scores[i], reverse=True)[:k * 3]

        # LlamaIndex MetadataFilters: is_global == 'true' OR session_id == current_session
        filter_list = [MetadataFilter(key="is_global", value="true", operator=FilterOperator.EQ)]
        if session_id:
            filter_list.append(MetadataFilter(key="session_id", value=str(session_id), operator=FilterOperator.EQ))
        if user_id:
            filter_list.append(MetadataFilter(key="user_id", value=str(user_id), operator=FilterOperator.EQ))
        filters = MetadataFilters(filters=filter_list, condition=FilterCondition.OR)

        # LlamaIndex is responsible for actual embedding/vector retrieval with metadata filters
        vector = snapshot.index.as_retriever(similarity_top_k=k * 3, filters=filters).retrieve(query)

        fused, by_id = {}, {n.node_id: n for n in snapshot.nodes}
        for rank, i in enumerate(lexical, 1):
            node_id = snapshot.nodes[i].node_id
            fused[node_id] = fused.get(node_id, 0) + 1 / (60 + rank)
        for rank, hit in enumerate(vector, 1):
            if (hit.score or 0) >= self.settings.vector_min_similarity:
                fused[hit.node.node_id] = fused.get(hit.node.node_id, 0) + 1 / (60 + rank)
        result = []
        for node_id in sorted(fused, key=fused.get, reverse=True)[:k]:
            node = by_id[node_id]
            if not matches_scope(node.metadata):
                continue
            result.append({"document_id": node.metadata["document_id"],
                           "filename": node.metadata["filename"], "location": node.metadata["location"],
                           "chunk_id": node_id, "excerpt": node.get_content(metadata_mode=MetadataMode.NONE),
                           "retrieval_score": round(fused[node_id], 6),
                           "is_global": node.metadata.get("is_global") in (True, "true"),
                           "session_id": node.metadata.get("session_id") or None})
        return result


class KnowledgeBases:
    def __init__(self, settings: Settings, clients: ProviderClients | None = None):
        self.settings = settings
        namespace = f"{settings.embedding_provider}|{settings.embedding_base_url}|{settings.embedding_model}|{settings.local_embedding_model}|{settings.embedding_revision}"
        self.embedding = CachedEmbedding(make_embedding(settings, clients), settings.data_dir.resolve() / "embedding-cache.sqlite3", namespace)
        self.items: dict[str, KnowledgeBase] = {}
        self.lock = threading.Lock()

    def for_tenant(self, tenant: str) -> KnowledgeBase:
        with self.lock:
            if tenant not in self.items:
                self.items[tenant] = KnowledgeBase(self.settings.data_dir.resolve() / "kb" / tenant,
                                                 self.settings, self.embedding)
            return self.items[tenant]
