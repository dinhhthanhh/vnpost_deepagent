"""Crawl public VNPost content into a resumable, auditable TXT corpus.

The crawler respects robots.txt, limits each host to two in-flight requests and spaces
requests by default. It only follows official VNPost/EMS links (plus a directly linked
Google Drive file), and treats an FAQ pair as a document only when its answer text was
actually extracted.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
import time
from collections import Counter, deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup, Tag

OFFICIAL_HOSTS = {
    "vnpost.vn", "www.vnpost.vn", "vietnampost.vn", "www.vietnampost.vn",
    "ipostal.vnpost.vn", "ems.com.vn", "www.ems.com.vn",
}
GOOGLE_DRIVE_HOSTS = {"drive.google.com", "docs.google.com", "drive.usercontent.google.com"}
START_URLS = [
    "https://vnpost.vn/vi/ho-tro",
    "https://vnpost.vn/vi/dich-vu/chuyen-phat-trong-nuoc",
    "https://ipostal.vnpost.vn/",
    "https://ems.com.vn/",
    "https://vnpost.vn/vi/quy-trinh-tiep-nhan-va-giai-quyet-khieu-nai/quy-trinh-tiep-nhan-va-giai-quyet-khieu-nai-cua-khach-hang-su-dung-dich-vu-buu-chinh-chuyen-phat",
    "https://vnpost.vn/sitemap.xml",
    "https://ems.com.vn/sitemap.xml",
    "https://ipostal.vnpost.vn/sitemap.xml",
]
CONTENT_HINTS = ("ho-tro", "dich-vu", "chuyen-phat", "cuoc", "gia", "khieu-nai", "boi-thuong", "quy-trinh", "huong-dan", "dieu-kien", "dong-goi", "quoc-te", "faq", "tin-tuc", "buu-pham", "ems", "ipostal")
SKIP_HINTS = ("/login", "/dang-nhap", "/search", "/tim-kiem", "/gio-hang", "/cart", "facebook.com", "youtube.com", "zalo.me", "mailto:", "tel:")
USER_AGENT = "VNPostRAGResearchBot/1.0 (+https://vnpost.vn/; public-document-retrieval)"


@dataclass
class CrawlRecord:
    document_id: str
    filename: str
    title: str
    source_url: str
    source_locator: str
    source_domain: str
    document_type: str
    crawled_at: str
    published_at: str | None
    effective_date: str | None
    content_hash: str
    extraction_method: str
    review_status: str


@dataclass
class QueueItem:
    url: str
    discovered_from: str | None = None
    direct_official_link: bool = False


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = parts.netloc.lower().split("@")[-1]
    if host.endswith(":443") and scheme == "https":
        host = host[:-4]
    query = urlencode(sorted((key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                            if not key.lower().startswith(("utm_", "fbclid", "gclid"))))
    path = re.sub(r"/+", "/", parts.path or "/")
    return urlunsplit((scheme, host, path, query, ""))


def host_of(url: str) -> str:
    return urlsplit(url).hostname.lower() if urlsplit(url).hostname else ""


def is_pdf_url(url: str) -> bool:
    return urlsplit(url).path.lower().endswith(".pdf") or "download" in urlsplit(url).path.lower()


def safe_name(value: str, limit: int = 72) -> str:
    value = re.sub(r"[^a-zA-Z0-9À-ỹ]+", "-", value).strip("-").lower()
    return (value[:limit].strip("-") or "van-ban")


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def text_hash(value: str) -> str:
    return hashlib.sha256(normalized_text(value).encode()).hexdigest()


def table_to_markdown(table: Tag) -> str:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [normalized_text(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"], recursive=False)]
        if any(cells):
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    header_rows = 1
    if len(rows) > 1 and table.find("thead"):
        header_rows = sum(1 for _ in table.find("thead").find_all("tr")) or 1
    header = [" / ".join(rows[index][col] for index in range(min(header_rows, len(rows))) if rows[index][col]) or f"Cột {col + 1}" for col in range(width)]
    body = rows[header_rows:] or rows[:1]
    output = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    output.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(output)


def select_main(soup: BeautifulSoup) -> Tag:
    candidates = soup.select("main, article, [role='main'], .article-content, .entry-content, .post-content, .content-detail, .detail-content")
    candidates = [candidate for candidate in candidates if isinstance(candidate, Tag)]
    return max(candidates, key=lambda tag: len(tag.get_text(" ", strip=True)), default=soup.body or soup)


def extract_article(soup: BeautifulSoup) -> tuple[str, str]:
    for node in soup(["script", "style", "noscript", "svg", "iframe", "form", "button", "nav", "footer", "header", "aside"]):
        node.decompose()
    main = select_main(soup)
    title_tag = main.find("h1") or soup.find("h1") or soup.find("title")
    title = normalized_text(title_tag.get_text(" ", strip=True)) if title_tag else "Nội dung VNPost"
    blocks: list[str] = []
    seen: set[str] = set()
    for element in main.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote", "table"]):
        if element.name != "table" and element.find_parent(["p", "li", "blockquote", "table"]) is not None:
            continue
        value = table_to_markdown(element) if element.name == "table" else normalized_text(element.get_text(" ", strip=True))
        if len(value) < 2 or value in seen:
            continue
        seen.add(value)
        blocks.append(("## " if element.name in {"h1", "h2", "h3", "h4"} else "") + value)
    content = "\n\n".join(blocks)
    return title, content


def json_ld_faqs(soup: BeautifulSoup) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for script in soup.select("script[type='application/ld+json']"):
        try:
            payload = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        stack = payload if isinstance(payload, list) else [payload]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                if item.get("@type") in {"FAQPage", "https://schema.org/FAQPage"}:
                    for question in item.get("mainEntity", []):
                        name = normalized_text(str(question.get("name", "")))
                        answer = question.get("acceptedAnswer", {})
                        answer_text = normalized_text(str(answer.get("text", ""))) if isinstance(answer, dict) else ""
                        if name and len(answer_text) >= 40:
                            result.append((name, answer_text))
                stack.extend(value for value in item.values() if isinstance(value, (dict, list)))
            elif isinstance(item, list):
                stack.extend(item)
    return result


def visible_faqs(soup: BeautifulSoup) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(question: str, answer: str) -> None:
        question, answer = normalized_text(question), normalized_text(answer)
        pair = (question, answer)
        if question and len(answer) >= 40 and pair not in seen:
            seen.add(pair)
            pairs.append(pair)

    for details in soup.find_all("details"):
        question = details.find("summary")
        if question:
            add(question.get_text(" ", strip=True), details.get_text(" ", strip=True).replace(question.get_text(" ", strip=True), "", 1))
    # VNPost's support page uses Bootstrap accordions: the button's aria-controls
    # points to the answer panel. This reads the published Q&A, not link labels.
    for button in soup.select("button[aria-controls]"):
        target_id = button.get("aria-controls", "").strip()
        answer_panel = soup.find(id=target_id) if target_id else None
        if answer_panel:
            add(button.get_text(" ", strip=True), answer_panel.get_text(" ", strip=True))
    return pairs


def extract_dates(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    published = None
    for selector in ("meta[property='article:published_time']", "meta[name='date']", "time[datetime]"):
        node = soup.select_one(selector)
        if node:
            published = node.get("content") or node.get("datetime") or normalized_text(node.get_text(" ", strip=True))
            break
    text = normalized_text(soup.get_text(" ", strip=True))
    effective_match = re.search(r"(?:hiệu lực|áp dụng từ)\s*(?:ngày)?\s*([0-3]?\d[/-][01]?\d[/-]\d{4})", text, re.I)
    return published, effective_match.group(1) if effective_match else None


class PublicCrawler:
    def __init__(self, output: Path, target: int, max_pages: int, delay: float, concurrency: int, seeds: list[str], refresh: list[str] | None = None):
        self.output = output
        self.documents_dir = output / "documents"
        self.raw_dir = output / "raw"
        self.target, self.max_pages, self.delay, self.concurrency = target, max_pages, delay, concurrency
        self.seeds = [canonical_url(url) for url in seeds]
        self.refresh = [canonical_url(url) for url in (refresh or [])]
        self.manifest_path = output / "manifest.jsonl"
        self.checkpoint_path = output / "checkpoint.json"
        self.report_path = output / "crawl_report.json"
        self.queue: deque[QueueItem] = deque()
        self.queued: set[str] = set()
        self.completed: set[str] = set()
        self.manifest: dict[str, CrawlRecord] = {}
        self.content_hashes: set[str] = set()
        self.errors: list[dict[str, str]] = []
        self.skipped: Counter[str] = Counter()
        self.pages_accessed = 0
        self.host_locks: dict[str, asyncio.Lock] = {}
        self.host_last_request: dict[str, float] = {}
        self.host_semaphores: dict[str, asyncio.Semaphore] = {}
        self.robots: dict[str, RobotFileParser | None] = {}
        self.robots_locks: dict[str, asyncio.Lock] = {}
        self.client: httpx.AsyncClient | None = None
        self.checkpoint_counter = 0

    def load(self) -> None:
        self.output.mkdir(parents=True, exist_ok=True)
        self.documents_dir.mkdir(exist_ok=True)
        self.raw_dir.mkdir(exist_ok=True)
        if self.manifest_path.exists():
            for line in self.manifest_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    item = CrawlRecord(**json.loads(line))
                    self.manifest[item.document_id] = item
                    self.content_hashes.add(item.content_hash)
        if self.checkpoint_path.exists():
            data = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            self.completed = set(data.get("completed", []))
            for raw_item in data.get("queue", []):
                item = QueueItem(**raw_item)
                self.queue.append(item)
                self.queued.add(item.url)
            self.pages_accessed = int(data.get("pages_accessed", 0))
            self.errors = list(data.get("errors", []))
            self.skipped.update(data.get("skipped", {}))
        # Re-add seeds on resume: completed URLs are ignored, while newly added sitemap
        # seeds can extend a previous incomplete crawl without discarding its queue.
        for url in self.refresh:
            self.completed.discard(url)
            self.enqueue(QueueItem(url))
        for url in self.seeds:
            self.enqueue(QueueItem(url))

    def enqueue(self, item: QueueItem) -> None:
        url = canonical_url(item.url)
        host = host_of(url)
        if not url.startswith(("http://", "https://")) or url in self.completed or url in self.queued:
            return
        if host in GOOGLE_DRIVE_HOSTS and not item.direct_official_link:
            return
        if host not in OFFICIAL_HOSTS and host not in GOOGLE_DRIVE_HOSTS:
            return
        lowered = url.lower()
        if any(hint in lowered for hint in SKIP_HINTS) or re.search(r"\.(?:jpg|jpeg|png|gif|webp|mp4|zip|docx?|xlsx?)$", lowered):
            return
        is_sitemap = urlsplit(url).path.lower().endswith(("sitemap.xml", "sitemap_index.xml"))
        if host in OFFICIAL_HOSTS and not is_pdf_url(url) and not is_sitemap and not any(hint in lowered for hint in CONTENT_HINTS) and "/vi/" not in lowered:
            return
        self.queue.append(QueueItem(url, item.discovered_from, item.direct_official_link))
        self.queued.add(url)

    def save_checkpoint(self) -> None:
        data = {"completed": sorted(self.completed), "queue": [asdict(item) for item in self.queue], "pages_accessed": self.pages_accessed, "errors": self.errors, "skipped": dict(self.skipped), "updated_at": utc_now()}
        self.checkpoint_counter += 1
        staged = self.checkpoint_path.with_name(f"checkpoint.{self.checkpoint_counter}.tmp")
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        staged.write_text(payload, encoding="utf-8")
        try:
            staged.replace(self.checkpoint_path)
        except PermissionError:
            # Windows antivirus/indexing can momentarily hold the destination open.
            # Keep the crawl resumable instead of failing an otherwise successful fetch.
            staged.unlink(missing_ok=True)
            self.checkpoint_path.write_text(payload, encoding="utf-8")
        self.manifest_path.write_text("\n".join(json.dumps(asdict(record), ensure_ascii=False) for record in self.manifest.values()) + ("\n" if self.manifest else ""), encoding="utf-8")

    async def allowed_by_robots(self, url: str) -> bool:
        host = host_of(url)
        if host not in self.robots:
            lock = self.robots_locks.setdefault(host, asyncio.Lock())
            async with lock:
                if host not in self.robots:
                    robots_url = f"{urlsplit(url).scheme}://{host}/robots.txt"
                    parser = RobotFileParser()
                    try:
                        response = await self.raw_request(robots_url, check_robots=False)
                        if response.status_code == 200:
                            parser.parse(response.text.splitlines())
                            self.robots[host] = parser
                            for sitemap_url in getattr(parser, "site_maps", lambda: [])() or []:
                                self.enqueue(QueueItem(sitemap_url, robots_url))
                        else:
                            self.robots[host] = None
                            self.errors.append({"url": robots_url, "stage": "robots", "error": f"HTTP {response.status_code}; treated as unavailable"})
                    except Exception as exc:
                        self.robots[host] = None
                        self.errors.append({"url": robots_url, "stage": "robots", "error": type(exc).__name__})
        parser = self.robots[host]
        return True if parser is None else parser.can_fetch(USER_AGENT, url)

    async def raw_request(self, url: str, check_robots: bool = True) -> httpx.Response:
        assert self.client is not None
        if check_robots and not await self.allowed_by_robots(url):
            raise PermissionError("robots_disallow")
        host = host_of(url)
        sem = self.host_semaphores.setdefault(host, asyncio.Semaphore(2))
        async with sem:
            lock = self.host_locks.setdefault(host, asyncio.Lock())
            async with lock:
                loop = asyncio.get_running_loop()
                remaining = self.delay - (loop.time() - self.host_last_request.get(host, 0))
                if remaining > 0:
                    await asyncio.sleep(remaining)
                self.host_last_request[host] = loop.time()
            retry_after = 0.0
            for attempt in range(3):
                if retry_after:
                    await asyncio.sleep(retry_after)
                try:
                    response = await self.client.get(url)
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt == 2:
                        raise RuntimeError(type(exc).__name__) from exc
                    retry_after = min(8.0, 1.5 * (2 ** attempt))
                    continue
                if response.status_code == 429 and attempt < 2:
                    try:
                        retry_after = min(30.0, float(response.headers.get("Retry-After", "2")))
                    except ValueError:
                        retry_after = 2.0
                    continue
                return response
            raise RuntimeError("retry_exhausted")

    def write_raw(self, url: str, body: bytes, content_type: str) -> str:
        suffix = ".pdf" if "pdf" in content_type.lower() or is_pdf_url(url) else ".html"
        name = hashlib.sha256(url.encode()).hexdigest()[:20] + suffix
        path = self.raw_dir / name
        if not path.exists():
            path.write_bytes(body)
        return name

    def add_document(self, *, title: str, content: str, source_url: str, locator: str, document_type: str, extraction_method: str, published_at: str | None, effective_date: str | None) -> bool:
        if len(self.manifest) >= self.target:
            return False
        content = re.sub(r"[ \t]+\n", "\n", content.replace("\r", ""))
        content = re.sub(r"\n{3,}", "\n\n", content).strip()
        if len(content) < 120:
            self.skipped["content_too_short"] += 1
            return False
        digest = text_hash(content)
        if digest in self.content_hashes:
            self.skipped["duplicate_content"] += 1
            return False
        stable = hashlib.sha256(f"{source_url}\n{locator}".encode()).hexdigest()
        filename = f"{safe_name(title)}-{stable[:12]}.txt"
        crawled_at = utc_now()
        document = CrawlRecord(stable, filename, title, source_url, locator, host_of(source_url), document_type, crawled_at, published_at, effective_date, digest, extraction_method, "auto_extracted")
        body = f"# {title}\n\nNguồn: {source_url}\nVị trí nguồn: {locator}\nNgày thu thập: {crawled_at}\n\n{content}\n"
        (self.documents_dir / filename).write_text(body, encoding="utf-8")
        self.manifest[stable] = document
        self.content_hashes.add(digest)
        return True

    def discover_links(self, soup: BeautifulSoup, base: str) -> list[QueueItem]:
        items = []
        base_host = host_of(base)
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "").strip()
            if not href or href.startswith(("#", "javascript:")):
                continue
            url = canonical_url(urljoin(base, href))
            host = host_of(url)
            if host not in OFFICIAL_HOSTS and host not in GOOGLE_DRIVE_HOSTS:
                continue
            items.append(QueueItem(url, base, direct_official_link=(base_host in OFFICIAL_HOSTS and host in GOOGLE_DRIVE_HOSTS)))
        # Relevant content is visited sooner and gives deterministic resume ordering.
        return sorted(items, key=lambda item: (not any(hint in item.url.lower() for hint in CONTENT_HINTS), item.url))

    async def process(self, item: QueueItem) -> None:
        url = item.url
        try:
            response = await self.raw_request(url)
            self.pages_accessed += 1
            final_url = canonical_url(str(response.url))
            if host_of(final_url) not in OFFICIAL_HOSTS and host_of(final_url) not in GOOGLE_DRIVE_HOSTS:
                raise RuntimeError("redirected_outside_allowed_hosts")
            if response.status_code >= 400:
                raise RuntimeError(f"HTTP {response.status_code}")
            content_type = response.headers.get("content-type", "")
            self.write_raw(final_url, response.content, content_type)
            if "xml" in content_type.lower() or urlsplit(final_url).path.lower().endswith(("sitemap.xml", "sitemap_index.xml")):
                sitemap = BeautifulSoup(response.text, "xml")
                for loc in sitemap.find_all("loc"):
                    if loc.text.strip():
                        self.enqueue(QueueItem(loc.text.strip(), final_url))
                return
            if "pdf" in content_type.lower() or is_pdf_url(final_url):
                import pypdf
                pages = pypdf.PdfReader(__import__("io").BytesIO(response.content)).pages
                text_pages = [normalized_text(page.extract_text() or "") for page in pages]
                text = "\n\n".join(f"## Trang {index}\n{page}" for index, page in enumerate(text_pages, 1) if page)
                if len(text) < 200:
                    self.errors.append({"url": final_url, "stage": "pdf", "error": "scan_or_no_extractable_text; not counted"})
                    return
                title = Path(urlsplit(final_url).path).stem.replace("-", " ") or "Tài liệu PDF VNPost"
                self.add_document(title=title, content=text, source_url=final_url, locator=f"PDF gốc ({len(text_pages)} trang)", document_type="pdf", extraction_method="pypdf_text", published_at=None, effective_date=None)
                return
            if "html" not in content_type.lower() and not response.text.lstrip().startswith("<"):
                self.skipped["unsupported_content_type"] += 1
                return
            soup = BeautifulSoup(response.text, "html.parser")
            # Read FAQ markup before article cleanup removes interactive buttons/scripts.
            schema_faqs = json_ld_faqs(soup)
            faqs = schema_faqs or visible_faqs(soup)
            faq_method = "jsonld_faq" if schema_faqs else "html_faq"
            title, article = extract_article(soup)
            published_at, effective_date = extract_dates(soup)
            if len(article) >= 250:
                self.add_document(title=title, content=article, source_url=final_url, locator=f"Tiêu đề trang: {title}", document_type="article", extraction_method="html_main", published_at=published_at, effective_date=effective_date)
            for question, answer in faqs:
                self.add_document(title=question, content=f"Câu hỏi: {question}\n\nTrả lời: {answer}", source_url=final_url, locator=f"FAQ: {question}", document_type="faq", extraction_method=faq_method, published_at=published_at, effective_date=effective_date)
            for link in self.discover_links(soup, final_url):
                self.enqueue(link)
        except PermissionError:
            self.skipped["robots_disallow"] += 1
            self.errors.append({"url": url, "stage": "robots", "error": "disallowed"})
        except Exception as exc:
            self.errors.append({"url": url, "stage": "fetch_or_extract", "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
        finally:
            self.completed.add(url)
            self.save_checkpoint()

    async def run(self) -> None:
        self.load()
        timeout = httpx.Timeout(25.0, connect=15.0)
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT, "Accept-Language": "vi,en;q=0.7"}, follow_redirects=True, timeout=timeout, max_redirects=5) as client:
            self.client = client
            active: set[asyncio.Task] = set()
            while active or (self.queue and len(self.manifest) < self.target and self.pages_accessed < self.max_pages):
                while self.queue and len(active) < self.concurrency and self.pages_accessed + len(active) < self.max_pages:
                    item = self.queue.popleft()
                    self.queued.discard(item.url)
                    if item.url in self.completed:
                        continue
                    active.add(asyncio.create_task(self.process(item)))
                if not active:
                    break
                done, active = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
        self.save_checkpoint()
        self.write_report()

    def write_report(self, ingestion: dict[str, Any] | None = None, retrieval: dict[str, Any] | None = None) -> None:
        report = {
            "generated_at": utc_now(), "target_documents": self.target,
            "valid_documents": len(self.manifest), "source_urls": len({record.source_url for record in self.manifest.values()}),
            "pages_accessed": self.pages_accessed, "queue_remaining": len(self.queue),
            "duplicate_or_skipped": dict(self.skipped), "errors": self.errors,
            "robots_checked_hosts": sorted(self.robots), "raw_files": len(list(self.raw_dir.iterdir())) if self.raw_dir.exists() else 0,
            "ingestion": ingestion, "retrieval": retrieval,
        }
        self.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def make_draft_questions(records: list[CrawlRecord], output: Path, count: int = 20) -> list[dict[str, Any]]:
    questions = []
    for record in records:
        path = output / "documents" / record.filename
        text = path.read_text(encoding="utf-8")
        body = text.split("\n\n", 3)[-1]
        evidence = next((sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", body) if len(sentence.strip()) >= 35), "")
        words = re.findall(r"[\wÀ-ỹ]+", record.title)
        query = " ".join(words[:8])
        if len(query) < 6 or not evidence:
            continue
        questions.append({"id": f"draft-{len(questions) + 1:02d}", "question": f"Thông tin về {query} là gì?", "expected_filename": record.filename, "expected_excerpt_contains": evidence[:80], "source_url": record.source_url, "source_locator": record.source_locator, "status": "draft_requires_business_review"})
        if len(questions) == count:
            break
    (output / "evaluation_questions_draft.jsonl").write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in questions) + ("\n" if questions else ""), encoding="utf-8")
    return questions


def ingest_demo(records: list[CrawlRecord], output: Path, questions: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    from app.core.config import Settings
    from app.rag import KnowledgeBases, read_document

    settings = Settings(_env_file=None, data_dir=output / "test_index", demo_mode=True, embedding_provider="hash", chunk_size=256)
    kb = KnowledgeBases(settings).for_tenant("vnpost-crawl-test")
    valid_files = []
    for record in records:
        raw = (output / "documents" / record.filename).read_bytes()
        parsed = read_document(record.filename, raw, record.document_id, settings)
        if not parsed or not any(doc.text.strip() for doc in parsed):
            raise ValueError(f"Parser rejected {record.filename}")
        for attempt in range(4):
            try:
                kb.ingest(record.filename, raw, is_global=True)
                break
            except PermissionError:
                if attempt == 3:
                    raise
                time.sleep(0.5 * (attempt + 1))
        valid_files.append(record.filename)
    ranks = []
    for question in questions:
        hits = kb.retrieve(question["question"])
        rank = next((index for index, hit in enumerate(hits, 1) if hit["filename"] == question["expected_filename"] and question["expected_excerpt_contains"].lower() in hit["excerpt"].lower()), None)
        ranks.append(rank)
    answerable = len(ranks)
    retrieval = {"questions": answerable, "recall_at_k": sum(rank is not None for rank in ranks) / answerable if answerable else None, "mrr_at_k": sum(1 / rank if rank else 0 for rank in ranks) / answerable if answerable else None, "embedding_provider": "hash", "quality_note": "Demo hash embedding validates ingestion plumbing only, not semantic retrieval quality."}
    return {"files_ingested": len(valid_files), "chunks": len(kb.snapshot.nodes), "index_path": str((output / "test_index").resolve())}, retrieval


def write_readme(output: Path) -> None:
    (output / "README.md").write_text("""# VNPost public RAG crawl dataset

This corpus is built only from public pages on official VNPost, EMS and iPostal domains (and an official page's directly linked Google Drive document). It keeps raw downloads, normalized TXT documents, a source manifest and a resumable checkpoint.

## Run

```powershell
.\\.venv\\Scripts\\python scripts\\crawl_vnpost_public.py --output datasets/vnpost_rag_100 --target 100 --max-pages 250 --ingest-demo
```

The crawler checks `robots.txt`, uses at most two concurrent requests per host, waits at least 1.2 seconds between requests to the same host and resumes from `checkpoint.json`. It does not use an LLM to synthesize content. A PDF with no extractable text is reported and excluded; no OCR claim is made.

`evaluation_questions_draft.jsonl` uses the schema accepted by `scripts/evaluate_retrieval.py`, with source URL/locator extras. These are draft questions that require VNPost business review. The optional test index uses the project's hash embedding, so its retrieval scores validate ingestion only, not real semantic quality.

Each TXT starts with source URL, source locator and crawl timestamp, allowing the existing TXT parser to retain traceability in retrieved excerpts.
""", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("datasets/vnpost_rag_100"))
    parser.add_argument("--target", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=250)
    parser.add_argument("--delay", type=float, default=1.2)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--seed", action="append", default=[])
    parser.add_argument("--refresh", action="append", default=[], help="Revisit a completed URL to apply an improved extractor")
    parser.add_argument("--ingest-demo", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.target <= 1000 or args.max_pages < args.target or args.delay < 1 or not 1 <= args.concurrency <= 16:
        parser.error("target/max-pages/delay/concurrency out of bounds")
    return args


async def async_main(args: argparse.Namespace) -> None:
    crawler = PublicCrawler(args.output, args.target, args.max_pages, args.delay, args.concurrency, args.seed or START_URLS, args.refresh)
    await crawler.run()
    write_readme(args.output)
    records = list(crawler.manifest.values())[:args.target]
    questions = make_draft_questions(records, args.output)
    ingestion = retrieval = None
    if args.ingest_demo:
        ingestion, retrieval = ingest_demo(records, args.output, questions)
    crawler.write_report(ingestion, retrieval)
    print(json.dumps({"documents": len(records), "source_urls": len({r.source_url for r in records}), "pages_accessed": crawler.pages_accessed, "errors": len(crawler.errors), "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        asyncio.run(async_main(parse_args()))
    except KeyboardInterrupt:
        print("Interrupted; checkpoint.json can be resumed.", file=sys.stderr)
        raise