from app.domain.terminology import (
    build_terminology_hint,
    find_matched_terminology,
    load_terminology,
    normalize_for_match,
    postprocess_func,
)


def test_normalize_for_match():
    assert normalize_for_match("Đo kiểm chất lượng") == "do kiem chat luong"
    assert normalize_for_match("ĐKCL") == "dkcl"
    assert normalize_for_match("Bưu điện Việt Nam") == "buu dien viet nam"


def test_find_matched_terminology():
    terms = {
        "cod": "Dịch vụ phát hàng thu tiền hộ",
        "ems": "Chuyển phát nhanh",
        "đkcl": "Đo kiểm chất lượng",
    }
    # Match exact term in sentence
    res = find_matched_terminology("Cho tôi hỏi về quy trình giao COD tại bưu cục", terms)
    assert "cod" in res
    assert "ems" not in res

    # Match case-insensitive and Vietnamese accents
    res = find_matched_terminology("Công tác ĐKCL năm nay thế nào?", terms)
    assert "đkcl" in res

    # Word boundary: 'coder' or 'code' should not match 'cod'
    res_no_match = find_matched_terminology("Tôi là coder lập trình", terms)
    assert "cod" not in res_no_match


def test_build_terminology_hint():
    matched = {"ems": "Chuyển phát nhanh", "cod": "Thu tiền hộ"}
    hint = build_terminology_hint(matched)
    assert "EMS: Chuyển phát nhanh" in hint
    assert "COD: Thu tiền hộ" in hint
    assert build_terminology_hint({}) == ""


def test_postprocess_func_numbers_and_math():
    # 1. Thousand separators with space or narrow space
    text1 = "Giá cước là 125 000 đồng cho bưu gửi 1 500 000 đ."
    assert postprocess_func(text1) == "Giá cước là 125.000 đồng cho bưu gửi 1.500.000 đ."

    text_narrow = "Phí COD: 35\u202f000 đ."
    assert postprocess_func(text_narrow) == "Phí COD: 35.000 đ."

    # 2. LaTeX block math: \[ ... \] -> $$ ... $$
    latex_block = r"Công thức tính cước: \[ C = a \times b \]"
    assert postprocess_func(latex_block) == r"Công thức tính cước: $$ C = a \times b $$"

    # 3. LaTeX inline math: \( ... \) -> $ ... $
    latex_inline = r"Giả sử \( x = 10 \) và \( y = 20 \)."
    assert postprocess_func(latex_inline) == r"Giả sử $ x = 10 $ và $ y = 20 $."

    # 4. Bảo vệ số điện thoại / hotline không bị đổi dấu cách thành dấu chấm tiền tệ
    hotline_text = "Liên hệ hotline 1900 545 481 hoặc tổng đài 024 3768 4969 để được giải đáp."
    assert postprocess_func(hotline_text) == "Liên hệ hotline 1900 545 481 hoặc tổng đài 024 3768 4969 để được giải đáp."


def test_load_terminology():
    terms = load_terminology("terminology.json")
    assert isinstance(terms, dict)
    assert "ems" in terms
    assert "cod" in terms
    assert "đkcl" in terms
