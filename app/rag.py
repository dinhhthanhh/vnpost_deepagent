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
from llama_index.core.vector_stores import (
    FilterCondition,
    FilterOperator,
    MetadataFilter,
    MetadataFilters,
)
from rank_bm25 import BM25Plus

from app.config import Settings
from app.embedding_cache import CachedEmbedding
from app.providers import ProviderClients
from app.reranker import CrossEncoderReranker

STOPWORDS = set(
    "và là của có cho các những một trong với được đến từ thì này đó về theo hay tôi bạn gì nào bao nhiêu bao lâu mấy ngày năm tại thế như xin hãy không thông tin "
    "va la cua co cho cac nhung mot trong voi duoc den tu thi nay do ve theo hay toi ban gi nao bao nhieu bao lau may ngay nam tai the nhu xin hay khong thong tin".split()
)


def resolve_embedding_device(requested: str) -> str:
    """Resolve embedding device for fallback CPU/CUDA."""
    return "cpu" if requested in ("auto", "cpu") else requested


def tokens(text: str) -> list[str]:
    text_nfc = unicodedata.normalize("NFC", (text or "").lower())
    text_nfkd = unicodedata.normalize("NFKD", text_nfc.replace("đ", "d"))
    no_accents = "".join(c for c in text_nfkd if not unicodedata.combining(c))
    toks_no_accents = [t for t in re.findall(r"\w+", no_accents) if t not in STOPWORDS]
    return list(dict.fromkeys(toks_no_accents))


def filter_relevant_hits(query: str, hits: list[dict], min_overlap: int | None = None) -> list[dict]:
    """Lọc các hit có từ khóa trùng khớp thực sự với câu hỏi (loại bỏ stopwords). Dùng chung cho cả Fast RAG và Deep Agent."""
    if not hits:
        return []
    clean_q = query.strip().lower()
    q_tokens = [tok for tok in tokens(query) if tok not in STOPWORDS]
    if not q_tokens:
        return hits

    q_words = [tok for tok in q_tokens if not tok.isdigit()]
    filtered = []

    if q_words:
        q_terms = set(q_words)
        threshold = min_overlap if min_overlap is not None else (1 if len(q_terms) <= 2 else 2)
        for hit in hits:
            excerpt = (hit.get("excerpt", "") or "").lower()
            e_terms = set(tok for tok in tokens(excerpt) if not tok.isdigit())
            if len(q_terms & e_terms) >= threshold:
                filtered.append(hit)
    else:
        # Nếu query chỉ gồm số/ngày tháng (ví dụ: "8/3", "20/10", "30/4")
        dates = re.findall(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", clean_q)
        for hit in hits:
            excerpt = (hit.get("excerpt", "") or "").lower()
            if dates:
                if any(d in excerpt for d in dates):
                    filtered.append(hit)
            else:
                e_terms = set(tokens(excerpt))
                if len(set(q_tokens) & e_terms) >= len(q_tokens):
                    filtered.append(hit)

    return filtered


def resolve_search_query(message: str, history: list[dict] | None = None) -> str:
    """Nếu câu hỏi hiện tại ngắn hoặc mang tính tham chiếu (follow-up), kết hợp ngữ cảnh lượt trước để truy vấn RAG chính xác."""
    clean = (message or "").strip()
    words = clean.split()
    if not history or len(words) > 10:
        return clean
    referential_keywords = (
        "tài liệu nào", "ở đâu", "bao nhiêu", "như thế nào", "thời gian", "khi nào",
        "chi tiết", "cụ thể", "vùng", "cước", "phí", "nó", "dịch vụ này", "gói này",
        "tại sao", "ai", "mã nào", "bảng giá", "bảng cước", "quy định ở đâu",
    )
    is_referential = len(words) <= 5 or any(kw in clean.lower() for kw in referential_keywords)
    if not is_referential:
        return clean
    last_user_query = ""
    for turn in reversed(history):
        if turn.get("role") == "user" and turn.get("content"):
            last_user_query = turn["content"].strip()
            break
    if not last_user_query or last_user_query.lower() == clean.lower():
        return clean
    return f"{last_user_query} ({clean})"


def embedding_units(text: str) -> list[str]:
    """Conservative token estimate used only to protect an encoder's input window."""
    return re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE)


def structure_aware_nodes(documents: list[Document], settings: Settings) -> list[TextNode]:
    """Keep structural units intact; split only units too large for the embedding model."""
    splitter = SentenceSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        tokenizer=embedding_units,
        chunking_tokenizer_fn=lambda s: re.split(r"(?<=[.!?;])\s+", s),
        include_metadata=True,
    )
    nodes = []
    for document in documents:
        if len(embedding_units(document.text)) <= settings.chunk_size:
            nodes.append(TextNode(
                text=document.text,
                metadata=document.metadata.copy(),
                excluded_embed_metadata_keys=document.excluded_embed_metadata_keys,
                excluded_llm_metadata_keys=document.excluded_llm_metadata_keys,
            ))
        else:
            # A section/page/row is exceptionally long. SentenceSplitter preserves paragraph
            # and sentence boundaries before using token-level fallback.
            nodes.extend(splitter.get_nodes_from_documents([document], show_progress=False))
    return nodes

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
    # Pydantic loads .env without exporting it. Hugging Face clients read HF_TOKEN
    # from the process environment, so bridge the configured secret at startup.
    hf_token = settings.hf_token.get_secret_value()
    if hf_token:
        os.environ.setdefault("HF_TOKEN", hf_token)
    if settings.hf_hub_offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
    if settings.embedding_provider == "hash":
        return DemoHashEmbedding()
    if settings.embedding_provider == "huggingface":
        device = resolve_embedding_device(settings.embedding_device)
        # This PhoBERT bi-encoder must receive Vietnamese text with word segmentation.
        # Its published SentenceTransformers configuration is 256 tokens / 768 dimensions.
        if settings.local_embedding_model.lower() == "bkai-foundation-models/vietnamese-bi-encoder":
            from app.vietnamese_embedding import VietnameseBiEncoderEmbedding
            return VietnameseBiEncoderEmbedding(model_name=settings.local_embedding_model,
                                                device=device,
                                                embed_batch_size=settings.embedding_batch_size,
                                                max_length=settings.embedding_max_length)

        import importlib
        try:
            mod = importlib.import_module("llama_index.embeddings.huggingface")
            HuggingFaceEmbedding = mod.HuggingFaceEmbedding
        except ImportError as exc:
            raise RuntimeError("HuggingFace embedding requires 'local-embedding' extras.") from exc
        is_e5 = "e5" in settings.local_embedding_model.lower()
        return HuggingFaceEmbedding(model_name=settings.local_embedding_model,
                                   query_instruction="query: " if is_e5 else "",
                                   text_instruction="passage: " if is_e5 else "",
                                   normalize=True, device=device,
                                   embed_batch_size=settings.embedding_batch_size)
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
    authority = extra_metadata.get("authority", "legacy_unverified") if extra_metadata else "legacy_unverified"
    source_url = extra_metadata.get("source_url") if extra_metadata else None
    issuer = extra_metadata.get("issuer") if extra_metadata else None
    metadata = {
        "filename": filename,
        "document_id": document_id,
        "is_global": "true" if is_global else "false",
        "session_id": str(session_id) if session_id else "",
        "user_id": str(user_id) if user_id else "",
        "scope": "global" if is_global else "session",
        "authority": authority,
        "source_url": source_url or "",
        "issuer": issuer or "",
    }
    excluded = ["filename", "document_id", "location", "is_global", "session_id", "user_id", "scope", "authority", "source_url", "issuer"]

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
        # Preserve the author's structure for TXT/Markdown exports. In particular,
        # tariff tables are represented one row at a time with their named columns;
        # fixed line-count splitting loses that relationship and hurts retrieval.
        lines = text.splitlines()
        title = Path(filename).stem
        for line in lines:
            match = re.match(r"^#\s+(.+?)\s*$", line)
            if match:
                title = match.group(1)
                break

        documents, paragraph, table_number = [], [], 0
        section, paragraph_start = title, 1

        def contextualize(content: str) -> str:
            if section and section != title:
                return f"# {title}\n\n## {section}\n\n{content}"
            return f"# {title}\n\n{content}"

        def flush_paragraph(end_line: int):
            nonlocal paragraph, paragraph_start
            content = "\n".join(paragraph).strip()
            if content:
                documents.append(doc(contextualize(content),
                                     f"{section}; dòng {paragraph_start}–{end_line}"))
            paragraph = []

        def is_source_preamble(line: str) -> bool:
            return line.startswith(("Nguồn:", "Vị trí nguồn:", "Ngày thu thập:"))

        line_index = 0
        while line_index < len(lines):
            line_number = line_index + 1
            line = lines[line_index].strip()
            header = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
            if header and len(line) <= 200:
                flush_paragraph(line_number - 1)
                section = header.group(1)
                paragraph_start = line_number + 1
                line_index += 1
                continue
            is_numbered_heading = re.match(r"^(?:[IVXLCDM]+|\d+)\.\s+\S", line)
            if (not paragraph and is_numbered_heading and len(line) <= 120
                    and line_index + 1 < len(lines) and not lines[line_index + 1].strip()):
                section = line
                paragraph_start = line_number + 1
                line_index += 1
                continue
            if is_source_preamble(line):
                flush_paragraph(line_number - 1)
                paragraph_start = line_number + 1
                line_index += 1
                continue
            if line.startswith("|"):
                table_start = line_index
                table_lines = []
                while line_index < len(lines) and lines[line_index].strip().startswith("|"):
                    table_lines.append(lines[line_index].strip())
                    line_index += 1
                flush_paragraph(table_start)
                if len(table_lines) >= 3 and re.match(r"^\|?\s*:?-{3,}", table_lines[1]):
                    headers = [cell.strip() for cell in table_lines[0].strip("|").split("|")]
                    table_number += 1
                    for row_offset, table_row in enumerate(table_lines[2:], 3):
                        values = [cell.strip() for cell in table_row.strip("|").split("|")]
                        if len(values) != len(headers) or not any(values):
                            continue
                        pairs = [f"{key}: {value}" for key, value in zip(headers, values) if value]
                        row_text = (f"Bảng {table_number} — {section}\n"
                                    + "; ".join(pairs) + "\n\n"
                                    + table_lines[0] + "\n" + table_lines[1] + "\n" + table_row)
                        documents.append(doc(contextualize(row_text),
                                             f"{section}; bảng {table_number}, hàng {row_offset}"))
                else:
                    documents.append(doc(contextualize("\n".join(table_lines)),
                                         f"{section}; dòng {table_start + 1}–{line_index}"))
                paragraph_start = line_index + 1
                continue
            if not line:
                flush_paragraph(line_number - 1)
                paragraph_start = line_number + 1
            else:
                if not paragraph:
                    paragraph_start = line_number
                paragraph.append(line)
            line_index += 1
        flush_paragraph(len(lines))
        if not documents:
            raise ValueError("TXT không có đơn vị nội dung hợp lệ.")
        return documents
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
        elif element.tag.endswith("}tbl"):
            flush()
            table_number += 1
            table = Table(element, word)
            if not table.rows:
                continue
            headers = [c.text.strip() or f"Cột {i}" for i, c in enumerate(table.rows[0].cells, 1)]
            # Repeat named columns with every row so tariff tables retain cell relationships.
            table_title = f"Bảng {table_number} — {section}"
            for row_number, row in enumerate(table.rows[1:], 2):
                values = [c.text.strip() for c in row.cells]
                pairs = [f"{header}: {value}" for header, value in zip(headers, values) if value]
                if pairs:
                    markdown = " | ".join(headers) + "\n" + " | ".join("---" for _ in headers)
                    markdown += "\n" + " | ".join(values)
                    text = f"{table_title}\n" + "; ".join(pairs) + "\n\n" + markdown
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

    def __init__(self, root: Path, settings: Settings, embedding: BaseEmbedding, ignore_fingerprint: bool = False, clients: ProviderClients | None = None):
        self.root, self.settings, self.embedding, self.clients = root, settings, embedding, clients
        self.reranker = CrossEncoderReranker(settings, clients=clients) if settings.reranker_enabled else None
        self.lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        self.raw_dir = self.root / "documents"
        self.raw_dir.mkdir(exist_ok=True)
        self.snapshot = self._load(ignore_fingerprint=ignore_fingerprint)

    def _fingerprint(self):
        value = {"provider": self.settings.embedding_provider,
                 "endpoint": self.settings.embedding_base_url,
                 "revision": self.settings.embedding_revision,
                 "model": self.embedding.model_name, "chunk_size": self.settings.chunk_size,
                 "chunk_overlap": self.settings.chunk_overlap, "parser": "v3-structure-first"}
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def _snapshot(self, index, nodes, records, revision):
        term_lists = [tokens(n.text) or ["__empty__"] for n in nodes]
        return Snapshot(index, nodes, BM25Plus(term_lists) if nodes else None,
                        [set(t) for t in term_lists], records, revision)

    def _load(self, ignore_fingerprint: bool = False):
        pointer = self.root / "current.json"
        if not pointer.exists():
            return self._snapshot(None, [], [], "empty")
        manifest = json.loads(pointer.read_text(encoding="utf-8"))
        if not ignore_fingerprint and manifest.get("fingerprint") != self._fingerprint():
            raise ValueError("Embedding/chunk config đã đổi; chạy scripts/reindex.py để dựng lại KB.")
        folder = self.root / "snapshots" / manifest["revision"]
        if not folder.exists() and ignore_fingerprint:
            return self._snapshot(None, [], manifest.get("records", []), manifest.get("revision", "empty"))
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

    def reindex(self) -> Snapshot:
        """Atomically rebuild the index from existing raw documents under current settings/embedding.

        The live pointer 'current.json' is only updated via os.replace AFTER the new
        snapshot and vectors are completely built and stored, ensuring zero corrupted
        state if interrupted.
        """
        pointer = self.root / "current.json"
        if not pointer.exists():
            raise ValueError("Tenant has no KB to reindex.")
        manifest = json.loads(pointer.read_text(encoding="utf-8"))
        records = manifest.get("records", [])
        with self.lock:
            self._commit(records)
            return self.snapshot

    def _commit(self, records: list[dict], preloaded: dict[str, list[Document]] | None = None):
        documents = []
        for record in records:
            loaded = (preloaded or {}).get(record["id"])
            extra_meta = {
                "is_global": record.get("is_global", True),
                "session_id": record.get("session_id"),
                "user_id": record.get("user_id"),
                "authority": record.get("authority", "legacy_unverified"),
                "source_url": record.get("source_url"),
                "issuer": record.get("issuer"),
            }
            documents.extend(loaded if loaded is not None else read_document(
                record["filename"], (self.raw_dir / record["stored_name"]).read_bytes(),
                record["id"], self.settings, extra_metadata=extra_meta))
        if sum(len(d.text) for d in documents) > self.settings.max_corpus_characters:
            raise ValueError("Kho tài liệu vượt MAX_CORPUS_CHARACTERS.")
        nodes = structure_aware_nodes(documents, self.settings)
        for ordinal, node in enumerate(nodes):
            # Text can legitimately repeat within one source (for example a repeated
            # tariff row or FAQ answer). Include the structural ordinal so the vector
            # store never overwrites a distinct chunk that happens to have the same text.
            identity = f"{node.metadata['document_id']}|{node.metadata['location']}|{ordinal}|{node.text}"
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
               session_id: str | None = None, user_id: str | None = None, *,
               authority: str = "user_upload", source_url: str | None = None, issuer: str | None = None) -> dict:
        # Client filenames are display metadata; storage names are generated IDs.
        filename = Path(filename.replace("\\", "/")).name[:180]
        if len(raw) > self.settings.max_upload_bytes:
            raise ValueError("File vượt giới hạn upload.")
        document_id = hashlib.sha256(raw).hexdigest()
        if is_global is None:
            is_global = False if (session_id or user_id) else True
        if authority not in {"vnpost_internal", "official_public", "user_upload"}:
            raise ValueError("Invalid document authority.")
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
                "authority": authority,
                "source_url": source_url,
                "issuer": issuer,
            }
            loaded = read_document(filename, raw, document_id, self.settings, extra_metadata=extra_meta)
            record = {"id": document_id, "filename": filename,
                "authority": authority,
                "source_url": source_url,
                "issuer": issuer,
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

    def remove_session(self, session_id: str) -> int:
        """Xóa toàn bộ tài liệu đính kèm riêng của session này khi xóa session."""
        with self.lock:
            matched = [r for r in self.snapshot.records if str(r.get("session_id", "")) == str(session_id)]
            if not matched:
                return 0
            matched_ids = {r["id"] for r in matched}
            self._commit([r for r in self.snapshot.records if r["id"] not in matched_ids])
            for r in matched:
                (self.raw_dir / r["stored_name"]).unlink(missing_ok=True)
            return len(matched)

    def retrieve(self, query: str, top_k: int | None = None,
                 session_id: str | None = None, user_id: str | None = None) -> list[dict]:
        snapshot = self.snapshot
        if not snapshot.nodes:
            return []
        k = min(top_k or self.settings.retrieval_top_k, 15)
        candidate_k = k * 3
        if self.reranker:
            candidate_k = max(candidate_k, self.settings.reranker_candidate_k)
        candidate_k = min(candidate_k, 50)
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


        # LlamaIndex MetadataFilters: is_global == 'true' OR session_id == current_session
        filter_list = [MetadataFilter(key="is_global", value="true", operator=FilterOperator.EQ)]
        if session_id:
            filter_list.append(MetadataFilter(key="session_id", value=str(session_id), operator=FilterOperator.EQ))
        if user_id:
            filter_list.append(MetadataFilter(key="user_id", value=str(user_id), operator=FilterOperator.EQ))
        filters = MetadataFilters(filters=filter_list, condition=FilterCondition.OR)

        # LlamaIndex is responsible for actual embedding/vector retrieval with metadata filters
        vector = snapshot.index.as_retriever(similarity_top_k=candidate_k, filters=filters).retrieve(query)
        vector_hits_map = {hit.node.node_id: float(hit.score or 0.0) for hit in vector}

        scores = snapshot.bm25.get_scores(list(query_terms))
        min_overlap = 1 if len(query_terms) <= 1 else 2
        lexical = sorted((i for i, terms in enumerate(snapshot.token_sets)
                          if ((len(terms & query_terms) >= min_overlap and scores[i] > 0)
                              or vector_hits_map.get(snapshot.nodes[i].node_id, 0.0) >= self.settings.vector_min_similarity)
                          and matches_scope(snapshot.nodes[i].metadata)),
                         key=lambda i: scores[i], reverse=True)[:candidate_k]

        fused, by_id = {}, {n.node_id: n for n in snapshot.nodes}
        for rank, i in enumerate(lexical, 1):
            node_id = snapshot.nodes[i].node_id
            fused[node_id] = fused.get(node_id, 0) + 1 / (60 + rank)
        for rank, hit in enumerate(vector, 1):
            if (hit.score or 0) >= self.settings.vector_min_similarity:
                fused[hit.node.node_id] = fused.get(hit.node.node_id, 0) + 1 / (60 + rank)
        candidates = []
        for node_id in sorted(fused, key=fused.get, reverse=True)[:candidate_k]:
            node = by_id[node_id]
            if not matches_scope(node.metadata):
                continue
            candidates.append({"document_id": node.metadata["document_id"],
                               "filename": node.metadata["filename"], "location": node.metadata["location"],
                               "chunk_id": node_id, "excerpt": node.get_content(metadata_mode=MetadataMode.NONE),
                               "retrieval_score": round(fused[node_id], 6),
                               "vector_score": round(vector_hits_map.get(node_id, 0.0), 4),
                               "is_global": node.metadata.get("is_global") in (True, "true"),
                                "session_id": node.metadata.get("session_id") or None,
                                "authority": node.metadata.get("authority", "legacy_unverified"),
                                "source_url": node.metadata.get("source_url") or None,
                                "issuer": node.metadata.get("issuer") or None})
        if self.reranker:
            candidates = self.reranker.rerank(query, candidates)
        return candidates[:k]


class KnowledgeBases:
    def __init__(self, settings: Settings, clients: ProviderClients | None = None):
        self.settings = settings
        self.clients = clients
        is_pyvi = (settings.embedding_provider == "huggingface" and
                   "vietnamese-bi-encoder" in settings.local_embedding_model.lower())
        namespace = (f"{settings.embedding_provider}|{settings.embedding_base_url}|"
                     f"{settings.embedding_model}|{settings.local_embedding_model}|"
                     f"{settings.embedding_revision}|pyvi={is_pyvi}")
        self.embedding = CachedEmbedding(make_embedding(settings, clients), settings.data_dir.resolve() / "embedding-cache.sqlite3", namespace)
        self.items: dict[str, KnowledgeBase] = {}
        self.lock = threading.Lock()

    def for_tenant(self, tenant: str) -> KnowledgeBase:
        with self.lock:
            if tenant not in self.items:
                self.items[tenant] = KnowledgeBase(self.settings.data_dir.resolve() / "kb" / tenant,
                                                 self.settings, self.embedding, clients=self.clients)
            return self.items[tenant]
