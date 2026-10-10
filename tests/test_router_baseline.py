from core.intent_router import Intent, _classify_layer_1_2


def test_greeting_is_classified_without_entities():
    intent, entities = _classify_layer_1_2("你好")

    assert intent is Intent.GREETING
    assert entities == {}


def test_order_id_next_to_chinese_is_extracted():
    intent, entities = _classify_layer_1_2("帮我查订单88001")

    assert intent is Intent.ORDER_QUERY
    assert entities["order_id"] == "88001"


def test_five_digits_inside_longer_number_are_not_order_id():
    _intent, entities = _classify_layer_1_2("手机号是13800138000")

    assert "order_id" not in entities


def test_complaint_has_priority_over_refund_words():
    intent, _ = _classify_layer_1_2("一直不给我退款，我要投诉")

    assert intent is Intent.COMPLAINT


def test_policy_question_and_action_request_are_different():
    policy_intent, _ = _classify_layer_1_2("怎么退款")
    action_intent, _ = _classify_layer_1_2("帮我退款")

    assert policy_intent is Intent.FAQ
    assert action_intent is Intent.AFTER_SALES


def test_unknown_message_falls_back_to_complex():
    intent, entities = _classify_layer_1_2("这个情况有点奇怪，麻烦综合判断一下")

    assert intent is Intent.COMPLEX
    assert entities == {}

