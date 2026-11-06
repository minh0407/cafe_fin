# iconv: bằng chứng nguồn và gate phân phối — 07/11/2026

Trạng thái: **FACTUAL AUDIT ONLY; release gate vẫn OPEN; không có kết luận legal clearance.**
Baseline khi lưu báo cáo: ae82d009e162f2b1c356474ee7104768e41140cf.
Bản [JSON](iconv-source-provenance-20261107.json) giữ dữ kiện, URL, hash và phạm vi xác minh có cấu trúc.

Lần lưu này chỉ thêm hai tài liệu. Không tải lại artifact, build, chạy test executable,
sửa môi trường/source/CI/manifest/policy, gửi thông điệp upstream, upload hoặc phát hành.
Không đưa archive, binary, nội dung log, credential hay dữ liệu ứng dụng vào repo.
Các hash archive dưới đây được tính từ dữ liệu tải vào RAM trong lượt điều tra read-only trước đó.

## 1. Những gì đã xác nhận

Wheel locked là lxml-6.1.1-cp312-cp312-win_amd64.whl, 3.997.255 bytes,
SHA256 26e6eda8d38c1fcab1090dd196ee87cbd13788e531937610e2589085de074e77.
[Tệp PyPI](https://files.pythonhosted.org/packages/1b/89/45198e9624762af2dfd2cb8782598477ceb29f6e59caab560388ae1f4ec1/lxml-6.1.1-cp312-cp312-win_amd64.whl)
khớp uv.lock. etree.pyd byte-identical với bản installed đã kiểm và hash trong inventory:
b5cef7d22ab972de3fee18e3787730ba74ecd12d5896eaa3660ebde418219669.
objectify.pyd có hash ad4d1aabe85561cc06f503fb5758a45c3850a12f8719f1d66af06bd74553cf83.

Native versions được module báo là libxml2 2.11.9 và libxslt 1.1.45; feature iconv bật.
etree PE không import iconv DLL riêng và chỉ export PyInit_etree: phù hợp static linkage,
không cho phép đọc trực tiếp version iconv. Wheel không có iconv source/header/native-build
manifest hay object relink. Bản thân wheel chỉ có các notice lxml đã mô tả trong audit.

Exact lxml sdist có SHA256 ba96ae44888e0185281e937633a743ea90d5a196c6000f82565ebb0580012d40,
4.197.430 bytes; [URL nguồn](https://files.pythonhosted.org/packages/05/3b/aab6728cae887456f409b4d75e8a01856e4f04bd510de38052a47768b680/lxml-6.1.1.tar.gz).
Tag lxml-6.1.1 resolve tới b4a4c595fb875d6f50ae113449834209a364643a.
Sdist chứa generated C/packaging files; không gọi nó byte-identical với git archive.

[Build helper](https://github.com/lxml/lxml/blob/b4a4c595fb875d6f50ae113449834209a364643a/buildlibxml.py)
chọn tag lớn nhất theo chuỗi trong năm native releases gần nhất, rồi chọn assets win64
có version lớn nhất cho libxml2/libxslt/zlib/iconv. Cache ZIP chỉ được dùng lại nếu
**size và SHA256** trùng metadata asset. Bản tải mới dùng urlretrieve; helper không
assert digest một lần nữa ngay sau lệnh tải đó. Vì vậy cache cũ không mặc nhiên là
blocker, nhưng đây cũng không phải attestation của toàn bộ input link.

[Workflow](https://github.com/lxml/lxml/blob/b4a4c595fb875d6f50ae113449834209a364643a/.github/workflows/wheels.yml)
có LIBICONV_VERSION=1.18 chung; biến này không pin prebuilt Windows selection.
Không dùng giá trị đó để kết luận version của wheel Windows.

## 2. Chuỗi nguồn native ứng viên

Native release 2026.05.17, commit 4e8ae01f61145dc823ce2ae1d79f06241b7b46de,
[build.ps1](https://github.com/lxml/libxml2-win-binaries/blob/4e8ae01f61145dc823ce2ae1d79f06241b7b46de/build.ps1)
biên dịch project libiconv static, tạo iconv1.17.1/libxml2 2.11.9/libxslt1.1.45/zlib1.3.2.
[Workflow native](https://github.com/lxml/libxml2-win-binaries/blob/4e8ae01f61145dc823ce2ae1d79f06241b7b46de/.github/workflows/main.yml)
checkout submodules và áp
[libiconv.patch](https://github.com/lxml/libxml2-win-binaries/blob/4e8ae01f61145dc823ce2ae1d79f06241b7b46de/libiconv.patch).

| Source | Commit | Archive bytes | SHA256 |
| --- | --- | ---: | --- |
| [native-build](https://codeload.github.com/lxml/libxml2-win-binaries/tar.gz/4e8ae01f61145dc823ce2ae1d79f06241b7b46de) | 4e8ae01f61145dc823ce2ae1d79f06241b7b46de | 4262 | cd155987f5269d04acb549d8664b50b1ea0bf3580e1ab709587a03e4bda4396e |
| [libiconv](https://codeload.github.com/winlibs/libiconv/tar.gz/880a1fa8b5581e37e136a7b051947d3ea39097b6) | 880a1fa8b5581e37e136a7b051947d3ea39097b6 | 5313881 | 89dd45d7f074ddae04dcd25cc4ceace3432c04b72dc36a6508854aac713f3eb6 |
| [libxml2](https://codeload.github.com/winlibs/libxml2/tar.gz/bb84678855e3407fc88180295c992f9c984e28e0) | bb84678855e3407fc88180295c992f9c984e28e0 | 4225102 | 5182396205f97b183d34ab8dadd7693523c7d4e2137394aec02514a5a9a9dcf0 |
| [libxslt](https://codeload.github.com/winlibs/libxslt/tar.gz/c0076eaa6e0d1f99e01107e8db225a308eb1e543) | c0076eaa6e0d1f99e01107e8db225a308eb1e543 | 2705214 | d687aaf48527e042d942dccbc74fbcd150588522305e63d3e91785d9b6590677 |
| [zlib](https://codeload.github.com/winlibs/zlib/tar.gz/0089522e62e6b5d4950e62bd20f0cb06a9288413) | 0089522e62e6b5d4950e62bd20f0cb06a9288413 | 1559272 | e2af9f28fcdf723e464b40af73fdeed07ce3e581a9ea110702c1ba733983f8a0 |


Các gitlink được xác nhận từ tree native parent. **Archive parent chỉ 4.262 bytes,
không chứa source của bốn submodule**; chỉ đưa archive parent là thiếu material.
Hash ghi nhận bytes đã quan sát; nếu chuẩn bị source kit sau này phải giữ chính bytes
được kiểm, vì không giả định GitHub-generated tarball có encoding byte bất biến.

Assets của release 2026.05.17:

| Asset | Bytes | SHA256 | Phạm vi xác minh |
| --- | ---: | --- | --- |
| [iconv-1.17.1.win64.zip](https://github.com/lxml/libxml2-win-binaries/releases/download/2026.05.17/iconv-1.17.1.win64.zip) | 992481 | 090225898fc0b37fe1f0d3ecc3938c926de77cd7f8c3636a5c9712b61e7af849 | Hash bytes trong RAM + metadata |
| [libxml2-2.11.9.win64.zip](https://github.com/lxml/libxml2-win-binaries/releases/download/2026.05.17/libxml2-2.11.9.win64.zip) | 3455109 | ff23c75d4b3991042f9bbe7fd38ccc50616349a3c1b583c328d996be22e52b64 | Digest từ metadata release; chưa hash body riêng |
| [libxslt-1.1.45.win64.zip](https://github.com/lxml/libxml2-win-binaries/releases/download/2026.05.17/libxslt-1.1.45.win64.zip) | 461024 | e6fcfa1cf6719630e83c39a5448687db65084b0a375af366c9a857b62c3e4bf7 | Digest từ metadata release; chưa hash body riêng |
| [zlib-1.3.2.win64.zip](https://github.com/lxml/libxml2-win-binaries/releases/download/2026.05.17/zlib-1.3.2.win64.zip) | 206914 | e1c1bcaa1dea202057f96614565c5773ee9c9be7033b470f2b746ab8a9070f01 | Digest từ metadata release; chưa hash body riêng |


iconv ZIP gồm iconv_a.lib, iconv_a.pdb và headers, không phải complete corresponding
source. Bundle Windows tên 1.17.1; [source header](https://github.com/winlibs/libiconv/blob/880a1fa8b5581e37e136a7b051947d3ea39097b6/source/include/iconv.h)
ghi 0x0111, tương ứng GNU API 1.17. Không đồng nhất tên bundle với một GNU release 1.17.1.

## 3. Suy luận lịch sử, chưa phải chứng thực exact wheel

[Metadata release](https://api.github.com/repos/lxml/libxml2-win-binaries/releases/tags/2026.05.17)
ghi publish 17/05/2026 19:07:49 UTC; assets được tạo/cập nhật ngày 17/5.
PyPI wheel upload ngày 18/05/2026 19:17:56.781 UTC. Release trước đó 2026.03.25
còn libxslt1.1.39. Hai release tháng 10 (2026.10.05 và 2026.10.31-1) dùng iconv1.19
nhưng giữ libxml2 2.11.9/libxslt1.1.45; chúng xuất hiện sau wheel và không xác định
ngược được input của wheel tháng 5.

Chuỗi thời gian, helper kiểm cache hash và native versions làm 2026.05.17 trở thành
**ứng viên nguồn có bằng chứng lịch sử mạnh**. Nó không khôi phục một historical API
response bất biến hoặc chứng minh object bytes thực sự được link vào wheel hash này.
Không nâng suy luận đó thành binary proof.

[Wheel build run 26032085562](https://github.com/lxml/lxml/actions/runs/26032085562)
đã tìm được; log Windows cache job76520411743 trả HTTP410 Gone trong lượt kiểm trước.
[PyPI provenance endpoint](https://pypi.org/integrity/lxml/6.1.1/lxml-6.1.1-cp312-cp312-win_amd64.whl/provenance)
trả HTTP404. Chưa thu được artifact-specific attestation/native-input manifest.
Không tiếp tục đoán version từ integer hoặc chuỗi rời trong PE để lấp khoảng trống này.

## 4. Những gì còn thiếu trước khi gọi phân phối đã được xử lý

[License của nguồn ứng viên](https://github.com/winlibs/libiconv/blob/880a1fa8b5581e37e136a7b051947d3ea39097b6/source/COPYING.LIB)
là LGPL2.1; phần source library chính cho phép LGPL2.1-or-later. Audit không chọn lại
license hoặc xác nhận legal clearance. Điều6 nói tới prominent notice/license,
terms cho phép sửa cho việc dùng của khách và reverse engineering để debug sửa đổi.
Static-link route gồm corresponding source của library kể cả thay đổi, cùng source/object
và build materials của linked work đủ relink; các lựa chọn khác có điều kiện riêng.

backend.txt đã kiểm có LGPL3 text cho dependency khác; iconv chỉ xuất hiện ở dòng
OPEN DISTRIBUTION GATE, chưa phải source/relink package đã được xác minh.
Không suy clearance từ BSD của lxml hoặc từ một bản LGPL text thuộc dependency khác.
Scoped inspection không thấy root LICENSE/COPYING/EULA; việc này không kết luận
về toàn bộ quyền sở hữu, hợp đồng hoặc terms chưa được inspect.

Sidecar hiện dùng onefile, chứa các PYD. [PyInstaller](https://pyinstaller.org/en/v6.22.3/advanced-topics.html)
giải nén payload vào runtime directory. Chép một iconv DLL cạnh EXE không phải
replacement procedure đã được chứng minh cho static PYD này.

Đường ít thay đổi nhất là **giữ wheel/static iconv và chuẩn bị bộ source/relink riêng**:

1. Giữ exact lxml sdist, native parent, đủ bốn submodule, patch, headers/config/build
   scripts, hash và notices tương ứng trong source kit. Báo cáo này không chứa kit đó.
2. Xác định terms phù hợp cho người nhận sửa/debug và quyền dùng source/object materials.
   Không mặc nhiên cần đổi toàn bộ business core sang LGPL; cũng không tự suy terms đã đủ.
3. Cung cấp recipe đủ sửa libiconv, relink cả etree/objectify rồi đóng gói/chạy với
   business-core source không đổi. Không đòi refactor nghiệp vụ hoặc đổi dependency.
   Việc này có thể cần build/đóng gói sidecar cho người nhận, khác với thay đổi core.
4. Trong lượt thực thi riêng được giao, chứng minh recipient procedure với một thay đổi
   libiconv vô hại và ghi hash/result. Audit tài liệu hiện tại không thay bằng chứng này.
5. Nếu gate của dự án cần wheel-specific confirmation mạnh hơn, một yêu cầu có giới hạn
   tới maintainer, nêu exact wheel/native ZIP hash và commits, là bước thu thập bằng chứng
   cụ thể. Không có liên hệ nào được gửi trong audit này. Không để việc tìm log đã Gone
   hoặc scan PE suy đoán kéo dài vô hạn.

## 5. Vì sao no-iconv chưa phải đường tối thiểu

Ignored proposal ở main checkout .local-runtime/licensing/lxml-noiconv-proposal vẫn
**NOT BUILT / NOT APPROVED**. CMake no-iconv được libxml2 hỗ trợ, nhưng lxml Windows
cần private link/macro patch. Link-only mất non-BMP Python str parsing vì native
không có UTF32 converter; Cython UTF8 fallback riêng mới là draft chưa compile/test.
Fallback cũng không khôi phục raw UTF32 hay arbitrary legacy XML codecs.

Proposal dùng VS2026v145, tạo thêm yêu cầu CRT so với PBS14.44.35211.0 đang được
inventory ghi nhận. [Microsoft](https://learn.microsoft.com/en-us/cpp/porting/binary-compat-2015-2017)
yêu cầu runtime ít nhất mới bằng toolchain mới nhất của các component. Dùng toolchain
mới cần review runtime/provenance/notices; không kế thừa mặc nhiên runtime claim cũ,
không đổi /MT để che vấn đề, không thu DLL bất kỳ từ host PATH.

No-iconv là phương án thay artifact riêng; nó không đổi nghĩa vụ của wheel/EXE cũ.
Source/relink kit cho static wheel tránh các thay đổi hành vi/CRT bổ sung đó, nhưng
chưa đủ bằng chứng để đóng gate ngay trong báo cáo read-only này.

## 6. Tham chiếu artifact và kiểm tra lần lưu

Tracked desktop/notices/sidecar-native-inventory.json ghi executable lịch sử
b9377e8a173a92eac8827a4a73bdf503d185cdb8cc40151f498babfe98384ecb,
33.017.856 bytes. Đây là reference foundation inventory, không phải nghiệm thu
runtime của business baseline ae82d00 hoặc của installer mới.

- JSON parse: PASS.
- Whitespace/final newline của hai tài liệu: PASS.
- Native/Cython build, test executable, relink/replaceability, CRT/frozen/installer
  và clean-Windows acceptance trong lượt lưu: NOT RUN.
- backend notices, OPEN gate, source, manifest, CI, môi trường và policy: không sửa.
- Không stage, commit hoặc push. Root review và quyết định các bước tiếp theo.
