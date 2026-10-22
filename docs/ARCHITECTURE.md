# Kiến trúc chatbot Deep Agent + RAG + ZeroTTS & STT

Phiên bản 1.3.0 (Cập nhật đồng bộ 100% với Codebase thực tế). Tài liệu này mô tả ứng dụng đang vận hành: Backend FastAPI (`app/`), giao diện React (`frontend/`), cụm lưu trữ doanh nghiệp PostgreSQL 16 (`compose.yaml`), giao thức FastMCP / A2A, và các dịch vụ AI (vLLM BGE-M3, Qwen3-Reranker-8B, ZeroTTS, Whisper STT).

Mục tiêu là chọn đường xử lý tối ưu nhất nhưng luôn đảm bảo bằng chứng: câu đơn giản/xã giao trả lời tức thì qua Tầng 0; câu tra cứu văn bản đi qua Fast RAG; các yêu cầu đa bước, tính cước thể tích, tra cứu hành trình, GPS bưu cục, tạo đơn gửi hàng hoặc khiếu nại bồi thường được điều phối tự động qua Deep Agent Supervisor.

## 1. Thành phần đang triển khai

```mermaid
flowchart TD
    U[Người dùng / React 19 UI\n• Canvas Image Compressor\n• Voice STT & TTS Audio Player\n• Prompt Re-ask / Edit History] --> API[FastAPI Gateway app.api.main]
    API --> AUTH[Rate Limiter & X-API-Key Resolver]
    AUTH --> FP[Tầng 0: Đường tắt xã giao & số học AST]
    AUTH --> RT[Router 4 tầng Zero-LLM Fast-First]
    FP --> OUT[Đáp án trực tiếp]
    RT -->|Một ý tra cứu tài liệu| FAST[Tầng 1: Fast RAG Engine]
    RT -->|Nhiều bước, so sánh, nghiệp vụ thời gian thực| DEEP[Tầng 2 & 3: Deep Agent Supervisor]
    FAST --> KB[KnowledgeBase: Hybrid Dense BGE-M3 + BM25 + Qwen Reranker]
    DEEP --> PREFETCH[Prefetched Evidence Loader]
    PREFETCH --> KB
    DEEP -.->|Parallel Dispatch| RAG[rag-agent\nTra cứu văn bản]
    DEEP -.->|Parallel Dispatch| ANA[analyst-agent\nTính cước 6000 & Ngày UTC+7]
    DEEP -.->|Parallel Dispatch| TRK[tracking-agent\nĐịnh vị vận đơn S10]
    DEEP -.->|Parallel Dispatch| PO[post-office-agent\nBưu cục & GPS Google Maps]
    DEEP -.->|HITL 2-Phase| BOK[booking-agent\nTiếp nhận đặt gửi hàng]
    DEEP -.->|HITL 2-Phase| COM[complaint-agent\nKhiếu nại bồi thường 6/12 tháng]
    DEEP -.->|Sequential Turn| WR[writer-agent\nSoạn thảo văn bản]
    RAG --> KB
    TRK --> POSTAL[VNPost Postal Services API]
    PO --> POSTAL
    BOK --> DB_DRAFTS[PostgreSQL: draft_bookings]
    COM --> DB_DRAFTS[PostgreSQL: draft_complaints]
    DEEP --> CHECKPOINT[PostgreSQL 16 Connection Pool\nPersistentPostgresCheckpointer]
    DEEP --> MCP[FastMCP Server & A2A Server]
    FAST --> CHECK[Kiểm tra trích dẫn [S1]... & Entailment]
    DEEP --> CHECK
    CHECK --> SSE[JSON Response hoặc SSE Stream]
    SSE --> TTS[ZeroTTS Adapter\nStreaming Audio]
    U -.->|Ghi âm micro| STT[Voice STT: Whisper / HuggingFace API]
    STT -.->|Văn bản nhận diện| API
```

| Thành phần | Trách nhiệm thực tế trong Codebase |
|---|---|
| **FastAPI Gateway** | Điểm tiếp nhận `/api/chat`, `/api/chat/stream`, `/api/stt`, `/api/tts`, `/api/documents`, quản lý phiên và tài liệu. |
| **Router (Bộ định tuyến)** | Phân luồng 4 tầng Zero-LLM (`app/router/classifier.py` và `app/agents/signals.py`) với độ trễ < 0.1ms; chỉ gọi LLM Router khi opt-in `LLM_ROUTER_ENABLED=true`. |
| **Tầng 0 (Fast Path)** | Phản hồi chào hỏi, cảm ơn, phép tính số học trực tiếp hoặc thời gian tương đối mà không tốn chi phí gọi LLM/RAG. |
| **Tầng 1 (Fast RAG)** | Truy hồi lai 1 lượt (Dense BGE-M3 + BM25 + Qwen Reranker) và 1 lượt LLM streaming; tích hợp **Trí nhớ hội thoại tự nhiên** đọc ngữ cảnh 10 lượt gần nhất. |
| **Tầng 2 & 3 (Deep Agent)** | Nhạc trưởng Supervisor (LangGraph StateGraph) điều phối đồng thời 7 Sub-agents chuyên trách; hỗ trợ Human-in-the-Loop (HITL), ngắt/hủy đơn nháp và quản lý ngân sách task. |
| **Hệ thống 7 Sub-agents** | `rag-agent`, `analyst-agent`, `writer-agent`, `tracking-agent`, `post-office-agent`, `booking-agent`, `complaint-agent`. |
| **Cơ sở dữ liệu PostgreSQL 16** | Lưu trữ tập trung bảng phiên (`sessions`), phản hồi (`replies`), bản nháp đơn hàng/khiếu nại (`draft_bookings`, `draft_complaints`), bộ nhớ trạng thái (`checkpoints` qua `AsyncPostgresSaver`) và bộ đệm nhúng vector (`embedding_cache`). |
| **Voice STT & TTS Pipeline** | Chuyển đổi giọng nói hai chiều: Nhận diện giọng nói qua Whisper API (`/api/stt`) và tổng hợp giọng nói tự nhiên qua ZeroTTS streaming (`/api/tts/stream`). |
| **Chuẩn FastMCP & A2A** | Máy chủ FastMCP (`app/mcp/server.py`) và máy chủ giao tiếp Agent-to-Agent (`app/a2a/server.py`). |

---

## 2. Luồng định tuyến và xử lý yêu cầu

1. **Xác thực & Tách Tenant**: API xác thực `X-API-Key` và ánh xạ sang tenant (mặc định `vnpost`). Kiểm soát tốc độ qua Sliding Window Rate Limiter.
2. **Tầng 0 (Zero-LLM Bypass)**: Nếu nhận diện lời chào hỏi (`sig.chitchat`) hoặc phép tính số học thuần túy (`try_evaluate_math`), hệ thống phản hồi tức thì trong 30ms không tốn tài nguyên RAG.
3. **Tầng 1 (Fast RAG - Mặc định)**: Với các câu hỏi tra cứu quy chế, biểu cước, dịch vụ đơn lẻ hoặc câu hỏi về thông tin trao đổi trong hội thoại, Fast RAG thực hiện tìm kiếm và sinh câu trả lời trong ~1.5 – 2.2 giây.
4. **Tầng 2 & 3 (Deep Agent Escalation)**: Khi câu hỏi có mã vận đơn (`_POSTAL_OPS`), yêu cầu tìm bưu điện gần nhất qua GPS, đặt đơn gửi hàng, khiếu nại, tính toán ngày tháng/lịch trình (`_TEMPORAL_CALC`), hoặc so sánh phức tạp (`_COMPARE`, `_MULTISTEP`), Router lập tức chuyển sang Deep Agent Supervisor.
5. **Human-in-the-Loop (HITL) 2 Pha**:
   - Pha 1: Sub-agent thu thập thông tin (slot filling), tạo bản ghi nháp trong PostgreSQL và trình bày tóm tắt cho khách hàng.
   - Pha 2: Chờ khách hàng phản hồi "Xác nhận/Đồng ý" mới chính thức kích hoạt công cụ cấp mã vận đơn hoặc mã ticket. Nếu khách từ chối, hỗ trợ gọi hủy nháp tức thì.
6. **Kiểm tra Bằng chứng & Trích dẫn**:
   - Mọi câu trả lời nghiệp vụ từ RAG phải kèm mã nguồn `[S1]`, `[S2]` và vượt qua đối soát từ khóa excerpt để chống ảo giác. Nếu tài liệu không chứa thông tin, trả về thông báo chuẩn hóa `NO_EVIDENCE_TEMPLATE`.
   - Với tác vụ thời gian thực từ `tracking-agent`, `post-office-agent`, `booking-agent`, kết quả được gán trạng thái `grounding_status="computed"` đảm bảo tính xác thực.
   - Với các câu hỏi về diễn biến phiên trò chuyện, hệ thống sử dụng lịch sử cuộc trò chuyện làm nguồn sự thật (Ground Truth) mà không ép `[[NO_EVIDENCE]]`.

---

## 3. Danh mục 7 Sub-agents và Điều phối song song

| Sub-agent | Công cụ chính | Trách nhiệm nghiệp vụ |
|---|---|---|
| `rag-agent` | `search_documents`, `read_file` | Tìm kiếm tài liệu nội bộ (.docx, .txt, .pdf) theo câu hỏi cụ thể, trích xuất đoạn văn bản kèm mã trích dẫn `[S...]`. |
| `analyst-agent` | `calculate`, `calculate_date`, `read_file` | Tính toán số học AST an toàn, tính cước hàng cồng kềnh (D×R×C/6000), và tính ngày tháng chuẩn múi giờ Việt Nam UTC+7. |
| `tracking-agent` | `track_item` | Tra cứu hành trình bưu phẩm/bưu kiện VNPost theo mã vận đơn chuẩn UPU S10 (13 ký tự) hoặc nội địa. |
| `post-office-agent` | `find_nearest_post_office`, `lookup_post_office` | Tìm bưu điện gần nhất theo tọa độ GPS (latitude, longitude), tính khoảng cách km và tạo link Google Maps; tra cứu địa chỉ, giờ mở cửa qua Vpostcode. |
| `booking-agent` | `create_draft_booking`, `confirm_booking`, `cancel_draft_booking`, `cancel_booking`, `list_my_orders` | Thu thập thông tin gửi/nhận, trọng lượng/kích thước, tạo đơn hàng nháp, chờ người dùng duyệt HITL và hủy đơn linh hoạt. |
| `complaint-agent` | `create_draft_complaint`, `confirm_complaint`, `cancel_draft_complaint`, `cancel_complaint`, `list_my_orders` | Tiếp nhận khiếu nại mất mát/hư hỏng/chậm phát, đối chiếu thời hiệu 06 tháng nội địa / 12 tháng quốc tế, tạo ticket nháp và duyệt HITL. |
| `writer-agent` | `read_file` | Soạn thảo công văn, văn bản thông báo hoặc báo cáo tổng hợp từ dữ liệu đã thu thập (chế độ fork kế thừa context). |

Supervisor điều phối giao việc bằng công cụ `task(subagent_type, description)`. Các sub-agent độc lập được LangGraph gom đợt và chạy song song theo `max_parallel_subagents = 3` được kiểm soát bằng Semaphore `run.slots`.

---

## 4. Quản lý trạng thái Checkpointer và Kỹ năng doanh nghiệp (/skills/)

- **PostgreSQL Checkpointer (`AsyncPostgresSaver`)**:
  - Lưu trạng thái đồ thị LangGraph vào PostgreSQL (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`) với thread ID `{tenant}:{session_id}`.
  - Cho phép khôi phục phiên làm việc, hỗ trợ Human-in-the-Loop liền mạch ngay cả khi server khởi động lại.
- **Kỹ năng nghiệp vụ chuẩn hóa (`/skills/`)**:
  - `bang-ma-buu-chinh-vung-cuoc`: 3 vùng cước (Vùng 1: Nội tỉnh; Vùng 2: Nội miền; Vùng 3: Liên miền) và chuẩn mã bưu chính quốc gia 5 số.
  - `quy-dinh-hang-cong-kenh`: Công thức quy đổi thể tích cồng kềnh: $\text{Khối lượng quy đổi (kg)} = (\text{Dài} \times \text{Rộng} \times \text{Cao}) / 6000$ (cm).
  - `quy-trinh-khieu-nai-boi-thuong`: Thời hiệu khiếu nại (06 tháng nội địa, 12 tháng quốc tế), SLA giải quyết 20 ngày, quy chuẩn bồi thường 100% khai giá và 04 lần cước không khai giá.

---

## 5. Dữ liệu và Pipeline RAG

- **Định dạng hỗ trợ**:
  - `.txt`: Tách theo đoạn/dòng ngữ nghĩa.
  - `.docx`: Giữ nguyên cấu trúc bảng biểu kèm tiêu đề cột.
  - `.pdf`: Đọc qua `pypdf` bảo toàn văn bản theo trang.
- **Mô hình nhúng & Reranker**:
  - Vector Embedding: **BGE-M3** đa ngôn ngữ phục vụ nhúng ngữ nghĩa chiều sâu (`https://ai.vnpost.vn/vllm-bge-m3/v1/embeddings`).
  - Lexical Search: **BM25Plus** đã chuẩn hóa tiếng Việt loại bỏ dấu thanh và tách từ.
  - Hợp nhất thứ hạng: **Reciprocal Rank Fusion (RRF)**.
  - Cross-Encoder Reranker: **Qwen3-Reranker-8B** (`https://ai.vnpost.vn/vllm-qwen3-reranker-8b/rerank`) lọc lại Top-K ứng viên có điểm liên quan cao nhất.
- **Bộ nhớ đệm nhúng**: Bảng `embedding_cache` trên PostgreSQL lưu trữ vector đã tính toán, giảm thiểu 100% chi phí tính lại các văn bản lặp lại.

---

## 6. Giao diện Frontend và Trải nghiệm tương tác

Giao diện người dùng được xây dựng trên nền tảng **React 19 + Vite**:
- **Tính năng Hỏi lại / Sửa câu hỏi (Re-ask Prompt)**: Cho phép người dùng chỉnh sửa prompt của bất kỳ câu hỏi nào trong quá khứ. Hệ thống cập nhật Optimistic UI, tự động cắt tỉa các lượt chat phía sau câu hỏi được sửa để giữ cho ngữ cảnh hội thoại luôn nhất quán.
- **Điều khiển bằng giọng nói (Voice STT)**: Thu âm trực tiếp từ trình duyệt qua Web Audio API, nén WAV và gửi lên `/api/stt` để chuyển thành văn bản tức thì.
- **Phát âm thanh phản hồi (Streaming TTS)**: Nhận phản hồi dạng văn bản trước, kết hợp phát audio trực tiếp từ ZeroTTS.
- **Nút tác vụ nhanh (Quick Actions)**: Cung cấp các lối tắt nghiệp vụ tiện dụng (📍 Tìm bưu cục gần tôi, 📦 Tra cứu vận đơn, 💰 Bảng giá cước, 📝 Tạo đơn gửi hàng).

---

## 7. Tài liệu liên quan

- `README.md`: Hướng dẫn cài đặt, cấu hình biến môi trường `.env` và vận hành hệ thống.
- `Mipo báo cáo kỹ thuật Deep Agent, RAG LlamaIndex và TTS.md`: Báo cáo khảo sát kỹ thuật chi tiết nhất (1.300+ dòng) phân tích sâu về Agent Harness, Benchmark và Kiểm toán an toàn.
- `docs/ROUTING_AND_SCALE.md`: Tài liệu kỹ thuật chuyên sâu về thuật toán định tuyến 4 tầng và kịch bản mở rộng 100.000 tài liệu.
- `docs/API.md`: Hợp đồng đặc tả chi tiết toàn bộ các REST endpoints và SSE event streams.