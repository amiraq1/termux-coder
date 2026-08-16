from termux_coder.core.session import SessionStore


def test_message_roundtrip(tmp_path):
    store = SessionStore(tmp_path / "s.db")
    sid = store.create("/w", "m")
    msgs = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "1", "type": "function",
                 "function": {"name": "read_file", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "1", "content": "ok"},
        {"role": "assistant", "content": "done"},
    ]
    for i, m in enumerate(msgs):
        store.save_message(sid, i, m)

    loaded = store.load_messages(sid)
    assert loaded[0] == {"role": "user", "content": "hi"}
    assert loaded[1]["tool_calls"][0]["function"]["name"] == "read_file"
    assert loaded[2]["tool_call_id"] == "1"
    assert loaded[3]["content"] == "done"


def test_dangling_tail_is_sanitized(tmp_path):
    store = SessionStore(tmp_path / "s.db")
    sid = store.create("/w", "m")
    store.save_message(sid, 0, {"role": "user", "content": "hi"})
    # محاكاة قتل الوكيل وسط جولة:
    store.save_message(sid, 1, {
        "role": "assistant", "content": "",
        "tool_calls": [{"id": "9", "type": "function",
                        "function": {"name": "run_command", "arguments": "{}"}}],
    })
    loaded = store.load_messages(sid)
    assert len(loaded) == 1
    assert loaded[0]["role"] == "user"


def test_state_roundtrip(tmp_path):
    from termux_coder.core.context import SessionState

    store = SessionStore(tmp_path / "s.db")
    sid = store.create("/w", "m")
    st = SessionState(read_files={"a.py", "b.py"}, applied_patches=["a.py"],
                      todos=[{"text": "x", "done": True}])
    store.save_state(sid, st)
    back = store.load_state(sid)
    assert back.read_files == {"a.py", "b.py"}
    assert back.applied_patches == ["a.py"]
    assert back.todos[0]["done"] is True


def test_recent_ordering(tmp_path):
    store = SessionStore(tmp_path / "s.db")
    a = store.create("/w", "m", "first")
    b = store.create("/w", "m", "second")
    store.touch(a)  # الأقدم يُلمس → يصبح الأحدث
    recent = store.list_recent()
    assert recent[0]["id"] == a
    assert recent[1]["id"] == b
