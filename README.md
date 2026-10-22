# VNPost Deep Agent

Trợ lý hội thoại cho nghiệp vụ bưu chính VNPost, kết hợp FastAPI, React, RAG có trích dẫn và Deep Agent điều phối các tác vụ cần công cụ chuyên biệt.

> Dự án không chứa API key, lịch sử chat, vector index hay dữ liệu crawl cục bộ. Sao chép `.env.example` thành `.env` và điền cấu hình của riêng bạn trước khi chạy.

## Tính năng

- RAG cho TXT, DOCX và PDF; kết hợp vector search, BM25 và reranking tùy chọn.
- Trích dẫn nguồn `[S1]`, kiểm tra citation và chặn trả lời thiếu bằng chứng khi bật grounded mode.
- Router retrieval-first: câu hỏi đơn giản đi Fast RAG; câu phức tạp, tính ngày tháng, mã vận đơn và bưu cục đi Deep Agent.
- Specialist tools cho tra cứu hành trình bưu gửi, bưu cục/mã bưu chính, tính toán và soạn thảo.
- Lưu lịch sử theo tenant/session, SSE streaming và TTS ZeroTTS tùy chọn.
- Xoá chat phản hồi ngay; quá trình dọn tài liệu/index riêng của session chạy nền.

## Kiến trúc

```text
React UI → FastAPI → Router
                    ├─ Fast RAG → evidence + citation
                    └─ Deep Agent → specialist tools / sub-agents

Knowledge base → hybrid retrieval → citation validation → response / TTS
```

## Yêu cầu

- Python 3.12
- Node.js 22+ (chỉ cần khi phát triển giao diện)
- Một LLM tương thích OpenAI có hỗ trợ tool/function calling nếu không chạy demo

## Chạy nhanh (demo/CPU)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.venv\Scripts\python.exe scripts\seed_demo.py
.venv\Scripts\python.exe -m uvicorn app.api.main:app --host 127.0.0.1 --port 8080
```

Mở [http://127.0.0.1:8080](http://127.0.0.1:8080). Demo dùng model và embedding giả lập để kiểm tra luồng; không đại diện cho chất lượng của LLM thật.

Trên Linux/macOS:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
cp .env.example .env
.venv/bin/python scripts/seed_demo.py
.venv/bin/python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8080
```

## Cấu hình môi trường

```bash
cp .env.example .env
```

Các biến quan trọng:

| Biến | Mục đích |
|---|---|
| `DEMO_MODE` | Dùng model giả lập khi `true`; production nên đặt `false`. |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | LLM chính tương thích OpenAI. |
| `EMBEDDING_PROVIDER`, `EMBEDDING_*` | Embedding cục bộ hoặc qua API. |
| `API_KEYS_JSON` | Khoá truy cập chatbot, ánh xạ theo tenant. |
| `DATA_DIR` | Thư mục dữ liệu runtime; không commit. |
| `TTS_*` | Cấu hình ZeroTTS tùy chọn. |

Chỉ dùng placeholder trong `.env.example`. Không đưa `.env`, API key, token, dữ liệu khách hàng hoặc index vào Git.

## Chạy với Docker

```bash
cp .env.example .env
# Điền giá trị production vào .env
docker compose up --build -d
```

Dịch vụ mặc định chỉ bind `127.0.0.1:8080`. Dữ liệu runtime được lưu trong Docker volume `chatbot_data`.

## Phát triển giao diện

```bash
cd frontend
npm ci
npm run dev
```

Vite phục vụ tại `http://127.0.0.1:5173` và proxy `/api` tới backend cổng 8080. Khi đóng gói production, chạy `npm run build`.

## Kiểm thử

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\ruff.exe check app scripts tests
cd frontend
npm run test
npm run build
```

## API và tài liệu

- OpenAPI khi server chạy: `/docs`
- Hợp đồng API: [docs/API.md](docs/API.md)
- Kiến trúc và đánh giá retrieval: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Cấu trúc mã nguồn

| Đường dẫn | Vai trò |
|---|---|
| `app/main.py` | API FastAPI, auth tenant, SSE và endpoints. |
| `app/service.py` | Điều phối request, session, timeout, TTS. |
| `app/router.py`, `app/signals.py` | Phân tuyến Fast/Deep theo tín hiệu rẻ. |
| `app/fast_rag.py`, `app/rag.py` | Retrieval và knowledge base. |
| `app/agents.py` | Deep Agent, specialist tools và validation. |
| `frontend/` | Giao diện React/Vite. |
| `tests/` | Unit, integration và contract tests. |

## Bảo mật

- Không commit `.env`, Postman environment, lịch sử, audio, index hay dữ liệu crawl.
- Dùng khóa riêng cho từng tenant và HTTPS/VPN cho các upstream service.
- Chỉ nạp nguồn public từ domain được allowlist hoặc tài liệu do người dùng cấp quyền.
- Trước khi push, chạy `git status` và kiểm tra staged diff để tránh đưa secrets vào repository.

## Giấy phép

Chưa kèm giấy phép mã nguồn. Hãy bổ sung tệp `LICENSE` trước khi phân phối công khai.
