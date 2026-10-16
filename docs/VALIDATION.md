# Báo cáo Kiểm thử và Đánh giá Bộ Mã Nguồn (Validation Report)

Ngày kiểm tra: 16/10/2026. Môi trường thực nghiệm: Windows 11 (PowerShell) và Linux; Python 3.11 / Python 3.12.

| Hạng mục kiểm tra | Kết quả đạt được | Ghi chú kỹ thuật |
|---|:---:|---|
| **Pytest backend** | **141 passed** (86.98s) | Kiểm thử bao phủ toàn bộ: Fastpath, AST Calculator, Router 4 tầng, Supervisor Deep Agent, 5 Sub-agent, Checkpointer SQLite, LlamaIndex RAG, Terminology và ZeroTTS |
| **Node frontend / WAV / SSE** | **11 passed** | Kiểm tra phân tích chunk âm thanh WAV (1, 2, 7, 13, 44, 1000 byte), header JUNK, stereo/mono, 16kHz/22.05kHz và SSE buffer |
| **Ruff Code Quality** | **All checks passed** | Tuân thủ định dạng PEP8 và quy chuẩn code sạch |
| **Dependency consistency** | **pip check OK** | Không có xung đột phiên bản thư viện |
| **Vite production build** | **Thành công** | Đóng gói `frontend/dist` hoàn chỉnh phục vụ cùng origin |
| **Browser desktop và mobile** | **Đạt chuẩn** | Đã thử nghiệm giao diện desktop và mobile (viewport 390px), hiển thị trích dẫn [S#], âm thanh ZeroTTS, không tràn ngang |
| **Live Benchmark với LLM thật** | **Hoàn thành 100% (8/8)** | Chạy đo đạc thực tế trên `gemini-2.5-flash` và `vietnamese-bi-encoder`: P50 2.27s, Deep 3.55s, Tầng 0 shortcut 31ms |

## Phạm vi kiểm thử backend

Các kiểm thử tự động khởi tạo trực tiếp lớp `AgentHarness` (`create_deep_agent`), các đồ thị LangChain/LangGraph và chỉ mục `VectorStoreIndex` / `KnowledgeBase` LlamaIndex thật:

- **Điều phối song song:** Xác nhận cả cơ chế native `task` của Deep Agents và `parallel_tasks` kích hoạt các Sub-agent chạy đồng thời với độ trễ bắt đầu chỉ cách nhau 3–4 ms (`task_start` chồng thời gian).
- **Kiểm soát ngân sách & Timeout:** Kiểm tra `max_parallel_subagents = 3`, `max_delegated_tasks = 8`, giới hạn 12 bước đồ thị, hủy request khi timeout 35s và cô lập lỗi an toàn qua JSON `task_failed`.
- **RAG Đa định dạng & Bảng biểu:** Kiểm thử bóc tách cấu trúc DOCX (lặp lại tên cột ở từng hàng), TXT và PDF có text layer (`pypdf`); kiểm tra chống tấn công đường dẫn và file vượt giới hạn dung lượng.
- **Atomic Snapshot:** Đảm bảo quá trình nạp/xóa tài liệu tạo snapshot mới nguyên tử bằng `os.replace` sang `current.json`, không làm gián đoạn các truy vấn đang đọc trên RAM.
- **Thẩm định trích dẫn (Citation Gate):** Kiểm tra chặn mã nguồn giả mạo (`invalid_citation`), xử lý `[[NO_EVIDENCE]]` và đối chiếu từ khóa mức câu (Claim $\leftrightarrow$ Excerpt).
- **Bộ tính toán số học & Ngày tháng:** `calculator.py` tính toán đúng biểu thức AST chuẩn quy ước Việt Nam và từ chối mã độc; `calculate_date` tính toán chính xác theo múi giờ UTC+7.
- **ZeroTTS Adapter:** Kiểm thử kết nối 4 endpoint chuẩn (`/tts`, `/v1/audio/speech`, `/tts/stream`, `/voices`), kiểm tra header PCM 16-bit và cơ chế bảo vệ luôn phát sự kiện chữ trước TTS.

## Phạm vi kiểm thử frontend

11 bài test Node.js bao gồm:
- Xử lý các chunk âm thanh WAV bị phân mảnh;
- Header chứa khối JUNK;
- Mono và Stereo;
- Tần số lấy mẫu 16 kHz và 22.05 kHz;
- Phát hiện dữ liệu bị cắt cụt và codec không hỗ trợ;
- Phân giải khung SSE JSON truyền phát từng phần.

Giao diện React được kiểm thử trực tiếp trên trình duyệt ở cả chế độ máy tính để bàn và thiết bị di động (viewport 390 px), đảm bảo lịch sử hội thoại được lưu giữ và bảng biểu hiển thị rõ ràng.

## Kết quả đo kiểm thực tế trên môi trường Live (Live Benchmark)

Hệ thống đã thực hiện đo đạc benchmark thực tế trên endpoint LLM `gemini-2.5-flash` kết hợp mô hình nhúng `bkai-foundation-models/vietnamese-bi-encoder` và kho tri thức VNPost (kết quả lưu tại `reports/architecture_metrics.json` và `reports/architecture_comparison.json`, ngày 16/10/2026):

1. **Độ trễ trung vị (P50):**
   - Tầng 0 (Đường tắt cục bộ - Chào hỏi / Tính toán): **31 ms** (0 token LLM, 0 RAG).
   - Tầng 1 (Fast RAG): **2.266 ms (~2.27s)**.
   - Tầng 2/3 (Deep Agent): **3.547 ms (~3.55s)**.
   - Toàn hệ thống (Overall P50): **2.266 ms (~2.27s)**.
2. **Tỷ lệ thành công:** **8/8 (100%)**, 0 lỗi, 0 timeout.
3. **Đối sánh 3 chế độ (`auto`, `fast`, `deep`):** Cả 3 chế độ đều đạt độ trễ trung vị dưới 2.5 giây, trong đó chế độ `auto` đạt hiệu quả tối ưu nhất về mặt tài nguyên và chất lượng câu trả lời.

## Phiên bản thư viện chính

- `deepagents`: 0.7.24
- `langchain`: 1.4.5
- `langchain-openai`: 1.7.1
- `llama-index-core`: 0.14.25
- `fastapi`: 0.143.0
- `httpx`: 0.28.1
- `pypdf`: 5.3.0
- `sentence-transformers`: 3.4.1
- `pyvi`: 0.1.1
