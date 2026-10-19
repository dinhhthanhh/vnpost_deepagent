import pytest

from app.calculator import _vn_numbers
from app.fastpath import local_answer


@pytest.mark.parametrize("q,expect", [
    ("1+1=?", "= **2**"), ("1+1=", "= **2**"), ("3002x2", "= **6004**"), ("3002 x 2 = ?", "= **6004**"),
    ("1+4", "= **5**"), ("Tính giúp tôi 125000 + 35000 đồng và nêu cách tính.", "= **160000**"),
    ("125.000 + 35.000", "= **160000**"), ("1.500 + 500", "= **2000**"), ("1.500.000 + 500.000", "= **2000000**"),
    ("10/4", "= **2,5**"), ("2,5 + 1", "= **3,5**"), ("3.14 + 1", "= **4,14**"),
    ("2^10", "= **1024**"), ("(2+3)*4 bằng bao nhiêu", "= **20**"), ("3002×2", "= **6004**"), ("10:4", "= **2,5**"),
])
def test_calc(q, expect):
    a = local_answer(q)
    assert a and a.kind == "calc" and expect in a.text, (q, a)

@pytest.mark.parametrize("q", [
    "1+!", "12/10/2025", "quy trình nghỉ phép", "cước EMS 2kg + phụ phí là bao nhiêu",
    "so sánh 1+1 và 2+2", "tính phí chuyển phát", "số điện thoại 0912345678", "5", "1+1 theo quy định số 12",
    "1/0", "9**99",
])
def test_not_calc(q):
    assert local_answer(q) is None, q

def test_chitchat():
    assert "Mipo" in local_answer("xin chào", chitchat=True).text
    assert "Không có gì" in local_answer("ok cảm ơn", chitchat=True).text
    assert "Tạm biệt" in local_answer("tạm biệt", chitchat=True).text

def test_vn_numbers_edge_cases():
    # 3.141 có 3 chữ số sau dấu chấm, theo quy ước số Việt Nam _vn_numbers hiểu là 3141
    assert _vn_numbers("3.141") == "3141"
    # 3.14 có 2 chữ số sau chấm nên giữ nguyên số thập phân
    assert _vn_numbers("3.14") == "3.14"
    # 1.500.000 có nhiều cụm chấm nghìn
    assert _vn_numbers("1.500.000") == "1500000"
    # 2,5 dấu phẩy thành dấu chấm
    assert _vn_numbers("2,5") == "2.5"
    # 0.500 thành 0500 gây SyntaxError trong safe_calculate, try_arithmetic sẽ trả None để LLM xử lý
    assert local_answer("0.500 + 1") is None


def test_current_date_is_a_local_answer():
    answer = local_answer("hôm nay là ngày bao nhiêu")
    assert answer and answer.kind == "date"
    assert "Hôm nay là ngày" in answer.text

    # Các biến thể hôm nay
    ans_today_gi = local_answer("hôm nay là ngày gì")
    assert ans_today_gi and ans_today_gi.kind == "date"
    assert "Hôm nay là ngày" in ans_today_gi.text

    ans_today_thu = local_answer("hôm nay thứ mấy")
    assert ans_today_thu and ans_today_thu.kind == "date"
    assert "Hôm nay là ngày" in ans_today_thu.text

    # Ngày mai
    ans_tomorrow = local_answer("ngày mai là ngày bao nhiêu")
    assert ans_tomorrow and ans_tomorrow.kind == "date"
    assert "Ngày mai là ngày" in ans_tomorrow.text

    ans_tomorrow_may = local_answer("mai là ngày mấy")
    assert ans_tomorrow_may and ans_tomorrow_may.kind == "date"
    assert "Ngày mai là ngày" in ans_tomorrow_may.text

    # Hôm qua
    ans_yesterday = local_answer("hôm qua là ngày mấy")
    assert ans_yesterday and ans_yesterday.kind == "date"
    assert "Hôm qua là ngày" in ans_yesterday.text

    # Giờ hiện tại
    ans_time = local_answer("bây giờ là mấy giờ")
    assert ans_time and ans_time.kind == "date"
    assert "Bây giờ là" in ans_time.text