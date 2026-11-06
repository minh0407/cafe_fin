# Windows Credential Manager adapter

Phạm vi bàn giao: `backend/cafe_fin/core/secrets.py` và `tests/core/test_secrets.py`. Chưa wiring runtime/reporting, không thay dependency, registry hoặc contract dùng chung. Adapter không đọc/ghi credential của CRM cũ.

## Interface và phạm vi

`WindowsCredentialStore` cung cấp `available: bool`, `has(key)`, `get(key) -> dict | None`, `put(key, value: dict)` và `delete(key)`. Interface khớp `SecretStore` của reporting. Caller vẫn phải kiểm quyền Admin/token trước khi sử dụng adapter; adapter không phải endpoint công khai.

Chỉ nhận khóa `cafe_fin/reporting/{root_uuid}/{oa_id}` với UUID canonical chữ thường và OA ID 1–128 ký tự ASCII chữ/số/`_`/`-`. Không nhận tên credential hệ thống hoặc target tùy ý. Target Windows là `CafeFin:reporting:v1:` + SHA-256 của toàn khóa, nên tách theo data-root identity/OA và không chứa đường dẫn local.

Trên Windows, dùng `CredReadW`, `CredWriteW`, `CredDeleteW` và `CredFree` trong DLL hệ thống `Advapi32.dll`, qua ctypes với chữ ký/pointer được khai báo. Loại `CRED_TYPE_GENERIC`, persistence `CRED_PERSIST_LOCAL_MACHINE`: tồn tại qua phiên đăng nhập của **cùng Windows user trên cùng máy**, không phải chia sẻ cho mọi user và không roaming sang máy khác.

Mỗi lần `put` serialize toàn bộ dict thành một UTF-8 JSON `CredentialBlob` và thực hiện **một** `CredWriteW` để thay thế nguyên cặp access/refresh token. Không delete trước khi ghi, không chia cặp token thành hai credential. Kiểm JSON hữu hạn và kích thước UTF-8 tối đa **2.560 byte**, gồm cả cấu trúc JSON, trước khi gọi OS. Payload quá lớn/không hợp lệ giữ nguyên bản cũ; không tự chuyển sang file/DB/env. Buffer ctypes tạm được xóa sau ghi, nhưng không tuyên bố Python có thể xóa mọi bản sao trong RAM.

Stress API thật phát hiện `CredReadW` có thể trả `ERROR_NOT_FOUND` thoáng qua trong lúc nhiều writer thay thế. Adapter vì thế dùng mutex Windows theo hash target (`Local\\CafeFin.Credentials.<hash>`), áp dụng cho cả read/write/delete, timeout 5 giây, để các instance/thread/process hợp tác trong cùng Windows session không quan sát khe hở này. Không enumerate credential. Đây không phải khóa các chương trình khác bỏ qua adapter hoặc các Terminal Services session khác; persistence LOCAL_MACHINE vẫn áp dụng qua các lần đăng nhập của cùng user. Named mutex bỏ dở được nhận lại, rồi dữ liệu credential được kiểm tra trước khi trả.

`available=False` ngoài Windows hoặc khi không load được API. Trường hợp đó `has=False`, `get=None`, còn ghi/xóa trả `SECRET_STORE_UNAVAILABLE`. Trên Windows, key không tồn tại trả `None`; lỗi OS khác trả CoreError đã làm sạch, không trả configured=true hoặc nội dung token. JSON/metadata credential không hợp lệ trả lỗi rõ. Không log target/key/value hoặc raw lỗi Windows.

## Kiểm chứng

Chạy trên Windows đang dùng bằng Python venv recovery:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/core/test_secrets.py
```

Các ca Windows gọi API thật với namespace UUID ngẫu nhiên riêng cho từng test: read-missing, write/get, đọc từ instance mới, thay nguyên cặp, delete idempotent, giới hạn UTF-8, ghi không hợp lệ giữ bản trước và hai writer/hai reader thấy cặp nguyên vẹn. Cleanup trong `finally` chỉ xóa đúng key test tạo; không enumerate hoặc xóa credential khác. Error-path access-denied được mô phỏng bổ sung trên adapter sau khi tạo credential tổng hợp thật; không làm thay đổi ACL/OS credential thật.

Kết quả thật ngày 06/11/2026: **15 PASS**, không skip, trên Windows 11 build 26200, Python 3.12.16 x64; cấu trúc CREDENTIALW 80 byte. `ruff check` và `ruff format --check` cho hai file Python PASS. Bốn ca có real Credential Manager gồm roundtrip/replace/delete, giới hạn byte, concurrent pair và OS-error supplement; thêm mutex-timeout supplement kiểm giữ bản cũ. Toàn bộ target tổng hợp đã được cleanup bằng đúng key trong fixture. Không kiểm tài khoản Zalo thật, không gửi tin ra ngoài, không chứng minh logout/reboot khác Windows user bằng các test này. Backup dữ liệu local không mang theo credential Windows; máy/user khác cần nhập lại credential.

## Nguồn chính thức

- [CREDENTIALW: kiểu generic, 5×512 byte, persistence](https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw)
- [CredWriteW: tạo hoặc thay thế credential](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credwritew)
- [CredReadW: credential của logon session và bộ nhớ phải CredFree](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credreadw)
- [CredDeleteW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-creddeletew), [CredFree](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credfree)
- [CreateMutexW](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-createmutexw), [WaitForSingleObject](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject)
