# Tài liệu API - VNPost Deep Agent Chatbot

Tài liệu đặc tả toàn diện hệ thống RESTful API và Server-Sent Events (SSE) cho Chatbot thông minh VNPost Deep Agent tích hợp tìm kiếm RAG và tổng hợp giọng nói tiếng Việt ZeroTTS.

- **Swagger / OpenAPI UI:** `http://127.0.0.1:8000/docs` (môi trường Local) hoặc `http://127.0.0.1:8080/docs` (Docker).
- **Mã hóa & Chuẩn hóa:** Toàn bộ request/response sử dụng định dạng JSON, bảng mã UTF-8 chuẩn NFC tiếng Việt.
- **Xác thực:** Mọi endpoint dữ liệu yêu cầu header `X-API-Key` (hoặc Session Token động). Server đối chiếu key trong `API_KEYS_JSON` để gán vào tenant tương ứng (`RunContext`). Môi trường local cho phép kết nối loopback ẩn danh nếu bật `ALLOW_ANONYMOUS_DEMO=true`.

---

## 1. Bảng tổng hợp các Endpoint

| Phương thức | Đường dẫn | Chức năng chính | Quyền hạn |
|---|---|---|---|
| `GET` | `/api/health` | Kiểm tra trạng thái liveness, router, embedding, TTS | Công khai |
| `POST` | `/api/chat` | Gửi câu hỏi, nhận JSON phản hồi hoàn chỉnh | Tenant User |
| `POST` | `/api/chat/stream` | Gửi câu hỏi, stream sự kiện tiến trình và đáp án qua SSE | Tenant User |
| `GET` | `/api/documents` | Liệt kê danh sách tài liệu trong kho tri thức của tenant | Tenant User |
| `POST` | `/api/documents` | Tải lên tài liệu (TXT, DOCX, PDF) dạng Multipart Form | Tenant User |
| `POST` | `/api/documents/verified` | Nạp tài liệu nguồn tin cậy công khai (Official Public) | Source Admin |
| `POST` | `/api/documents/s3` | Nạp tài liệu tự động từ S3 Presigned URL hoặc Bucket/Key | Tenant User |
| `DELETE` | `/api/documents/{document_id}` | Xóa tài liệu khỏi kho tri thức và dựng lại snapshot | Tenant User |
| `GET` | `/api/sessions` | Lấy danh sách các phiên hội thoại gần nhất | Tenant User |
| `GET` | `/api/sessions/{session_id}` | Xem chi tiết lịch sử tin nhắn và nguồn của phiên | Tenant User |
| `DELETE` | `/api/sessions/{session_id}` | Xóa toàn bộ lịch sử một phiên hội thoại | Tenant User |
| `GET` | `/api/replies/{request_id}` | Lấy lại câu trả lời và nguồn đã lưu theo mã request | Tenant User |
| `GET` | `/api/tts/voices` | Lấy danh sách giọng đọc khả dụng từ ZeroTTS | Công khai / Tenant |
| `POST` | `/api/tts` | Tổng hợp giọng nói từ văn bản (tạo file WAV lưu tạm) | Tenant User |
| `POST` | `/api/tts/stream` | Proxy truyền phát luồng âm thanh WAV trực tiếp | Tenant User |
| `GET` | `/api/audio/{audio_id}` | Tải file âm thanh WAV theo phiên và kiểm tra TTL | Tenant User |

---

## 2. Chi tiết các Endpoint Nghiệp vụ

### 2.1. Tra cứu & Hội thoại (`POST /api/chat`)

Xử lý câu hỏi của người dùng qua hệ thống định tuyến thông minh (Fastpath $\rightarrow$ Fast RAG $\rightarrow$ Deep Agent).

**Headers:**
- `Content-Type: application/json`
- `X-API-Key: <tenant-api-key>`

**Request Body (`ChatRequest`):**
```json
{
  "message": "Cước bưu phẩm gửi nhanh EMS từ Hà Nội đi Đà Nẵng 500g là bao nhiêu?",
  "session_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
  "mode": "auto",
  "grounded": true,
  "voice": false,
  "stream_voice": false,
  "voice_name": "maichi",
  "image": null
}
```

**Mô tả tham số:**
- `message` *(bắt buộc, str, 1--12.000 ký tự)*: Nội dung câu hỏi của người dùng.
- `session_id` *(tùy chọn, UUID)*: Mã phiên hội thoại. Nếu để `null`, server tự sinh phiên mới.
- `mode` *(tùy chọn, `auto` | `fast` | `deep`, mặc định `auto`)*:
  - `auto`: Tự động nhận diện (Fastpath chitchat/toán $\rightarrow$ Fast RAG $\rightarrow$ Deep Agent nếu phức tạp/so sánh).
  - `fast`: Ép buộc sử dụng tuyến Fast RAG (trả lời siêu tốc 1--2 giây).
  - `deep`: Ép buộc sử dụng tuyến Deep Agent đa bước với Supervisor và các Sub-agent.
- `grounded` *(tùy chọn, bool, mặc định `true`)*: Yêu cầu câu trả lời phải trích dẫn nguồn từ tài liệu. Khi `false`, cho phép đàm thoại tự do, câu đố, tính toán logic.
- `voice` *(tùy chọn, bool, mặc định `false`)*: Tự động tổng hợp file âm thanh WAV qua ZeroTTS sau khi sinh xong câu trả lời.
- `stream_voice` *(tùy chọn, bool, mặc định `false`)*: Cho phép client tự phân đoạn câu trả lời để gọi stream TTS.
- `voice_name` *(tùy chọn, str)*: Tên giọng đọc mong muốn (ví dụ: `maichi`, `naman`).
- `image` *(tùy chọn, str)*: Dữ liệu ảnh dạng Data URL (`data:image/...`) hoặc URL công khai HTTP/HTTPS (đã được bảo vệ chống SSRF).

**Response Model (`ChatResponse` - HTTP 200):**
```json
{
  "request_id": "req-1792049246114-abc",
  "session_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
  "answer": "Theo bảng cước dịch vụ chuyển phát nhanh EMS trong nước, cước gửi bưu gửi 500g từ Hà Nội đi Đà Nẵng là 28.500 đồng [S1].",
  "sources": [
    {
      "citation_id": "S1",
      "document_id": "8f4a2b1c9e...",
      "filename": "bang_cuoc_ems_2025.docx",
      "location": "Trang 3, Bảng cước vùng 2",
      "chunk_id": "chunk-1029",
      "excerpt": "Cước EMS liên tỉnh vùng 2 (Hà Nội - Đà Nẵng): nấc khối lượng đến 500g là 28.500 đồng.",
      "retrieval_score": 0.032145,
      "is_global": true,
      "authority": "official_public",
      "source_url": "https://vietnampost.vn/bang-cuoc-ems",
      "issuer": "Vietnam Post"
    }
  ],
  "grounding_status": "cited",
  "route": "fast",
  "route_reason": "Tra cứu thông tin nghiệp vụ độc lập (Tầng 1 - Mặc định)",
  "elapsed_ms": 1120,
  "events": [],
  "audio_url": "/api/audio/req-1792049246114-abc",
  "warnings": []
}
```

**Ý nghĩa các trường trạng thái:**
- `grounding_status`:
  - `cited`: Câu trả lời có trích dẫn nguồn hợp lệ và được kiểm chứng ngữ cảnh.
  - `computed`: Kết quả suy luận logic thời gian hoặc tính toán số học chính xác.
  - `no_evidence`: Không tìm thấy tài liệu phù hợp trong hệ thống (trả về thông báo mẫu chuẩn).
  - `invalid_citation`: Bị chặn do sinh mã trích dẫn không có trong danh mục.
  - `unverified`: Câu chào hỏi xã giao hoặc câu trả lời chế độ mở không nguồn.
- `route`: Tuyến xử lý đã chọn: `calculator` (phép tính trực tiếp), `local` (chào hỏi), `fast` (Fast RAG), `fast_fallback` (fallback), hoặc `deep` (Deep Agent).

---

### 2.2. Streaming Sự kiện & Token (`POST /api/chat/stream`)

Phát sự kiện Server-Sent Events (SSE) theo thời gian thực để tạo trải nghiệm tương tác trực quan cho người dùng.

**Headers:**
- `Content-Type: application/json`
- `Accept: text/event-stream`
- `X-API-Key: <tenant-api-key>`

**Các loại sự kiện SSE:**
- `event: start` $\rightarrow$ Khởi tạo yêu cầu với thông tin `request_id`, `session_id`.
- `event: planning` $\rightarrow$ Supervisor lập kế hoạch phân rã nhiệm vụ.
- `event: task_start` / `task_end` $\rightarrow$ Khởi chạy và hoàn tất các sub-agent song song (`rag-agent`, `analyst-agent`, `writer-agent`).
- `event: token` $\rightarrow$ Token văn bản trực tiếp từ Fast RAG (nếu stream).
- `event: answer` $\rightarrow$ Toàn bộ câu trả lời cuối cùng kèm danh sách trích dẫn `sources`.
- `event: speech_ready` $\rightarrow$ Thông báo file âm thanh TTS đã sẵn sàng tại `audio_url`.
- `event: done` $\rightarrow$ Hoàn thành chu trình xử lý request.

---

### 2.3. Nạp tài liệu từ S3 Presigned URL (`POST /api/documents/s3`)

Tải và nạp tài liệu tự động từ S3 Presigned URL hoặc AWS S3 Bucket + Key với cơ chế bảo vệ SSRF nhiều tầng.

**Headers:**
- `Content-Type: application/json`
- `X-API-Key: <tenant-api-key>`

**Request Body (`S3IngestRequest`):**
```json
{
  "url": "https://s3.vnpost.vn/documents/quy_trinh_khieu_nai_2026.pdf?AWSAccessKeyId=...",
  "bucket": null,
  "key": null,
  "filename": "quy_trinh_khieu_nai_2026.pdf",
  "is_global": true,
  "authority": "official_public",
  "source_url": "https://vietnampost.vn/quy-trinh-khieu-nai",
  "issuer": "Tổng công ty Bưu điện Việt Nam",
  "session_id": null,
  "user_id": null
}
```

**Chính sách An toàn thông tin (SSRF Protection):**
- **Chặn dải IP cấm (Fail-closed):** Tự động phân giải DNS và chặn đứng mọi địa chỉ IP thuộc dải nội bộ (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), loopback (`127.0.0.1`, `localhost`), link-local (đặc biệt dịch vụ metadata AWS/GCP/Alibaba: `169.254.169.254`), multicast và IPv6-mapped IPv4.
- **Tắt HTTP Redirect (`follow_redirects=False`):** Ngăn chặn kỹ thuật chuyển hướng 302 từ domain hợp lệ sang mạng nội bộ.
- **Kiểm soát dung lượng luồng:** Tải theo chunk 64KB, kiểm tra header `Content-Length` và ngắt kết nối với mã **HTTP 413** nếu vượt quá `MAX_UPLOAD_BYTES` (mặc định 15MB).
- **Hạn định thời gian (Timeout):** Giới hạn kết nối 10 giây và đọc dữ liệu 30 giây.
- **Danh sách tên miền cho phép (`ALLOWED_S3_DOMAINS`):** Nếu biến môi trường này được cấu hình, chỉ các domain hoặc S3 endpoint nằm trong danh sách (phân tách bởi dấu phẩy) mới được phép nạp.

**Response (HTTP 201 Created):**
```json
{
  "id": "c3d2e1f0...",
  "filename": "quy_trinh_khieu_nai_2026.pdf",
  "chunks": 18,
  "duplicate": false,
  "revision": "4b92af...",
  "authority": "official_public",
  "source_url": "https://vietnampost.vn/quy-trinh-khieu-nai",
  "issuer": "Tổng công ty Bưu điện Việt Nam"
}
```

---

### 2.4. Nạp tài liệu nguồn tin cậy (`POST /api/documents/verified`)

Dành riêng cho quản trị viên gắn nhãn chứng thực bằng chứng chính thức (`official_public`).

**Headers:**
- `X-API-Key: <tenant-api-key>`
- `X-Source-Admin-Key: <trusted-ingest-key>` (Khóa bí mật quản trị viên riêng biệt)

**Form Data:**
- `file`: File nhị phân (DOCX, TXT, PDF có text).
- `source_url`: URL nguồn bài viết gốc trên cổng thông tin VNPost (Bắt buộc phải thuộc các domain cấu hình trong `OFFICIAL_SOURCE_DOMAINS`, mặc định: `vietnampost.vn`).
- `issuer`: Tên cơ quan ban hành (mặc định: `Vietnam Post`).

---

### 2.5. Quản lý kho tài liệu (`/api/documents`)

- **Liệt kê tài liệu (`GET /api/documents`):**
  - Query params: `session_id` (lọc theo phiên), `only_session` (chỉ lấy tài liệu riêng của phiên).
  - Trả về danh sách file, tổng số chunks, kích thước và trạng thái chứng thực `authority`.
- **Xóa tài liệu (`DELETE /api/documents/{document_id}`):**
  - Xóa file gốc khỏi ổ đĩa, loại bỏ vector trong LlamaIndex/BM25 và tạo snapshot mới.

---

### 2.6. Quản lý phiên hội thoại (`/api/sessions`)

- **Danh sách phiên (`GET /api/sessions`):** Trả về danh sách các phiên trò chuyện gần nhất của tenant kèm thời gian cập nhật.
- **Chi tiết phiên (`GET /api/sessions/{session_id}`):** Trả về toàn bộ lịch sử tin nhắn hỏi-đáp và các nguồn trích dẫn đã sử dụng trong phiên.
- **Xóa phiên (`DELETE /api/sessions/{session_id}`):** Xóa toàn bộ lịch sử và tài liệu đính kèm riêng của phiên đó.

---

### 2.7. Tích hợp giọng nói ZeroTTS (`/api/tts/*`)

- **Danh sách giọng (`GET /api/tts/voices`):** Lấy danh sách các giọng đọc tiếng Việt hỗ trợ từ ZeroTTS (ví dụ: `maichi`, `naman`).
- **Tổng hợp giọng nói (`POST /api/tts`):** Nhận văn bản (tối đa 20.000 ký tự), gọi ZeroTTS và trả về đường dẫn `audio_url` dạng `/api/audio/{audio_id}`.
- **Phát trực tiếp (`POST /api/tts/stream`):** Proxy trực tiếp luồng nhị phân WAV (HTTP Chunked Transfer) giúp người dùng nghe giọng nói ngay khi câu trả lời đang sinh.
- **Tải file âm thanh (`GET /api/audio/{audio_id}`):** Tải file âm thanh WAV đã lưu trong thư mục đệm; tự động dọn dẹp theo thời gian sống TTL (mặc định 3600s / 1 giờ).

---

## 3. Mã phản hồi HTTP & Xử lý ngoại lệ

| Mã HTTP | Tên chuẩn | Nguyên nhân và xử lý |
|---|---|---|
| `200` | OK | Xử lý yêu cầu thành công. |
| `201` | Created | Nạp tài liệu hoặc tạo tài nguyên mới thành công. |
| `400` | Bad Request | Dữ liệu đầu vào vi phạm cấu trúc nghiệp vụ hoặc sai định dạng. |
| `401` | Unauthorized | Thiếu header `X-API-Key` hoặc khóa API không tồn tại. |
| `403` | Forbidden | Không có quyền quản trị (ví dụ sai `X-Source-Admin-Key` khi gọi verified ingest). |
| `404` | Not Found | Không tìm thấy phiên hội thoại, tài liệu hoặc file âm thanh. |
| `413` | Payload Too Large | Dung lượng file tải lên vượt quá `MAX_UPLOAD_BYTES` (15MB). |
| `422` | Unprocessable Entity | Dữ liệu không thỏa mãn Pydantic schema hoặc vi phạm bộ lọc SSRF (IP nội bộ, cấm domain). |
| `429` | Too Many Requests | Vượt quá số lượng kết nối đồng thời `MAX_ACTIVE_REQUESTS` của hệ thống. |
| `502` | Bad Gateway | Lỗi kết nối khi gọi upstream LLM, Embedding hoặc ZeroTTS. |

---

## 4. Bộ Kiểm thử Tự động Postman (Automated Test Suite)

Dự án cung cấp trọn bộ kịch bản kiểm thử tự động đạt chuẩn Postman Collection v2.1:
- **Thư mục Collection:** [postman/collections/VNPost Deep Agent API Test Suite/](file:///c:/Users/admin/Downloads/vnpost_deepagent/postman/collections/VNPost%20Deep%20Agent%20API%20Test%20Suite/)
- **Môi trường Local:** [postman/environments/vnpost_local.json](file:///c:/Users/admin/Downloads/vnpost_deepagent/postman/environments/vnpost_local.json)
- **Độ bao phủ:** 16 kịch bản kiểm thử tự động xác nhận mã trạng thái HTTP, schema JSON, logic Fastpath, Fast RAG, Deep Agent, SSRF và vòng đời tài liệu.
