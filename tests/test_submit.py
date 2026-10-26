from agent0.agent.loop import AgentLoop
from agent0.providers.base import ProviderResponse, ToolCallRequest
from agent0.providers.fake import FakeProvider
from agent0.tools.registry import headless_tools


def test_submit_alone_stops_loop(config, executor) -> None:
    tools = headless_tools(config)
    provider = FakeProvider(
        [
            ProviderResponse(
                "",
                "done thinking",
                [ToolCallRequest("s1", "submit", '{"summary":"fixed"}')],
                "tool_calls",
            ),
            ProviderResponse("should-not-run", "r2", [], "stop"),
        ]
    )
    loop = AgentLoop(config=config, provider=provider, executor=executor, tools=tools)
    answer = loop.run("finish")
    assert answer == "fixed"
    assert len(provider.requests) == 1
    result = [m for m in loop.messages if getattr(m, "name", "") == "submit"][0]
    assert result.terminate is True
    assert result.content == "fixed"


def test_submit_with_read_does_not_stop(config, executor, tmp_path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    tools = headless_tools(config)
    provider = FakeProvider(
        [
            ProviderResponse(
                "",
                "both",
                [
                    ToolCallRequest("c1", "read", '{"path":"a.txt"}'),
                    ToolCallRequest("s1", "submit", '{"summary":"done"}'),
                ],
                "tool_calls",
            ),
            ProviderResponse("continued", "r2", [], "stop"),
        ]
    )
    loop = AgentLoop(config=config, provider=provider, executor=executor, tools=tools)
    assert loop.run("go") == "continued"
    assert len(provider.requests) == 2
