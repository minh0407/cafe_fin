"""Deterministic synthetic desktop contracts, independent of records and renderer code.

All people, companies, identifiers and accounts below are invented test text.
The HTTP harness may seed actual records and add source references to a copy;
the base payloads intentionally also exercise completely manual contracts.
"""

from copy import deepcopy

FIXTURE_DATE = "2026-11-08"
PRODUCT_IDS = {
    "purchase": "c006f101-7fe8-5000-8000-000000000001",
    "sale": "c006f101-7fe8-5000-8000-000000000002",
}

_COMPANY = {
    "type": "company",
    "roles": ["buyer", "seller"],
    "name": "Công ty TNHH Cà phê Thử Nghiệm Cao Nguyên Xanh",
    "tax_code": "THU-MST-CONGTY-0001",
    "address": "Số 00, đường Dữ Liệu Tổng Hợp, phường Thử Nghiệm, Đắk Lắk",
    "contacts": [
        {"kind": "phone", "value": "0000000000", "label": "Điện thoại thử"},
        {"kind": "email", "value": "congty@cafe-fin.example", "label": "Email thử"},
    ],
    "bank_details": [
        {
            "bank_name": "Ngân hàng Tổng Hợp Thử Nghiệm",
            "account_number": "THU-00000123",
            "account_holder": "CONG TY CA PHE THU NGHIEM",
            "branch": "Chi nhánh Dữ Liệu Tổng Hợp",
        }
    ],
    "representative": {
        "name": "Nguyễn Ánh Thử Nghiệm",
        "title": "Giám đốc thử nghiệm",
        "authorization_reference": "Ủy quyền tổng hợp THU-UQ-0001, ngày 2026-11-08",
    },
}

_FARM = {
    "type": "farm",
    "roles": ["supplier"],
    "name": "Hộ trồng cà phê Thử Nghiệm Y H'Ương Êban",
    "tax_code": "THU-DINHDANH-FARM-0001",
    "address": "Buôn Tổng Hợp, xã Dữ Liệu Mẫu, Đắk Lắk",
    "contacts": [
        {"kind": "phone", "value": "0000000001", "label": "Chủ farm thử"},
        {"kind": "email", "value": "farm-ab01@cafe-fin.example", "label": "Email farm thử"},
    ],
    "bank_details": [
        {
            "bank_name": "Ngân hàng Mẫu Nông Nghiệp",
            "account_number": "THU-FARM-0000456",
            "account_holder": "Y HUONG THU NGHIEM",
            "branch": "Chi nhánh Farm Tổng Hợp",
        }
    ],
    "representative": {"name": "Y H'Ương Thử Nghiệm", "title": "Chủ farm thử"},
}

_CUSTOMER = {
    "type": "company",
    "roles": ["customer"],
    "name": (
        "Công ty Cổ phần Thử Nghiệm Chế Biến Và Phân Phối Cà Phê "
        "Chất Lượng Cao Tây Nguyên Đắk Nông Việt Nam"
    ),
    "tax_code": "THU-MST-KHACHHANG-0002",
    "address": (
        "Lô thử 00, khu Dữ Liệu Tổng Hợp, phường Thử Nghiệm, Đắk Nông; "
        "địa chỉ dài kiểm tra tiếng Việt ă â đ ê ô ơ ư Á Ế Ỡ Ự. "
    )
    * 3,
    "contacts": [
        {"kind": "phone", "value": "0000000002", "label": "Người liên hệ thử"},
        {"kind": "email", "value": "khachhang@cafe-fin.example", "label": "Email khách thử"},
    ],
    "bank_details": [
        {
            "bank_name": "Ngân hàng Mẫu Thương Mại",
            "account_number": "THU-KHACH-0000789",
            "account_holder": "KHACH HANG CA PHE THU NGHIEM",
            "branch": "Chi nhánh Khách Hàng Tổng Hợp",
        }
    ],
    "representative": {
        "name": "Trần Thị Ánh Thử Nghiệm",
        "title": "Người đại diện khách hàng thử",
        "authorization_reference": "Giấy phép/ủy quyền tổng hợp THU-KH-0002",
    },
}


def contract_payloads() -> dict[str, dict]:
    """Return fresh JSON-ready purchase/sale payloads; no IDs are generated at run time."""
    purchase = {
        "kind": "purchase",
        "number": "HĐ-MUA-THỬ-20261108-0001",
        "occurred_on": FIXTURE_DATE,
        "place": "Buôn Ma Thuột - địa điểm thử nghiệm",
        "template_id": "be33fbce-4a0d-50eb-b203-895a24102ce1",
        "company": deepcopy(_COMPANY),
        "counterparty": deepcopy(_FARM),
        "lines": [
            {
                "product_id": PRODUCT_IDS["purchase"],
                "description": "Cà phê quả tươi farm AB01 - dòng tịnh nhập tay",
                "quantity_kg": "100.005",
                "net_kg": "100.005",
                "unit_price": "100.50",
                "quantity_source": "direct",
                "note": "Chỉ có kg tịnh người dùng nhập; không tạo cân đầy/rỗng giả.",
            },
            {
                "product_id": PRODUCT_IDS["purchase"],
                "description": "Cà phê nhân Robusta farm AB01 - dòng đầy/rỗng/tịnh",
                "quantity_kg": "250.125",
                "gross_kg": "260.125",
                "tare_kg": "10.000",
                "net_kg": "250.125",
                "unit_price": "95000.25",
                "quantity_source": "gross_minus_tare",
                "note": "Nội dung cân do người dùng ghi; chưa phải dữ liệu từ thiết bị.",
            },
        ],
        "tax": {"mode": "exclusive", "rate": "8.00"},
        "terms": {
            "delivery": "Đã sửa: giao tại kho thử nghiệm số 00.\nĐối chiếu riêng từng dòng cân.",
            "packaging": "Bao tổng hợp; số bao theo người dùng ghi, không theo QR.",
            "quality": "Grade/chất lượng theo ghi nhận hai bên.\nKhông mặc định tỷ lệ ẩm hoặc tạp.",
            "deadline": "Giao đợt đầu ngày 2026-11-10; đợt còn lại ngày 2026-11-12.",
            "responsibilities": "Bên mua và bên bán kiểm thông tin trước khi ký.\nĐiều khoản này đã được người nhập sửa.",
            "additional": (
                "Farm AB01; mã vùng VÙNG-THỬ-01; lô trồng LÔ-THỬ-02.\n"
                "Văn bản an toàn: <script>alert('thử')</script> & <b>giữ nguyên chữ</b>.\n"
                "Không có ảnh farm, con dấu hoặc chữ ký thật."
            ),
        },
        "payment": {
            "method": "mixed",
            "description": "Đã sửa: một phần tiền mặt, phần còn lại chuyển khoản.\nLịch là cam kết hợp đồng do người nhập ghi.",
            "receiving_account": deepcopy(_FARM["bank_details"][0]),
            "due_on": "2026-11-30",
            "deposit_amount": "500000.50",
            "recorded_paid_amount": "0.00",
            "schedule": [
                {
                    "due_on": "2026-11-15",
                    "amount": "10000000.00",
                    "note": "Đợt một theo điều khoản đã sửa",
                },
                {
                    "due_on": "2026-11-30",
                    "amount": "15673747.07",
                    "note": "Phần giá trị còn lại theo lịch",
                },
            ],
        },
        "source_refs": [],
    }
    sale = {
        "kind": "sale",
        "number": "HĐ-BÁN-THỬ-20261108-0002",
        "occurred_on": FIXTURE_DATE,
        "place": "Đắk Nông - địa điểm thử nghiệm",
        "template_id": "9be1e97b-8278-55d3-aaba-13f663349ab2",
        "company": deepcopy(_COMPANY),
        "counterparty": deepcopy(_CUSTOMER),
        "lines": [
            {
                "product_id": PRODUCT_IDS["sale"],
                "description": f"Lô hàng thử {number:02d} - Cà phê nhân Đắk Nông tuyển chọn",
                "quantity_kg": f"{number}.125",
                "net_kg": f"{number}.125",
                "unit_price": "108000.00",
                "quantity_source": "direct" if number == 1 else "gross_minus_tare",
                "note": f"Dòng tổng hợp {number:02d}; lượng dùng trong hợp đồng do người nhập xác nhận.",
                **({"gross_kg": f"{number + 2}.125", "tare_kg": "2.000"} if number > 1 else {}),
            }
            for number in range(1, 19)
        ],
        "tax": {"mode": "inclusive", "rate": "8.00"},
        "terms": {
            "delivery": "Đã sửa: giao từng lô tại địa điểm khách hàng thử.\nGhi riêng ngày giao thực tế nếu có.",
            "packaging": "Bao thử nghiệm ghi nhãn bằng văn bản; không tạo mã QR.",
            "quality": "Các bên nhập mô tả thực tế; không có bước QC hoặc người duyệt bắt buộc.",
            "deadline": "Hoàn thành theo lịch hai đợt 2026-11-20 và 2026-11-30.",
            "responsibilities": "\n".join(
                f"{number}. Điều khoản đã sửa: hai bên phối hợp giao nhận, kiểm đếm và ghi nhận sai lệch bằng văn bản tiếng Việt."
                for number in range(1, 9)
            ),
            "additional": (
                "Lời văn tự do đã sửa: <b>không diễn giải HTML</b> & <script>không chạy</script>.\n"
                + "Nội dung dài kiểm tra xuống dòng, dấu tiếng Việt, phạm vi giao nhận và trách nhiệm do người nhập ghi. "
                * 12
                + "\nKẾT THÚC ĐIỀU KHOẢN DÀI - văn bản vẫn phải đứng trước phần đại diện ký."
            ),
        },
        "payment": {
            "method": "bank",
            "description": "Chuyển khoản theo tài khoản nhận và lịch đã sửa.\nKhông kết nối hoặc ra lệnh chuyển tiền qua ngân hàng.",
            "receiving_account": deepcopy(_COMPANY["bank_details"][0]),
            "due_on": "2026-12-05",
            "deposit_amount": "1000000.00",
            "recorded_paid_amount": "250000.25",
            "schedule": [
                {"due_on": "2026-11-20", "amount": "8000000.00", "note": "Đợt giao thứ nhất"},
                {
                    "due_on": "2026-12-05",
                    "amount": "10711000.00",
                    "note": "Đợt còn lại theo điều khoản",
                },
            ],
        },
        "source_refs": [],
    }
    return {"purchase": purchase, "sale": sale}


# Independent expected values, reviewed from the fixture arithmetic:
# purchase: 100.005*100.50 -> 10050.50; 250.125*95000.25 -> 23761937.53;
# tax = 23771988.03*8/100 -> 1901759.04; total = 25673747.07.
# sale: sum(n+.125,n=1..18)=173.250; *108000=18711000.00 including 8%;
# net=17325000.00, included tax=1386000.00. Neither deposit nor paid is subtracted.
EXPECTED_TOTALS = {
    "purchase": {
        "quantity_kg": "350.130",
        "line_amounts": ["10050.50", "23761937.53"],
        "subtotal": "23771988.03",
        "net_amount": "23771988.03",
        "tax_amount": "1901759.04",
        "grand_total": "25673747.07",
        "tax_mode": "exclusive",
        "tax_rate": "8.00",
        "amount_in_words": "Hai mươi lăm triệu sáu trăm bảy mươi ba nghìn bảy trăm bốn mươi bảy đồng và bảy phần trăm đồng",
    },
    "sale": {
        "quantity_kg": "173.250",
        "line_amounts": [
            "121500.00",
            "229500.00",
            "337500.00",
            "445500.00",
            "553500.00",
            "661500.00",
            "769500.00",
            "877500.00",
            "985500.00",
            "1093500.00",
            "1201500.00",
            "1309500.00",
            "1417500.00",
            "1525500.00",
            "1633500.00",
            "1741500.00",
            "1849500.00",
            "1957500.00",
        ],
        "subtotal": "18711000.00",
        "net_amount": "17325000.00",
        "tax_amount": "1386000.00",
        "grand_total": "18711000.00",
        "tax_mode": "inclusive",
        "tax_rate": "8.00",
        "amount_in_words": "Mười tám triệu bảy trăm mười một nghìn đồng",
    },
}

# SHA-256 over json.dumps(payload, ensure_ascii=False, sort_keys=True,
# separators=(",", ":")).encode("utf-8"); these freeze only base manual payloads.
EXPECTED_PAYLOAD_SHA256 = {
    "purchase": "9ccd30936a82c19932771b7be5d5a85810309faf6af210cb8601faf826abf270",
    "sale": "e18618205f82f31b5596a594d42dd19e88cee71d15d61a89161d99219906ccbf",
}
# SHA-256 of core DocumentSnapshot.canonical_bytes() with default v1 templates.
# Source-linked variants generated by the HTTP harness have separate manifests.
EXPECTED_DOCUMENT_SHA256 = {
    "purchase": "76ab9934f5bf3cf5e9bf6ce9114f00553b5778c6ee6689fdee7b280c5626bd73",
    "sale": "4c998c2220279435d0f6ada4d744424c7c65d4da9d9c4aabe8f25e6d69a26ef5",
}
