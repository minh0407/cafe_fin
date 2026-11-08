# Cafe Fin — thử trên PC Windows 11 x64 bằng GUI

Ngày 08/11/2026. Đây là hướng dẫn nghiệm thu; hiện chưa truy cập PC2 và mọi ca
dưới đây là NOT RUN. Kit baseline chưa có bộ cài do máy build bị AppControl chặn.
Không chạy file sidecar riêng. Chờ điều phối giao installer candidate cuối cùng,
có manifest/checksum đúng source sau khi ghép chức năng khay và startup.

## Trước khi cài

1. Mở Settings → System → About. Ghi Windows edition/version/build, x64, RAM/CPU,
   ổ local còn trống và quyền tài khoản vào RESULTS.json hoặc bản ghi bằng Notepad.
   Không ghi tên đăng nhập, serial máy, mật khẩu hoặc dữ liệu thật.
2. Ghi Cafe Fin/WebView2/Office/Python/Node/Docker có sẵn hay chưa. Máy có môi
   trường dev không được gọi là Windows sạch. Nếu Cafe Fin đang giữ dữ liệu thật,
   dừng phép thử; không reset cấu hình hoặc chọn lại DB để tạo môi trường giả sạch.
3. Dành thư mục local mới cho dữ liệu tổng hợp, ví dụ D:\CafeFinTestData\Đợt thử 01.
   Không chọn thư mục cài, SMB, OneDrive/Dropbox hoặc data root đang có dữ liệu.
   Nếu không có D/E, ghi rõ ổ đã thử và để ca D/E là NOT RUN.
4. Chỉ dùng installer được điều phối xác nhận trong installer/ của candidate cuối.
   manifest và SHA256SUMS đi cùng file. Hash lịch sử trong báo cáo không thay file.
   Kit có WebView2 standalone để đối chiếu/hỗ trợ; không cài trước ca kiểm thiếu
   runtime, vì làm vậy sẽ mất bằng chứng nhánh cài offline của bộ Cafe Fin.

## Cài và dùng lần đầu, không terminal/browser/Docker

- Ngắt WAN bằng GUI theo lựa chọn của chủ máy, giữ localhost hoạt động. Ghi cách
  ngắt và WebView2 có sẵn hay chưa. Không thay policy hoặc gỡ runtime OS để tạo ca.
- Nhấp đúp bộ setup, cài cho tài khoản Windows hiện tại. Ghi UAC/SmartScreen và
  signer thực tế. Nếu Windows chặn, ghi ảnh/thông báo rồi dừng; không tắt bảo vệ,
  thêm exclusion hoặc đổi tên/path để né chặn.
- Mở Cafe Fin từ shortcut/Start. App phải hiện trong cửa sổ riêng và tự chạy xử lý
  local. Không có bước mở website, Docker, Python, Node hoặc dev server.
- Chọn thư mục dữ liệu tổng hợp mới qua nút chọn thư mục. Tạo Admin thử nghiệm
  trong app; không lưu mật khẩu vào evidence. Tạo Operator thử bằng Quản lý tài khoản.
- Đóng/mở lại, kiểm đúng nơi lưu và dữ liệu đã nhập. Nếu ổ không sẵn sàng, app phải
  báo lỗi/giữ trạng thái; không tự tạo DB trống ở nơi khác.

## Khay và tự mở cùng Windows — chỉ kiểm candidate cuối đã tích hợp

- Đóng cửa sổ bằng X: app thu về khay và có hướng dẫn lần đầu. Nháp đang nhập phải
  còn hoặc được cảnh báo rõ; không suy rằng X đã Thoát hoàn toàn.
- Từ khay chọn Mở Cafe Fin, kiểm nháp và đăng nhập vẫn theo policy. Mở shortcut lần
  nữa không tạo instance/sidecar thứ hai. Chọn Thoát ở khay phải đóng thật.
- Tự mở cùng Windows mặc định tắt. Chỉ bật qua tùy chọn của app trong profile thử,
  đăng xuất/đăng nhập Windows để kiểm; không tự bật trên máy phát triển. Kiểm app
  không lưu mật khẩu/auto-login, bootstrap/data-root guard vẫn áp dụng. Tắt lại và
  kiểm trong Settings → Apps → Startup. Không cài service/task quản trị.
- Khi thu về khay, lịch báo cáo/bộ giá vẫn thuộc backend. Khi Thoát/ngủ/tắt máy thì
  không hứa tác vụ chạy; mở lại kiểm catch-up/cooldown đúng cấu hình. Thiếu cấu hình
  Telegram giữ Chưa cấu hình, nguồn giá bị chặn giữ BLOCKED. Không dùng nhóm thật.

## Fixture kế toán nhỏ, bảo toàn file gốc

Trong Kế toán tạo sổ thử riêng. Cấu hình và ánh xạ A:F theo expected-results.json:
Ngày=date; Mã=text (giữ 0001); Diễn giải=text; Thu/Chi=money hai số lẻ; Kg=decimal
ba số lẻ. Cột tiền/kg không bắt buộc, ô trống khác 0. Ngày là YYYY-MM-DD.
Chỉ dùng một file mini.csv HOẶC mini.xlsx cho một sổ/lượt sạch để không đếm chồng.

- Có 5 dòng nguồn: dòng Excel2/3 hợp lệ; dòng4 lặp dòng2; dòng5 cố ý sai ngày,
  tiền và precision; dòng6 có ô trống và số0. Xem/sửa/copy/paste bằng GUI.
- Chọn loại dòng4 một cách rõ ràng trong modal/manifest xác nhận. Nếu cấu hình
  khóa trùng, chọn Ngày+Mã cho phép thử này; không coi đó là quy tắc mọi sổ.
- Xác nhận phần hợp lệ: dự kiến 3 dòng công bố, 1 loại, 1 lỗi còn sửa. Tổng Thu
  15.000.000,00; Chi10.000.000,00; Kg2050,750. Đây là expected, chưa là kết quả chạy.
- Sửa đúng dòng nguồn5 thành ngày2026-11-08, Thu250000.00, Kg1.234, validate/xác nhận
  lại: chỉ thêm1, tổng4 dòng; Thu15.250.000,00; Chi10.000.000,00; Kg2051,984.
  Các dòng đã nhập không nhân đôi. Kế toán không làm thay tồn kho hay tạo tiền CRM.
- Xuất projection sửa riêng; tải lại bản Excel gốc để điều phối đối chiếu hash với
  fixture manifest. Người kiểm không phải chạy terminal. Không ghi đè file gốc.

preserve-only.xlsm có container macro-enabled hợp lệ, VBA mẫu công khai được pin,
và một external link tới example.invalid. Không mở/bật macro/content/link trong
Office, không chạy hàm hoặc nút macro. Chỉ import vào app để thử giữ byte gốc.
Nếu ánh xạ cộtI External vào cột công thức thử, phải báo không hỗ trợ; cached0
không được coi là kết quả đã tính. Không có lý do app gọi WAN vì file này.
VBA mẫu chỉ được phân tích tĩnh, không phải chứng nhận an toàn để chạy macro.

## Dữ liệu nghiệp vụ, backup và root

- Dùng fixture tổng hợp của lane nghiệp vụ đã ghép vào candidate, hoặc ví dụ trong
  USER_GUIDE. Kiểm farm/công ty, mua/bán, kho và báo cáo. Thử xuất quá tồn, sửa/xóa/
  đổi ngày làm âm tồn: phải bị chặn, dữ liệu cũ và lịch sử còn đúng. Không ghi dữ liệu thật.
- Lập hợp đồng có tiếng Việt, điều khoản và thanh toán. Xuất DOCX/PDF khi offline;
  xem PDF/phân trang/font, ghi việc xem/in Word nếu có viewer. Không có viewer thì
  visual Word là NOT RUN; không bắt cài Office chỉ để app xuất file.
- Sao lưu vào thư mục cha local khác qua GUI. Chuyển root mới: kiểm số liệu/hash,
  phiên đăng nhập target mới, khởi động lại vẫn giữ target. Giữ source cũ.
- Khôi phục backup vào root mới, đăng nhập Admin target và kích hoạt khi app đủ
  bằng chứng cho phép. Báo cáo/lịch gửi phải được giữ để kiểm tra lại sau restore.
- Nếu HELD/unknown ACK/MAINTENANCE_GENERATION_CONFLICT: giữ journal/marker/source,
  dùng chức năng trạng thái/attach theo guide. Không sửa file, xóa intent, Restart
  để hủy hoặc tự chọn DB rỗng thay thế. Phục hồi sau cắt điện là ca riêng, chưa thử.

## Nâng cấp, gỡ và kết luận

Chỉ thử nâng cấp sau khi điều phối giao rõ cặp from/to khác version, installer thật,
receipt và expected migration. Hai build cùng0.1.0 chỉ là thay thế/cài lại, không
được gọi là version-upgrade. Hiện chưa có cặp được chỉ định: ca upgrade NOT RUN.

Sau backup tổng hợp, gỡ bằng Settings → Apps → Installed apps. Kiểm data root và
tệp người dùng còn nguyên. Cài lại candidate đã chỉ định, chọn lại root thử và
đối chiếu số liệu/hash; không seed/reset DB. Không xóa rộng thư mục cha.

Ghi từng ca PASS/FAIL/NOT RUN và bằng chứng thực trong RESULTS.json. Không ghi token,
password, workbook thật hoặc raw HTTP. Không lấy build NSIS, test API hoặc parser
benchmark thay nghiệm thu app đã cài. Các mức50k/500k/1m dùng artifact cuối và slot
tải riêng của điều phối; mini fixture này không chứng minh hiệu năng lớn.
