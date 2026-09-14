from feishu_bot import _normalize_confirmation


def test_normalize_confirmation_accepts_only_whitespace_variants():
    assert _normalize_confirmation("确认提交") == "确认提交"
    assert _normalize_confirmation("确认 提交") == "确认提交"
    assert _normalize_confirmation(" 确认\n提交 ") == "确认提交"


def test_normalize_confirmation_does_not_accept_extra_words():
    assert _normalize_confirmation("请确认提交") == "请确认提交"
    assert _normalize_confirmation("确认提交全部订单") == "确认提交全部订单"
    assert _normalize_confirmation("同意") == "同意"
