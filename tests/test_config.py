from pathlib import Path

from agent0.config import load_config


def test_config_reads_toml_and_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    toml = tmp_path / "agent.toml"
    toml.write_text(
        "\n".join(
            [
                'model = "deepseek-flash"',
                'base_url = "https://example.test"',
                "context_window = 1000000",
                'thinking = "enabled"',
                "bash_timeout_seconds = 90",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-env")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://from-env.test")
    config = load_config(toml, cwd=tmp_path)
    assert config.model == "deepseek-flash"
    assert config.api_key == "sk-from-env"
    assert config.base_url == "https://from-env.test"
    assert config.thinking == "enabled"
    assert config.bash_timeout_seconds == 90


def test_dotenv_does_not_override_real_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-already-set")
    (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=sk-from-file\n", encoding="utf-8")
    toml = tmp_path / "agent.toml"
    toml.write_text('model = "deepseek-flash"\n', encoding="utf-8")
    config = load_config(toml, cwd=tmp_path)
    assert config.api_key == "sk-already-set"
