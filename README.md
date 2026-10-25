# 📰 TIN TỨC — Trình Đọc Báo Cho muOS

![GitHub Release](https://img.shields.io/github/v/release/ChauHaiRetro/App_TinTuc_MUOS?style=flat-square&color=orange)
![Platform](https://img.shields.io/badge/OS-muOS-blue?style=flat-square)
![Device](https://img.shields.io/badge/Device-Anbernic%20RG40XX%20H-red?style=flat-square)
![Resolution](https://img.shields.io/badge/Resolution-640x480-green?style=flat-square)
![Python](https://img.shields.io/badge/Language-Python-yellow?style=flat-square)

**Tin Tức** là ứng dụng đọc báo trực tuyến/ngoại tuyến dành riêng cho thiết bị handheld chạy hệ điều hành **muOS** (tối ưu hóa cho màn hình 3.5 inch, độ phân giải 640x480 của Anbernic RG40XX H). App chỉ hiển thị văn bản, không tải hình ảnh giúp tối ưu tốc độ, trải nghiệm đọc cực kỳ mượt mà và tiết kiệm pin tối đa.

---

## 📦 Hướng Dẫn Cài Đặt

1. **Tải về:** Tải gói cài đặt (`TinTuc_muOS.muxapp`) tại mục **[Releases](https://github.com/ChauHaiRetro/App_TinTuc_MUOS/releases/latest)**.
2. **Sao chép vào thẻ nhớ:** 
   - Tắt máy và cắm thẻ nhớ SD (chứa hệ điều hành **muOS**) vào máy tính.
   - Chép file cài đặt vào thư mục `Archive` trên thẻ nhớ (đường dẫn: `MUOS/archive/` hoặc góc ngoài thẻ nhớ tùy cấu hình).
   - Eject (ngắt kết nối an toàn) và rút thẻ nhớ ra.
3. **Cài đặt trên thiết bị:** 
   - Cắm thẻ nhớ lại vào máy handheld và bật nguồn.
   - Kết nối Wi-Fi (**Configuration > Wi-Fi Network**).
   - Vào **Applications > Archive Manager** (hoặc Archive), chọn file cài đặt `TinTuc_muOS` để máy tiến hành tự động giải nén & cài đặt.
4. **Trải nghiệm:** Sau khi cài đặt hoàn tất, vào mục **Applications** trên muOS và chọn **Tin Tức**.

---

## 🎮 Hướng Dẫn Điều Khiển (Controls)

| Phím bấm | Thao tác / Chức năng |
| :--- | :--- |
| **D-Pad Lên / Xuống** | Di chuyển / Cuộn bài viết (giữ để cuộn nhanh) |
| **D-Pad Trái / Phải** | Lật trang |
| **Phím A** | Mở tin tức / bài viết |
| **Phím B** | Quay lại (tại màn hình chính: thoát ứng dụng) |
| **Phím X** | Tải lại danh sách tin / tải lại bài viết |
| **Phím Y** | Lưu hoặc bỏ lưu bài viết (đọc offline khi không có Wi-Fi) |
| **L1 / R1** | Đổi chuyên mục — khi đang đọc: chuyển sang bài trước / sau |
| **SELECT** | Thay đổi kích thước chữ khi đọc (5 mức độ) |
| **START** | Chuyển đổi giao diện Sáng / Tối (Light / Dark mode) |
| **MENU** hoặc **SELECT + START** | Thoát ứng dụng |

---

## 📰 Nguồn Tin & Tùy Chỉnh Nguồn

Ứng dụng hỗ trợ tổng hợp tin tức tự động từ các trang báo lớn:
* **VnExpress**, **VietnamPlus (TTXVN)**, **Nhân Dân**, **Báo Chính phủ**, **Tuổi Trẻ**, **Thanh Niên**, **Dân trí**, **BBC Tiếng Việt**.

💡 **Hướng dẫn tùy biến nguồn tin (`sources.json`):**
- Bạn có thể tùy chỉnh hoặc thêm bất kỳ nguồn feed RSS/Atom nào vào file `sources.json`.
- Nếu RSS của một trang bị hỏng (trống, lỗi 404, bị chặn), app sẽ tự động đổi cách gửi yêu cầu kết nối khác. Nếu vẫn không được, app sẽ lấy trực tiếp danh sách bài từ trang chủ (*tin lấy từ trang chủ sẽ không có giờ đăng và tóm tắt*).
- Để đọc thẳng một trang web (trang chủ hoặc trang chuyên mục), hãy thêm `"type": "html"` vào chuyên mục đó trong `sources.json` (hiện tại *Báo Chính phủ* đang áp dụng cách này).

---

## ⚙️ Cấu Hình Nâng Cao (`config.json`)

| Tham số | Mô tả / Chức năng |
| :--- | :--- |
| `utc_offset_hours` | Múi giờ hiển thị (mặc định Việt Nam là `7`) |
| `refresh_minutes` | Tự động tải lại chuyên mục sau số phút đặt sẵn |
| `swap_ab` | Đặt `true` nếu phím A/B bị ngược thao tác |
| `insecure_ssl_fallback` | Đặt `true` khi máy báo lỗi SSL dù ngày giờ đúng (kém an toàn hơn) |
| `debug_input` | Đặt `true` để hiển thị mã nút bấm ở chân màn hình |
| `raw_buttons` | Bảng mã nút bấm (dùng khi tay cầm không được nhận dạng chuẩn, kết hợp bật `debug_input` để tra mã) |

---

## 🛠️ Khắc Phục Sự Cố

- **App không mở / thoát đột ngột:** Xem nhật ký lỗi tại file `tintuc.log` và `stdout.log` trong thư mục `TinTuc`.
- **Nguồn tin không tải được:** Mở `tintuc.log`, tìm dòng `"tải chuyên mục:"` để kiểm tra các phương thức đã thử. Phản hồi bất thường từ máy chủ sẽ lưu ở `cache/debug/`.
- **Lỗi chứng chỉ SSL:** Kiểm tra và cài đặt lại ngày giờ của máy (**Settings > Date/Time**).
- **Lỗi "Không có mạng":** Bật Wi-Fi trong Settings rồi nhấn phím **X** để làm mới.
- **Nút bấm không nhận:** Bật `"debug_input": true` trong `config.json`, mở app bấm từng phím để xem mã, sau đó ánh xạ lại mục `"raw_buttons"`.
- **Bài viết chỉ hiện tóm tắt:** Một số dạng bài (video, ảnh, longform) không có đoạn văn chuẩn nên app chỉ lấy được phần tóm tắt.

---

## 📁 Dữ Liệu & Tín Dụng (Credits)

- **Cấu trúc lưu trữ:**
  - `data/`: Lưu bài viết đã lưu, bài đã đọc và cấu hình ứng dụng.
  - `cache/`: Bộ nhớ đệm tin tức (có thể xóa thư mục này bất kỳ lúc nào để giải phóng dung lượng thẻ nhớ).
- **Phông chữ:** [Be Vietnam Pro](https://github.com/bevietnampro/bevietnampro) (*Giấy phép SIL Open Font License tại `font/OFL.txt`*).
- **Chứng chỉ:** `cacert.pem` (Mozilla CA bundle qua certifi).
- ⚡ **Tối ưu hóa:** Ứng dụng chỉ hiển thị văn bản thuần, không tải hình ảnh giúp giao diện tải siêu nhanh, hoạt động mượt mà và tiết kiệm pin tối đa.
