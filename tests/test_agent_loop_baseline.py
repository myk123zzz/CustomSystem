from core.loop import AgentLoop, MAX_HISTORY_MESSAGES, MAX_TOOL_RESULT_CHARS
from core.persistence import SessionStore


def test_tool_results_are_truncated_to_budget():
    messages = [
        {"role": "tool", "tool_call_id": "1", "content": "x" * (MAX_TOOL_RESULT_CHARS + 50)}
    ]

    result = AgentLoop._apply_tool_result_budget(messages)

    assert len(result[0]["content"]) < MAX_TOOL_RESULT_CHARS + 100
    assert "已截断" in result[0]["content"]


def test_history_snip_preserves_system_and_recent_messages():
    messages = [{"role": "system", "content": "system"}]
    messages.extend(
        {"role": "user" if i % 2 == 0 else "assistant", "content": str(i)}
        for i in range(MAX_HISTORY_MESSAGES + 20)
    )

    result = AgentLoop._snip_history(messages)

    assert result[0] == {"role": "system", "content": "system"}
    assert len(result) <= MAX_HISTORY_MESSAGES
    assert result[1]["role"] == "user"


def test_orphan_tool_results_are_removed():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "tool", "tool_call_id": "missing", "content": "orphan"},
    ]

    result = AgentLoop._drop_orphan_tool_results(messages)

    assert result == [{"role": "system", "content": "system"}]


async def test_history_refreshes_messages_written_by_other_execution_paths(tmp_path):
    store = SessionStore(tmp_path)
    loop = AgentLoop(None, None, str(tmp_path), session_store=store)
    await store.save_history("s1", [{"role": "user", "content": "第一条"}])
    assert (await loop._get_history("s1"))[-1]["content"] == "第一条"

    await store.save_history("s1", [
        {"role": "user", "content": "第一条"},
        {"role": "assistant", "content": "FastPath 回复"},
    ])

    assert (await loop._get_history("s1"))[-1]["content"] == "FastPath 回复"
