# API chatbot

OpenAPI tương tác: `http://127.0.0.1:8080/docs`. Tất cả endpoint dữ liệu dùng header `X-API-Key`; tenant được lấy từ cấu hình server. Demo không xác thực chỉ cho phép peer loopback. Endpoint health chỉ báo trạng thái process, không khẳng định upstream sẵn sàng.

| Phương thức | Endpoint | Chức năng |
|---|---|---|
| GET | `/api/health` | Liveness và chế độ hiện tại |
| POST | `/api/documents` | Multipart `file`, lập chỉ mục DOCX/TXT |
| GET | `/api/documents` | Danh sách file, chunk, revision |
| DELETE | `/api/documents/{sha256}` | Xóa file của tenant, rebuild snapshot |
| POST | `/api/chat` | Trả JSON hoàn chỉnh; có thể kèm audio URL |
| POST | `/api/chat/stream` | SSE tiến trình, answer trước TTS, done sau TTS |
| GET | `/api/sessions/{uuid}` | Hội thoại và bản sao nguồn của phiên |
| GET | `/api/replies/{request_id}` | Kết quả lần trả lời đã lưu |
| GET | `/api/tts/voices` | Danh sách giọng ZeroTTS |
| POST | `/api/tts` | Tạo WAV, trả URL được bảo vệ |
| POST | `/api/tts/stream` | Proxy streaming WAV từ ZeroTTS |
| GET | `/api/audio/{id}` | Tải WAV; kiểm tra tenant và TTL |

## Ví dụ chat

```bash
curl http://127.0.0.1:8080/api/chat \
  -H 'X-API-Key: YOUR-CHATBOT-KEY' \
  -H 'Content-Type: application/json' \
  -d '{"message":"So sánh hai quy trình trong tài liệu và trích nguồn","grounded":true,"voice":true,"voice_name":"maichi"}'
```

`session_id` là UUID; bỏ trống để tạo phiên mới. `grounded=true` yêu cầu nguồn đối với nội dung tài liệu. `grounded=false` cho phép hỏi chung/soạn nội dung/tính toán từ dữ kiện đã cho. `voice` điều khiển tạo âm thanh; TTS lỗi được đưa vào `warnings`, vẫn giữ `answer`.

```json
{
  "request_id": "generated-id",
  "session_id": "generated-uuid",
  "answer": "Nội dung trả lời [S1].",
  "sources": [{
    "citation_id": "S1", "document_id": "sha256",
    "filename": "quy_trinh.docx", "location": "Mục A; bảng 1, hàng 2",
    "chunk_id": "sha256", "excerpt": "Nội dung nguồn",
    "retrieval_score": 0.032
  }],
  "grounding_status": "cited",
  "demo": false,
  "elapsed_ms": 0,
  "events": [],
  "audio_url": "/api/audio/generated-id",
  "warnings": []
}
```

Ví dụ schema trên không phải một kết quả thực nghiệm. `retrieval_score` là điểm hợp nhất RRF, không phải độ tin cậy. Các trạng thái nguồn: `cited` là đã kiểm tra mã nguồn tồn tại; `no_evidence` thiếu nguồn; `invalid_citation` bị chặn mã không hợp lệ; `unverified` trả lời chung hoặc lời chào.

## SSE

Dùng `fetch` POST + `ReadableStream`, vì cần body JSON và header khóa. EventSource chuẩn không gửi được các tham số đó. Các event gồm `start`, `planning`, `task_start`, `task_end`, `task_rejected`, `retrieval`, `answer`, `speech_start`, `speech_ready`, `speech_error`, `done`, `error`.

```text
event: task_start
data: {"type":"task_start","agent":"rag-agent","elapsed_ms":100}

event: answer
data: {"type":"answer","data":{...ChatResponse...}}

event: done
data: {"type":"done","data":{...ChatResponse...}}
```

Các thời gian trong ví dụ chỉ minh họa định dạng. Hủy kết nối sẽ hủy coroutine agent; một tác vụ CPU/index đang chạy trong worker thread có thể vẫn kết thúc. Nguồn của các request đang chạy là snapshot; việc xóa tài liệu không thu hồi ngay nguồn đã đọc trong một request trước đó.

## Ánh xạ ZeroTTS

| Thao tác chatbot | API từ Postman | Payload |
|---|---|---|
| WAV chuẩn | `POST /zero-tts/tts` | `text`, `voice`, `cfg_scale`, `audio_temperature` |
| OpenAI speech | `POST /zero-tts/v1/audio/speech` | `model=ZeroTTS`, `input`, `voice`, `response_format=wav`, `speed=1.0` |
| Streaming | `POST /zero-tts/tts/stream` | Payload WAV chuẩn |
| Danh sách giọng | `GET /zero-tts/voices` | Không body |

URL gốc được giữ đủ tiền tố `/zero-tts`; HTTP client gọi đường dẫn tương đối. Không nhận URL TTS từ client. Khóa Bearer, nếu có, được thêm tại server. Không retry POST TTS để tránh lặp synthesis sau một kết quả không rõ trạng thái. Voice-pack upload/delete của Postman thuộc quản trị TTS và không được đưa thành tool của chatbot.

Âm thanh được tạo từ nội dung đã bỏ Markdown/citation/URL, giới hạn 5.000 ký tự mặc định. Câu trả lời dài hơn cần yêu cầu tóm tắt để nghe; backend không tự cắt mất nội dung. URL audio yêu cầu cùng `X-API-Key`; frontend fetch thành Blob, không đưa khóa vào query string. TTL mặc định 1 giờ; file quá hạn được dọn khi có synthesis tiếp theo.
