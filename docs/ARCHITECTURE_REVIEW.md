# Đánh giá kiến trúc và điều kiện sẵn sàng

Đánh giá ngày 13/10/2026, đối chiếu `Mipo – Nghiên cứu kiến trúc Deep Agent + RAG + TTS.md`,
`Hướng dẫn cài đặt và chạy.md` và mã nguồn hiện tại.

## Kết luận

Kiến trúc đích là đúng cho Mipo: router đưa câu tra cứu một ý qua Direct RAG; Deep Agent
chỉ điều phối các việc cần nhiều nguồn/phân tích; TTS là hậu xử lý tách khỏi vòng agent.
Mã hiện tại đã hiện thực đúng phần khung này cho pilot nhỏ. Tool calling của LLM, CUDA và
embedding BKAI đã được kiểm tra thật. Nó **chưa sẵn sàng cho 100.000 tài liệu hoặc dữ liệu
phân quyền nội bộ**.

## Phần khớp với kiến trúc

| Yêu cầu | Trạng thái | Hiện thực |
| --- | --- | --- |
| Harness LangChain Deep Agents | Có | `create_deep_agent` ở `app/agents.py`; supervisor quản lý RAG, analyst và writer |
| Chia task và chạy song song | Có | `task` của Deep Agents và `parallel_tasks` chạy các task độc lập bằng `asyncio.gather` |
| RAG DOCX/TXT bằng LlamaIndex | Có | `app/rag.py`: nạp, chunk, vector retrieval, BM25/RRF và rerank cross-encoder; Deep mode cần nguồn luôn prefetch evidence trước supervisor |
| Đường nhanh | Có | `app/router.py` và `app/fast_rag.py` bỏ vòng supervisor cho câu hỏi đơn giản |
| Giọng nói | Có | adapter ZeroTTS, WAV/streaming và chữ được trả trước TTS |
| Embedding GPU tiếng Việt | Đã xác nhận | BKAI bi-encoder dùng CUDA, PyVi word segmentation, 768 chiều và chunk 220/32 |

## Điều kiện chặn và khoảng cách

1. **Quy mô 100.000 tài liệu chưa khớp pilot.** Cấu hình hiện giới hạn 200 tài liệu, 10 triệu
   ký tự/tenant, giữ BM25 và vector index trong RAM, đồng thời rebuild snapshot mỗi khi nạp/xóa.
   Qdrant/pgvector, catalog PostgreSQL và worker ingestion là bắt buộc ở quy mô mục tiêu, không
   chỉ là tối ưu tùy chọn.

2. **SSO/RBAC chưa có.** Hiện có cách ly theo tenant API key. `RunContext.user_id` không được
   lấy từ identity đã xác thực và các trường `user_id`/`is_global` của upload đến từ client.
   Chưa được dùng cho tài liệu mật hay phân quyền phòng ban/cấp bậc. ACL phải được lấy từ SSO,
   lưu ở metadata đáng tin cậy và lọc ngay tại retriever/vector store.

3. **Chất lượng retrieval chưa được chứng minh.** Reranker GPU đã được tích hợp và kiểm tra
   kỹ thuật, nhưng chưa có bộ câu hỏi nghiệp vụ có đáp án/nguồn để chứng minh nó cải thiện kết
   quả VNPost. Tài liệu scan, OCR, PPTX/XLSX, versioning văn bản và queue ingestion là các hạng
   mục sau pilot.

4. **TTS chưa được kiểm tra với endpoint thực.** Adapter và giao diện đã có; `.env` đang để
   `TTS_ENABLED=false` đến khi có endpoint/khóa/voice được xác nhận. Lỗi TTS không làm mất câu
   trả lời chữ.

## Lộ trình đề xuất

1. **Pilot có kiểm soát:** DOCX/TXT, một tenant, tối đa vài trăm file; tạo 100–200 câu hỏi gán
   nguồn; đo Recall@K/MRR và p50/p95 cho fast/deep/TTS.
2. **Sẵn sàng nội bộ:** SSO, ACL tài liệu, audit log, Qdrant/pgvector, PostgreSQL/Redis,
   ingestion jobs, OCR/bảng biểu và reranker được chứng minh bằng evaluation.
3. **Mở rộng harness:** checkpointer bền vững, trạng thái task/queue, quan sát trace–chi phí,
   policy cho tool có tác động, phê duyệt người dùng trước action, và agent chuyên môn theo
   domain (nghiệp vụ, cước, khiếu nại, văn bản pháp quy).

## Hướng phát triển Deep Agent cần chốt trước

- Chỉ đọc/tra cứu trước; các agent gửi email, tạo phiếu, sửa dữ liệu phải là action có policy,
  idempotency key, audit trail và bước duyệt của người dùng.
- Dùng graph xác định (LangGraph) cho các quy trình bắt buộc/nhạy cảm; dùng Deep Agent cho nhiệm
  vụ mở cần lập kế hoạch. Không để model tự chọn hành động nghiệp vụ không hồi phục.
- Thêm agent kiểm chứng nguồn cho câu trả lời có hậu quả lớn: kiểm tra từng claim với excerpt,
  phát hiện văn bản hết hiệu lực/mâu thuẫn rồi chuyển người phụ trách khi thiếu bằng chứng.
- Với tác vụ dài, tách dispatch/execution/synthesis bằng hàng đợi và lưu task state; không giữ
  request HTTP cho OCR hoặc nhiều tài liệu lớn.
