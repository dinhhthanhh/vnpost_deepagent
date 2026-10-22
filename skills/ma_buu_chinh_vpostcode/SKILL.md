---
name: ma_buu_chinh_vpostcode
description: Quy định cấu trúc mã bưu chính quốc gia 5 chữ số Vpostcode và cơ chế định vị địa chỉ bưu chính của VNPost.
version: 1.0.0
author: Trung tâm Công nghệ Thông tin VNPost
triggers:
  - mã bưu điện
  - vpostcode
  - mã zip code việt nam
  - mã bưu chính cấp xã phường
allowed_tools:
  - lookup_post_office
  - find_nearest_post_office
---

# QUY ĐỊNH MÃ BƯU CHÍNH QUỐC GIA (VPOSTCODE)

## 1. Cấu trúc Mã Bưu chính Quốc gia 5 Ký tự số
Từ năm 2018, Việt Nam chính thức chuyển sang sử dụng Mã bưu chính quốc gia gồm **5 chữ số** (thay thế cho hệ thống 6 chữ số cũ):
- **2 chữ số đầu tiên:** Xác định tỉnh/thành phố trực thuộc Trung ương (ví dụ: `10xxx` đến `14xxx` là Hà Nội, `70xxx` đến `74xxx` là TP. Hồ Chí Minh).
- **Chữ số thứ 3 và 4:** Xác định quận/huyện/thị xã hoặc đơn vị hành chính tương đương.
- **Chữ số thứ 5:** Xác định đối tượng gán mã cụ thể: xã/phường/thị trấn, cụm bưu cục hoặc cơ quan tổ chức cấp cao.

## 2. Nền tảng Định vị Bưu chính Vpostcode
Vpostcode là nền tảng mã địa chỉ số kết hợp giữa tọa độ địa lý vệ tinh (GPS) và mã bưu chính quốc gia:
- Cung cấp độ chính xác định vị tới từng nóc nhà và vị trí giao dịch của người dân.
- Bưu cục VNPost sử dụng Vpostcode để tối ưu hóa tuyến đường giao hàng cho bưu tá và giảm tỷ lệ phát không thành công.
