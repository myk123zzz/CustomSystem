from core.trace import RequestTrace, TraceStore


def test_trace_store_returns_serializable_recent_items():
    store = TraceStore(maxlen=2)
    store.append(RequestTrace("s1", "fast_path", "greeting"))
    store.append(RequestTrace("s1", "presales", "product", ["rag_search"], 2, 30))

    traces = store.recent()

    assert len(traces) == 2
    assert traces[-1]["tools_called"] == ["rag_search"]
    assert traces[-1]["llm_calls"] == 2
    assert traces[-1]["request_id"]

