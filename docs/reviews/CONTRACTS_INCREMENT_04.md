# Hợp đồng và giao diện sử dụng — increment 04

Điều phối ghép module contracts tới `61a014ab389a1c2ff036d61cf6fb748ea38d0d97`, giữ module records đã kiểm và các shared fixes đã review. Nguồn làm việc ở `C:\Users\NC\.codex\worktrees\cafe-fin-foundation-recovery\cafe_fin`; checkout tích hợp đích vẫn là `C:\Users\NC\Desktop\UNILA{\cafe_fin`.

## Hành vi

Hợp đồng mua/bán cho nhập tay hoặc tìm đối tác/phiếu cân đã ghi để tự điền, rồi sửa trước khi lưu. Điều khoản, phương thức và lịch thanh toán là dữ liệu thật đưa vào preview/Word/PDF. Sửa hợp đồng không sửa nguồn cân, tồn kho hoặc sổ tiền. Snapshot đã xuất giữ nguyên; các định dạng phục hồi riêng khi render lỗi. Đính kèm bản ký là ghi nhận của người nhập, không tạo phê duyệt.

Registry dùng `RecordsReadProvider` theo runtime và principal hiện tại; không có tài khoản toàn cục. Xuất phục hồi sau crash dùng stable storage owner: retry khác tài khoản không tạo tệp thứ hai. Domain download kiểm saved reference, hash/size và quyền hiện tại trước headers; generic file ownership vẫn giữ nguyên. Migration contracts v2 nối thêm stable owner, không đổi checksum v1. Sidecar đóng gói cả template JSON của module.

Ngày nhập hiển thị DD/MM/YYYY và gửi ISO date; bản nháp ngày sai không gửi giá trị cũ hoặc coi là xóa. Calendar tuân thủ Form disabled. Root thêm Admin listing `/api/v1/users` và màn tạo/sửa role/khóa tài khoản local; không thêm OAuth hoặc bước duyệt. Lệnh chưa rõ kết quả giữ nguyên payload/request key để retry, phản hồi cũ không vượt phiên đăng nhập. Core vẫn chặn vô hiệu hóa Admin cuối cùng.

App sản phẩm mặc định mở ghi nhận, có mục cài đặt trên máy. Menu và route thử kỹ thuật chỉ bật bằng `VITE_CAFE_FIN_PROOFS=1` trong development; production không bật chúng. Cấu hình browser core chủ động bật proofs để giữ các phép kiểm nền tảng.

## Kiểm chứng tại Windows host

Python 3.12.16, SQLite 3.53.1, Node 24.21.0. Dữ liệu tổng hợp, không dùng DB/Excel/credential thật.

| Kiểm tra | Kết quả |
|---|---|
| `.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider` | PASS 445 tests / 190,82 giây: 183 core, 131 records, 131 contracts |
| Ruff backend/tests/scripts, compileall, diff whitespace | PASS |
| Frontend production build/TypeScript | PASS; chunk lớn còn cảnh báo |
| `CAFE_FIN_REAL_API=1 npm test` | PASS 32 tests / 17,9 giây |
| Records browser, HTTP/SQLite thật, cổng 1421 | PASS 1 flow / 20,2 giây |
| Contracts browser, HTTP/SQLite thật, cổng 1422 | PASS 3 flows / 29,3 giây |

App-shell thật dùng registry mặc định, tìm và lấy đối tác/cân qua API, tạo hợp đồng, preview/xuất DOCX+PDF; sửa lượng hợp đồng từ 12,345 xuống 1,125 kg vẫn giữ nguồn 12,345 kg. Cũng qua menu cài đặt thật để tạo Operator, sửa active theo version và thấy trạng thái khóa. Chỉ native invoke được stub; HTTP/auth/SQLite/module dùng thật. Các browser unit khác mock HTTP và không được tính là native acceptance.

Production bundle còn được smoke riêng bằng Chromium với HTTP/native mocks: 8 checks Admin/Operator PASS, mở records mặc định, không có menu proofs, truy cập trực tiếp hai hash proofs không gọi API `/spikes`, Admin có quản lý tài khoản, Operator không thấy hoặc fetch danh sách tài khoản. Đây là kiểm chứng bundle/UI, không thay cho real API hoặc native acceptance.

Reviewer độc lập đã kiểm rollback/stock của records, xuất hợp đồng crash/cross-actor, attachment ownership/revocation, stale source picker, date validation và snapshot isolation. Chi tiết cùng giới hạn nằm trong handoff từng module. Các lượt focused có giao nhau, không cộng thành một tổng test mới.

## Giới hạn phát hành

Đây là increment phát triển; accounting/reporting chưa có trong increment này. Native NSIS của source records trước đã build thành công ở CI; chưa dùng kết quả đó để tuyên bố native contracts PASS. CI của increment này phải kết thúc riêng. Không upload/phát hành bộ cài hoặc gửi Zalo thật.

Clean-Windows install/GUI/offline/update/uninstall, DOCX mở/in trực quan và nghĩa vụ phân phối native iconv còn là release gate. Host AppControl vẫn chặn một số Rust build outputs; không thay policy để né. Thư viện/grid miễn phí dùng theo license đã khóa, không có evaluation key. CRM cũ giữ nguyên.
