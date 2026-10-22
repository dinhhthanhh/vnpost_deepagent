---
name: uoc-tinh-cuoc-phi
description: Kỹ năng tính toán cước phí chuyển phát EMS và Bưu kiện dựa trên khối lượng tính cước và 3 vùng địa lý của VNPost.
version: 1.0.0
author: Ban Kinh Doanh & Dịch Vụ VNPost
triggers:
  - giá cước gửi hàng
  - chi phí vận chuyển
  - gửi hàng hết bao nhiêu tiền
  - tính cước bưu điện
allowed_tools:
  - calculate
  - calculate_date
---

# KỸ NĂNG TÍNH TOÁN CƯỚC PHÍ BƯU CHÍNH VNPOST

## 1. Nguyên tắc Xác định 3 Vùng Cước
- **Vùng 1 (Nội tỉnh):** Địa chỉ người gửi và người nhận cùng nằm trong một tỉnh/thành phố trực thuộc Trung ương.
- **Vùng 2 (Nội miền):** Địa chỉ người gửi và người nhận thuộc hai tỉnh/thành phố khác nhau nhưng trong cùng một miền địa lý:
  - *Miền Bắc:* Từ Hà Giang đến Ninh Bình (bao gồm Hà Nội, Hải Phòng, Quảng Ninh...).
  - *Miền Trung:* Từ Thanh Hóa đến Bình Định (bao gồm Nghệ An, Hà Tĩnh, Đà Nẵng, Huế...).
  - *Miền Nam:* Từ Phú Yên đến Cà Mau (bao gồm TP. Hồ Chí Minh, Bình Dương, Cần Thơ...).
- **Vùng 3 (Liên miền):** Địa chỉ người gửi và người nhận thuộc hai miền địa lý khác nhau (ví dụ: Hà Nội gửi đi TP.HCM, hoặc Đà Nẵng gửi đi Cần Thơ).

## 2. Bảng Biểu Cước Cơ Bản Dịch vụ EMS (Mô phỏng Hệ thống)
| Phân vùng | Khối lượng nấc đầu (đến 500g) | Nấc khối lượng tiếp theo (mỗi 500g) |
| :--- | :--- | :--- |
| **Vùng 1 (Nội tỉnh)** | 22.000 VNĐ | +3.500 VNĐ / 500g |
| **Vùng 2 (Nội miền)** | 32.000 VNĐ | +5.500 VNĐ / 500g |
| **Vùng 3 (Liên miền)** | 45.000 VNĐ | +8.500 VNĐ / 500g |

## 3. Khối lượng Tính cước (Chargeable Weight)
Khối lượng tính cước là giá trị lớn hơn giữa:
- **Khối lượng thực tế:** Đo bằng cân (đơn vị kg).
- **Khối lượng quy đổi cồng kềnh:** `(Chiều dài cm x Chiều rộng cm x Chiều cao cm) / 6000` (đơn vị kg).
