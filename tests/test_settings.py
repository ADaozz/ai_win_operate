from pathlib import Path

from pydantic import HttpUrl, SecretStr

from app.config.settings import Settings, load_settings, save_llm_settings


def test_load_settings_from_yaml(tmp_path: Path, monkeypatch) -> None:
    config_file = tmp_path / "settings.yaml"
    config_file.write_text(
        "app_name: Test Agent\nlog_level: DEBUG\nlog_dir: test-logs\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("WGA_APP_NAME", raising=False)

    settings = load_settings(config_file)

    assert settings.app_name == "Test Agent"
    assert settings.log_level == "DEBUG"
    assert settings.log_dir == Path("test-logs")


def test_environment_overrides_yaml(tmp_path: Path, monkeypatch) -> None:
    config_file = tmp_path / "settings.yaml"
    config_file.write_text("app_name: YAML Agent\n", encoding="utf-8")
    monkeypatch.setenv("WGA_APP_NAME", "Environment Agent")

    settings = load_settings(config_file)

    assert settings.app_name == "Environment Agent"


def test_dashscope_key_is_loaded_as_secret(tmp_path: Path, monkeypatch) -> None:
    config_file = tmp_path / "settings.yaml"
    config_file.write_text(
        "llm_model: test-model\n"
        "llm_base_url: https://example.test/compatible-mode/v1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-secret-value")

    settings = load_settings(config_file)

    assert settings.llm_model == "test-model"
    assert str(settings.llm_base_url) == "https://example.test/compatible-mode/v1"
    assert settings.dashscope_api_key is not None
    assert settings.dashscope_api_key.get_secret_value() == "test-secret-value"
    assert "test-secret-value" not in repr(settings)


def test_allowed_hotkeys_load_from_yaml(tmp_path: Path) -> None:
    config_file = tmp_path / "settings.yaml"
    config_file.write_text(
        "allowed_hotkeys:\n  - CTRL+A\n  - CTRL+F\n",
        encoding="utf-8",
    )

    settings = load_settings(config_file)

    assert settings.allowed_hotkeys == ["CTRL+A", "CTRL+F"]


def test_llm_timeout_and_response_format_load_from_yaml(tmp_path: Path) -> None:
    config_file = tmp_path / "settings.yaml"
    config_file.write_text(
        "llm_timeout: 12.5\nllm_response_format: json_object\n",
        encoding="utf-8",
    )

    settings = load_settings(config_file)

    assert settings.llm_timeout == 12.5
    assert settings.llm_response_format == "json_object"


def test_agent_runtime_limits_load_from_yaml(tmp_path: Path) -> None:
    config_file = tmp_path / "settings.yaml"
    config_file.write_text(
        "agent_max_steps: 12\n"
        "agent_action_delay_ms: 250\n"
        "agent_max_repeated_actions: 2\n"
        "agent_max_repeated_clicks: 6\n"
        "agent_repeat_recovery_attempts: 2\n"
        "agent_click_repeat_recovery_attempts: 9\n"
        "agent_frame_diff_threshold: 0.05\n"
        "agent_max_plan_actions: 4\n"
        "emergency_stop_key: F9\n",
        encoding="utf-8",
    )

    settings = load_settings(config_file)

    assert settings.agent_max_steps == 12
    assert settings.agent_action_delay_ms == 250
    assert settings.agent_max_repeated_actions == 2
    assert settings.agent_max_repeated_clicks == 6
    assert settings.agent_repeat_recovery_attempts == 2
    assert settings.agent_click_repeat_recovery_attempts == 9
    assert settings.agent_frame_diff_threshold == 0.05
    assert settings.agent_max_plan_actions == 4
    assert settings.emergency_stop_key == "F9"


def test_save_llm_settings_updates_env_without_removing_other_values(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "WGA_LOG_LEVEL=DEBUG\n"
        "WGA_LLM_MODEL=old-model\n"
        "WGA_LLM_API_KEY=old-key\n",
        encoding="utf-8",
    )
    settings = Settings.model_construct(
        llm_model="new model",
        llm_base_url=HttpUrl("http://127.0.0.1:8000/v1"),
        llm_auth_mode="bearer",
        llm_api_key=SecretStr("new-secret"),
    )

    save_llm_settings(settings, env_file)

    saved = env_file.read_text(encoding="utf-8")
    assert "WGA_LOG_LEVEL=DEBUG" in saved
    assert 'WGA_LLM_MODEL="new model"' in saved
    assert 'WGA_LLM_BASE_URL="http://127.0.0.1:8000/v1"' in saved
    assert 'WGA_LLM_AUTH_MODE="bearer"' in saved
    assert 'WGA_LLM_API_KEY="new-secret"' in saved
    assert "old-key" not in saved
