# PLUGIN: VNPost Customer Care & Public Network

- **Plugin Name:** `vnpost_customer_care`
- **Version:** 1.0.0
- **Author:** Ban Chăm sóc Khách hàng & Công nghệ Thông tin VNPost
- **Mô tả:** Plugin đóng gói các dịch vụ hỗ trợ khách hàng và mạng lưới bưu chính quốc gia: tra cứu bưu cục gần nhất theo định vị GPS, tra cứu mã bưu chính quốc gia Vpostcode 5 chữ số, tra cứu tri thức văn bản quy định (RAG LlamaIndex), và quy trình tiếp nhận giải quyết khiếu nại bồi thường theo SLA 20 ngày.

## Các Sub-agent & Tools Liên kết:
1. **post-office-agent:** `lookup_post_office`, `find_nearest_post_office`
2. **complaint-agent:** `create_draft_complaint`, `update_draft_complaint`, `confirm_complaint`, `cancel_draft_complaint`, `cancel_complaint`, `list_my_orders`
3. **rag-agent:** `search_documents`, `read_file`
4. **writer-agent:** `read_file`

## Các Kỹ năng (Skills) Tích hợp:
- `skills/ma_buu_chinh_vpostcode/SKILL.md`
- `skills/boi_thuong_khieu_nai/SKILL.md`
