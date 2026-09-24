from app.services.date_extractor import extract


def test_ocop_duration():
    text = """
    GIẤY CHỨNG NHẬN OCOP
    Ban hành kèm theo Quyết định số 4144/QĐ-UBND ngày 25 tháng 12 năm 2024.
    Có giá trị 36 tháng kể từ ngày ký ban hành.
    """
    out = extract(text)
    assert out["decision_date"] == "2024-12-25"
    assert out["issue_date"] == "2024-12-25"
    assert out["expiry_date"] == "2027-12-25"


def test_iso_validity_pair():
    text = "Giấy chứng nhận có giá trị từ ngày 17/3/2025 đến 16/3/2028"
    out = extract(text)
    assert out["valid_from"] == "2025-03-17"
    assert out["expiry_date"] == "2028-03-16"


def test_lab_report_excluded():
    text = "PHIẾU KẾT QUẢ THỬ NGHIỆM | TEST REPORT | Ngày nhận mẫu 06/01/2026 | Testing duration 07/01/2026 31/01/2026"
    out = extract(text)
    assert out["issue_date"] is None
    assert out["expiry_date"] is None
