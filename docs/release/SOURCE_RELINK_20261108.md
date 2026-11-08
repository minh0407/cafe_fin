# Material source/relink — 08/11/2026

Trạng thái: material đã tải/kiểm hash, recipe có thật; **relink execution NOT RUN**,
chưa đóng gate phân phối. Đọc cùng factual audit iconv ngày07/11 trong handoff
packaging. Không suy từ đủ notices thành legal/distribution clearance.

## Material thực có

prepare_source_relink.py và materials.lock.json tạo workbench mới, tải12 archive
đã pin và kiểm size/SHA256. Gồm exact lxml6.1.1 sdist/wheel, native parent release
2026.05.17, đủ libiconv/libxml2/libxslt/zlib submodule archives, bốn prebuilt assets
và setuptools84.2.1 source. Parent archive riêng không chứa submodule source;
workbench này có cả12 file và các tree đã giải nén. Không thực thi downloaded code.

Trong kit, archives/ giữ byte nguyên; trees/native chứa build.ps1, libiconv.patch,
MSVC projects/config/header/source của bốn thư viện. trees/lxml có generated C
etree/objectify và packaging/build helper. COPY[ING]/license gốc nằm trong source.
Candidate collection kèm git archive của đúng application source, không Git history
hoặc DB/credential. Recipe được copy riêng và có hash trong kit-manifest.

Nguồn native lịch sử vẫn là **historical inference**, chưa có wheel-specific
native-input attestation. Cùng version libxml2/libxslt không chứng minh object đã
link vào wheel PyPI. Workbench không giả khép khoảng trống đó. Source references:
https://github.com/lxml/libxml2-win-binaries/tree/4e8ae01f61145dc823ce2ae1d79f06241b7b46de
https://github.com/lxml/lxml/tree/b4a4c595fb875d6f50ae113449834209a364643a

## Recipient procedure cụ thể

Đây là công việc developer riêng, không phải bước người dùng app/PC2 phải làm.
Trên Windows x64 **được phép thực thi native tools**, chuẩn bị MSVC v14314.44.x,
SDK26100, Python3.12.16 x64 và uv. Các công cụ build có terms riêng, không dùng
evaluation key. Build hiện tại dùng CRT14.44.35211; không âm thầm chuyển sangv145,
/MT hoặc thu DLL bất kỳ từ host PATH. Source/CRT/notices phải được review lại nếu
chọn compiler khác. Máy local hiện chỉ có14.51 và AppControl chặn build helper.

1. Giữ nguyên archive/pin receipt. Dùng workbench mới và source app giải nén từ
   candidate/source/cafe-fin-<SHA>.zip, không live checkout, không data root.
2. Chạy relink_lxml.ps1 mặc định để chỉ kiểm material/hiện plan. Không có -Build
   thì không chạy compiler, import modified PYD, test EXE hoặc packaging.
3. Trên môi trường cho phép đã review, truyền -Build, -Workbench, -AppSourceRoot
   và -Python. Recipe áp đúng upstream libiconv.patch, thêm function vô hại trả
   20261108 vào iconv.c để làm bằng chứng linked native code, rồi build iconv,
   zlib, libxml2 và libxslt từ các source tree đã cung cấp.
4. Recipe dùng generated C với lxml --static --without-cython và thư mục include/lib
   chỉ định. Không dùng STATICBUILD/--static-deps để tải release native mutable.
   etree VÀ objectify phải link lại. Output wheel là bản modified, không đổi tên
   thành wheel PyPI byte-identical. Ghi hash và thay đổi source/probe rõ ràng.
5. Tạo environment riêng theo uv.lock, chỉ thay lxml bằng wheel modified. Không
   chỉnh business source. verify_relinked_lxml.py phải gọi probe export từ cả hai
   PYD, kiểm Unicode tiếng Việt/non-BMP, ghi module hashes và kết quả thực.
6. Build lại frozen sidecar bằng source app nguyên, rồi chạy existing frozen
   loopback/unicode/second-instance/restart test với CAFE_FIN_TEST_SIDECAR trỏ file
   mới. Receipt chỉ được ghi PASS sau tất cả lệnh đó thành công và source hash
   trước/sau bằng nhau. Việc compile không thay test chạy thật.

Ví dụ plan-only (đã chạy):
`relink_lxml.ps1 -Workbench <material-folder>` → PLAN_ONLY,12 materials,NOT_RUN.
Full -Build chưa chạy; recipe này chưa được xác nhận là một successful recipient
build. Không chạy/đổi output path trên host bị policy chặn để thử vượt chặn.
Sau proof, tích hợp lại modified sidecar/bộ cài đúng source nếu chọn thay artifact;
không giả rằng chép iconv DLL cạnh onefile EXE là replacement cho static PYD.

## Notices, quyền và gate còn lại

libiconv source mang LGPL2.1-or-later theo các header liên quan; COPYING.LIB2.1
được giữ nguyên và thêm vào notices. lxml BSD không thay license của iconv.
https://github.com/winlibs/libiconv/blob/880a1fa8b5581e37e136a7b051947d3ea39097b6/source/COPYING.LIB

Material delivery không tự cấp quyền của mọi bên hoặc đặt license mới cho toàn bộ
business app. Điều phối/chủ quyền cần chốt terms người nhận được sửa thư viện,
relink/replace và reverse-engineer cho debugging các sửa đổi theo phạm vi license,
không đặt hạn chế mâu thuẫn. Đây là điểm review cụ thể còn mở, không một giấy phép
evaluation/non-commercial hoặc lời hứa cung cấp source sau này.

Đề nghị terms để owner review, chưa phải EULA đã có hiệu lực: “Người nhận được sửa
các thư viện LGPL kèm theo để dùng riêng, relink/thay chúng bằng bản đã sửa và thực
hiện reverse engineering cần thiết để debug các sửa đổi đó. Các quyền license của
bên thứ ba giữ nguyên; điều khoản Cafe Fin không hạn chế các quyền này.” Owner
phải kiểm quyền phân phối material/application source trước chuyển kit.

Gate vẫn OPEN: wheel-specific provenance hoặc lựa chọn artifact rebuild được duyệt;
recipient relink/frozen test thực; terms review; signature/installer/client offline
acceptance; nâng cấp/clean Windows/packaged benchmarks. Không upload/release hoặc
gọi kit sẵn sàng phân phối dựa vào PLAN_ONLY hay các synthetic gate tests.
