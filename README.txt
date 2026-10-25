TIN TỨC — Trình đọc báo cho muOS (Anbernic RG40XXH)
====================================================

CÀI ĐẶT
-------
1. Tắt máy, rút thẻ SD1 (thẻ có thư mục MUOS) cắm vào máy tính.
2. Chép nguyên thư mục "TinTuc" vào:   MUOS/application/
   -> kết quả: MUOS/application/TinTuc/mux_launch.sh
3. Cắm thẻ lại, bật máy. App nằm trong mục Applications -> "Tin Tức".
   (Nếu chưa thấy, khởi động lại máy một lần.)
4. Nhớ bật Wi-Fi trong Settings trước khi mở app.

Cách khác (qua SSH/SFTP khi máy đang bật Wi-Fi):
   scp -r TinTuc root@<IP-máy>:/mnt/mmc/MUOS/application/
   ssh root@<IP-máy> chmod +x /mnt/mmc/MUOS/application/TinTuc/mux_launch.sh

ĐIỀU KHIỂN
----------
  D-pad lên/xuống   di chuyển / cuộn bài (giữ để cuộn nhanh)
  D-pad trái/phải   lật trang
  A                 mở
  B                 quay lại (ở màn hình đầu: thoát)
  X                 tải lại tin / tải lại bài
  Y                 lưu hoặc bỏ lưu bài (bài đã lưu đọc được khi không có mạng)
  L1 / R1           đổi chuyên mục — khi đang đọc: sang bài trước / sau
  SELECT            đổi cỡ chữ khi đọc (5 mức)
  START             đổi giao diện sáng / tối
  MENU hoặc SELECT+START   thoát

NGUỒN TIN
---------
VnExpress, VietnamPlus (TTXVN), Nhân Dân, Báo Chính phủ, Tuổi Trẻ,
Thanh Niên, Dân trí, BBC Tiếng Việt.
Sửa / thêm nguồn trong file sources.json (bất kỳ RSS hoặc Atom nào).
Nếu RSS của một báo hỏng (trống, lỗi 404, bị chặn), app tự thử lại với cách
gửi yêu cầu khác. Nếu vẫn không được, app lấy danh sách bài thẳng từ trang chủ
của báo. Tin lấy từ trang chủ không có giờ đăng và phần tóm tắt.
Muốn đọc thẳng một trang web (trang chủ hoặc trang chuyên mục), thêm
"type": "html" vào chuyên mục đó trong sources.json. Báo Chính phủ đang dùng
cách này.

TÙY CHỈNH (config.json)
-----------------------
  utc_offset_hours       múi giờ hiển thị (Việt Nam = 7)
  refresh_minutes        tự tải lại chuyên mục sau bao nhiêu phút
  swap_ab                true nếu thấy nút A/B bị ngược
  insecure_ssl_fallback  true chỉ khi máy luôn báo lỗi chứng chỉ SSL
                         dù ngày giờ đã đúng (kém an toàn hơn)
  debug_input            true để hiện mã nút bấm ở chân màn hình
  raw_buttons            bảng mã nút, chỉ dùng khi tay cầm không được
                         nhận dạng chuẩn (bật debug_input để tra mã)

XỬ LÝ SỰ CỐ
-----------
- App không mở / thoát ngay: xem file tintuc.log và stdout.log trong
  thư mục TinTuc.
- Một nguồn vẫn không có tin: mở tintuc.log, tìm dòng "tải chuyên mục:" để
  xem từng cách đã thử. Phản hồi lạ của máy chủ được lưu trong cache/debug/.
- "Lỗi chứng chỉ SSL": kiểm tra ngày giờ của máy (Settings > Date/Time).
- "Không có mạng": bật Wi-Fi trong Settings rồi nhấn X.
- Bấm nút không ăn: bật "debug_input": true, mở app, bấm từng nút để xem
  mã, rồi sửa "raw_buttons" cho khớp.
- Bài chỉ hiện tóm tắt: một số trang (video, ảnh, longform) không có
  đoạn văn thường nên app chỉ lấy được phần tóm tắt.

Dữ liệu: data/ (bài đã lưu, đã đọc, cài đặt), cache/ (tin tải về).
Xóa cache/ nếu muốn giải phóng dung lượng.

Font: Be Vietnam Pro — giấy phép SIL Open Font License (font/OFL.txt).
Chứng chỉ gốc: cacert.pem (Mozilla CA bundle, qua certifi).
App chỉ hiển thị chữ, không tải ảnh, để nhẹ và tiết kiệm pin.
