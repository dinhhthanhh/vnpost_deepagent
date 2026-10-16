# Đánh giá kiến trúc và điều kiện sẵn sàng

Đánh giá cập nhật ngày 16/10/2026, đối chiếu `Mipo báo cáo kỹ thuật Deep Agent, RAG LlamaIndex và TTS.md`, `README.md` và mã nguồn thực tế của hệ thống.

## Kết luận

Kiến trúc 4 tầng định tuyến là tối ưu cho Mipo: Router phân luồng câu hỏi tra cứu một ý qua Fast RAG; Deep Agent đóng vai trò điều phối viên đa bước chỉ kích hoạt khi câu hỏi phức tạp, so sánh hoặc đa tác vụ; ZeroTTS là bước hậu xử lý tách rời khỏi vòng lặp suy luận của agent.

Hệ thống đã hoàn thiện toàn bộ khung kiến trúc, tích hợp đầy đủ công cụ nghiệp vụ VNPost, bộ kỹ năng `/skills/`, checkpointer SQLite bất đồng bộ và cơ chế nạp bằng chứng bắt buộc. Hệ thống đã được **chạy đo đạc benchmark thực tế trên mô hình `gemini-2.5-flash` kết hợp mô hình nhúng tiếng Việt `bkai-foundation-models/vietnamese-bi-encoder`**, đạt độ trễ trung vị P50 toàn hệ thống là **2.27 giây** (vượt chỉ tiêu thời gian thực dưới 5 giây của bài toán).

Hệ thống hiện tại sẵn sàng cho giai đoạn Pilot doanh nghiệp và cần các bước mở rộng hạ tầng (Vector DB ngoài, SSO/RBAC) khi nâng quy mô lên trên 100.000 tài liệu hoặc phân quyền phòng ban bảo mật cao.

## Phần khớp với kiến trúc

| Yêu cầu kỹ thuật | Trạng thái | Hiện thực trong mã nguồn |
| --- | :---: | --- |
| **Harness LangChain Deep Agents** | Hoàn thành | `create_deep_agent` (`deepagents==0.7.24`) trong `app/agents.py`; Supervisor (`vnpost-supervisor`) điều phối **5 Sub-agent chuyên biệt**: `rag-agent`, `analyst-agent`, `tracking-agent`, `post-office-agent`, `writer-agent`. Supervisor được trang bị 3 công cụ trực tiếp: `calculate_date`, `track_item`, `lookup_post_office`. |
| **Chia task và chạy song song** | Hoàn thành | Cơ chế gọi `task(subagent_type, description)` native của Deep Agents gom đợt và thực thi song song theo `max_concurrency = 3`. Tiện ích `parallel_tasks` cài đặt sẵn qua `asyncio.gather` làm phương án bổ trợ. |
| **RAG Đa định dạng bằng LlamaIndex** | Hoàn thành | `app/rag.py`: nạp và bóc tách tài liệu **DOCX** (bảo toàn bảng biểu), **TXT/Markdown** và **PDF** (`pypdf` phân trang `Trang i`). Truy xuất lai Hybrid (Vector LlamaIndex + BM25Plus), hợp nhất thứ hạng RRF và Cross-Encoder Reranker tùy chọn. Nạp bằng chứng bắt buộc (`prefetched_evidence`) trước khi Supervisor chạy. |
| **Đường tắt & Định tuyến nhanh** | Hoàn thành | `app/fastpath.py` (Tầng 0: 0 gọi LLM cho chào hỏi và AST Calculator), `app/router.py` duyệt 9 luật ưu tiên bằng Regex `app/signals.py` (< 5 ms) và `app/fast_rag.py` (Tầng 1: 1 lần RAG + 1 lượt LLM). |
| **Giọng nói ZeroTTS** | Hoàn thành | Lớp `ZeroTTS` (`app/tts.py`), hỗ trợ 4 endpoint (`/tts`, `/v1/audio/speech`, `/tts/stream`, `/voices`), làm sạch văn bản `spoken_text`, 2 chế độ phát giọng (WAV trọn và Streaming SSE); kết quả chữ được bảo vệ tuyệt đối khi TTS gặp sự cố mạng. |
| **Embedding GPU tiếng Việt** | Đã xác nhận | `bkai-foundation-models/vietnamese-bi-encoder` (PhoBERT bi-encoder 768 chiều, chạy CUDA/CPU qua `pyvi`), bộ nhớ đệm `CachedEmbedding` 2 tầng (SQLite cho tài liệu, RAM LRU cho câu hỏi). Cấu hình chunk chuẩn: **`CHUNK_SIZE = 256`** và **`CHUNK_OVERLAP = 64`**. |
| **Lưu vết trạng thái (Checkpointer)** | Hoàn thành | `PersistentSqliteCheckpointer` lưu trạng thái đồ thị bất đồng bộ vào `checkpoints.sqlite3` với thread ID `{tenant}:{session}:{request}`, bật mặc định (`CHECKPOINTER_ENABLED=true`). |

## Điều kiện chặn và khoảng cách khi mở rộng Production

1. **Quy mô 100.000 tài liệu cần dịch chuyển sang Vector DB ngoài:**
   Cấu hình Pilot hiện tại lưu giữ snapshot chỉ mục và BM25 trong bộ nhớ RAM (được bảo vệ bằng cơ chế Snapshot nguyên tử `os.replace` và giới hạn an toàn 200 file / 10 triệu ký tự mỗi tenant). Khi đưa vào vận hành thực tế quy mô 100.000 tài liệu trên Kubernetes, cần chuyển đổi sang Vector Database chuyên dụng (Qdrant / Milvus / pgvector) kết hợp worker Ingestion chạy nền độc lập như đã quy hoạch trong `docs/ROUTING_AND_SCALE.md`.

2. **Phân quyền người dùng & SSO (RBAC):**
   Hiện tại hệ thống phân lập dữ liệu chặt chẽ theo `X-API-Key` giữa các tenant. Với người dùng nội bộ, trường `user_id` và `is_global` hiện phụ thuộc vào payload upload. Cần tích hợp với cổng SSO tập trung của VNPost (OpenID Connect / OAuth2) để cấp phát Access Control List (ACL) xác thực cho từng tài liệu và lọc trực tiếp tại bước truy xuất vector.

3. **Gán nhãn nghiệp vụ mở rộng để đo Recall@K / MRR:**
   Các bài kiểm thử kỹ thuật và benchmark trực tiếp với `gemini-2.5-flash` đã xác nhận hệ thống hoàn thành 100% các ca kiểm thử với độ trễ P50 2.27s. Để tối ưu hóa thêm mô hình Reranker `bge-reranker-v2-m3` cho tập dữ liệu VNPost, cần xây dựng bộ 100–200 câu hỏi nghiệp vụ chuẩn có gán nhãn đáp án và chạy đánh giá tự động qua `scripts/evaluate_retrieval.py`.

4. **Trạng thái cấu hình ZeroTTS:**
   File cấu hình `.env` hiện tại đã đặt **`TTS_ENABLED=true`** với giọng `maichi` và chế độ `standard`. Hệ thống đã sẵn sàng script `scripts/check_services.py --live --tts` để kiểm tra kết nối tới máy chủ ZeroTTS VNPost (`https://ai.vnpost.vn/zero-tts`).

## Lộ trình đề xuất

1. **Triển khai Pilot (Hiện tại):**
   - Vận hành với tài liệu DOCX, TXT, PDF nghiệp vụ VNPost;
   - Sử dụng định tuyến 4 tầng thích ứng (`auto`), Fast RAG và Deep Agent đa bước;
   - Đo đạc độ trễ và tỷ lệ giải quyết câu hỏi thực tế (đã xác nhận P50 2.27s trên Gemini 2.5 Flash).
2. **Sẵn sàng môi trường Enterprise:**
   - Kết nối hệ thống SSO nội bộ VNPost, bổ sung ACL phòng ban cho từng tài liệu;
   - Chuyển đổi Ingestion sang hàng đợi Celery/Redis worker bất đồng bộ;
   - Tích hợp Vector Database phân tán (Qdrant/pgvector) thay thế bộ nhớ RAM cục bộ.
3. **Mở rộng năng lực Deep Agent:**
   - Bổ sung các Sub-agent hành động nghiệp vụ (tạo mã đơn hàng, ghi nhận khiếu nại) có kèm cơ chế duyệt (human-in-the-loop) và khóa an toàn (idempotency key);
   - Tích hợp thêm module nhận dạng giọng nói (ASR) độc lập để hỗ trợ đàm thoại trực tiếp qua micro.

## Hướng phát triển Deep Agent cần chốt trước

- **Nguyên tắc an toàn:** Deep Agent hiện tại tập trung hoàn toàn vào tra cứu, tổng hợp, tính toán và đối chiếu bằng chứng (Read-Only). Các hành động có tác động dữ liệu (sửa đổi, tạo mới, hủy đơn) bắt buộc phải qua bước xác nhận của người dùng.
- **Phân định rõ Graph xác định và Deep Agent mở:** Dùng LangGraph xác định cho các quy trình bưu chính chuẩn hóa có sẵn; dùng Deep Agent cho các yêu cầu đối chiếu đa bước, phân tích mâu thuẫn hoặc giải quyết câu hỏi phức tạp.
- **Xác thực trích dẫn nguồn nghiêm ngặt:** Duy trì cơ chế 4 bước của `validate_answer()`, bảo đảm mọi phát biểu số liệu và chính sách bồi thường đều có bằng chứng trích dẫn `[S#]` hỗ trợ từ tài liệu chính thức.
