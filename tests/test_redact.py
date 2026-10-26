from agent0.agent.loop import AgentLoop
from agent0.providers.base import ProviderResponse
from agent0.providers.fake import FakeProvider
from agent0.redact import redact_obj, redact_secrets


def test_redact_only_exact_key_value() -> None:
    key = "sk-exact-secret-key-value"
    reasoning = f"I considered {key} and also sk-other-token-zzzz"
    out = redact_secrets(reasoning, key)
    assert key not in out
    assert "sk-other-token-zzzz" in out
    assert out.count("[REDACTED]") == 1


def test_redact_empty_key_leaves_text() -> None:
    text = "sk-looks-like-a-key-but-is-reasoning"
    assert redact_secrets(text, "") == text


def test_events_never_contain_api_key(config, executor, tools) -> None:
    leaked = []
    key = config.api_key

    def listener(event_type: str, payload: dict) -> None:
        leaked.append((event_type, payload))

    loop = AgentLoop(
        config=config,
        provider=FakeProvider(
            [
                ProviderResponse(
                    content=f"do not store {key}",
                    reasoning_content="r",
                    tool_calls=[],
                    finish_reason="stop",
                )
            ]
        ),
        executor=executor,
        tools=tools,
        listeners=[listener],
    )
    loop.emit("message_end", {"note": f"key={key}"})
    assert key not in str(leaked)
    assert "[REDACTED]" in str(leaked)


def test_redact_obj_nested() -> None:
    key = "sk-nestedkeyvalue"
    obj = {"reasoning_content": f"keep sk-other and hide {key}"}
    out = redact_obj(obj, key)
    assert key not in str(out)
    assert "sk-other" in str(out)
