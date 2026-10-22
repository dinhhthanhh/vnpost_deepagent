# PLUGIN: VNPost Logistics Services

- **Plugin Name:** `vnpost_logistics`
- **Version:** 1.0.0
- **Author:** Ban Bưu chính Chuyển phát VNPost
- **Mô tả:** Plugin đóng gói toàn bộ dịch vụ logistics cốt lõi của VNPost bao gồm: tra cứu hành trình vận đơn UPU (BCCP), tính cước chuyển phát nhanh EMS / Bưu kiện theo 3 vùng cước, tính khối lượng quy đổi cồng kềnh chia 6000, và quy trình tiếp nhận đơn hàng thu gom tận nơi (HITL 2-phase commit).

## Các Sub-agent & Tools Liên kết:
1. **tracking-agent:** `track_item`
2. **booking-agent:** `create_draft_booking`, `update_draft_booking`, `confirm_booking`, `cancel_draft_booking`, `cancel_booking`, `list_my_orders`
3. **analyst-agent:** `calculate`, `calculate_date`

## Các Kỹ năng (Skills) Tích hợp:
- `skills/tra-cuu-buu-gui/SKILL.md`
- `skills/uoc-tinh-cuoc-phi/SKILL.md`
- `skills/quy-chuan-dong-goi/SKILL.md`
