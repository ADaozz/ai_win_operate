"""Typed application settings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, HttpUrl, SecretStr, computed_field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

DEFAULT_CONFIG_PATH = Path(__file__).with_name("defaults.yaml")
DEFAULT_ENV_PATH = Path(".env")
_GUI_LLM_ENV_KEYS = (
    "WGA_LLM_MODEL",
    "WGA_LLM_BASE_URL",
    "WGA_LLM_AUTH_MODE",
    "WGA_LLM_API_KEY",
)


class Settings(BaseSettings):
    """Typed application, Windows safety, and LLM gateway settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="WGA_",
        extra="ignore",
    )

    app_name: str = "Windows GUI 智能助手"
    log_level: str = "INFO"
    log_dir: Path = Field(default=Path("logs"))
    llm_provider: Literal["openai_compatible"] = "openai_compatible"
    llm_model: str = "qwen3.7-plus"
    llm_base_url: HttpUrl = HttpUrl("https://example.com/compatible-mode/v1")
    llm_auth_mode: Literal["none", "bearer"] = "bearer"
    llm_api_key: SecretStr | None = None
    llm_timeout: float = Field(default=60.0, gt=0)
    llm_response_format: Literal["json_schema", "json_object"] = "json_schema"
    llm_max_image_width: int = Field(default=1600, gt=0)
    llm_jpeg_quality: int = Field(default=85, ge=1, le=100)
    agent_max_steps: int = Field(default=30, gt=0)
    agent_action_delay_ms: int = Field(default=500, ge=0)
    agent_max_repeated_actions: int = Field(default=3, gt=0)
    agent_max_repeated_clicks: int = Field(default=5, gt=0)
    agent_repeat_recovery_attempts: int = Field(default=3, gt=0)
    agent_click_repeat_recovery_attempts: int = Field(default=8, gt=0)
    agent_frame_diff_threshold: float = Field(default=0.005, gt=0.0, le=1.0)
    agent_max_plan_actions: int = Field(default=5, ge=1, le=10)
    emergency_stop_key: str = Field(default="F8", min_length=1)
    dashscope_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="DASHSCOPE_API_KEY",
    )
    allowed_hotkeys: list[str] = Field(
        default_factory=lambda: ["CTRL+A", "CTRL+C", "CTRL+V", "CTRL+F", "ENTER"]
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_llm_api_key(self) -> SecretStr | None:
        if self.llm_api_key is not None:
            return self.llm_api_key
        return self.dashscope_api_key

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Prefer deployment configuration over YAML constructor defaults."""
        return env_settings, dotenv_settings, init_settings, file_secret_settings


def load_settings(config_path: Path = DEFAULT_CONFIG_PATH) -> Settings:
    """Load YAML defaults, allowing environment variables to override them."""
    values: dict[str, Any] = {}
    if config_path.is_file():
        with config_path.open(encoding="utf-8") as stream:
            loaded = yaml.safe_load(stream)
        if loaded is not None:
            if not isinstance(loaded, dict):
                raise ValueError(f"Settings file must contain a mapping: {config_path}")
            values = loaded
    return Settings(**values)


def save_llm_settings(
    settings: Settings,
    env_path: Path = DEFAULT_ENV_PATH,
) -> None:
    """Persist GUI-editable LLM settings without replacing other .env values."""
    values = {
        "WGA_LLM_MODEL": settings.llm_model,
        "WGA_LLM_BASE_URL": str(settings.llm_base_url),
        "WGA_LLM_AUTH_MODE": settings.llm_auth_mode,
        "WGA_LLM_API_KEY": (
            settings.llm_api_key.get_secret_value()
            if settings.llm_api_key is not None
            else ""
        ),
    }
    if any("\n" in value or "\r" in value for value in values.values()):
        raise ValueError("LLM settings cannot contain line breaks")

    existing = (
        env_path.read_text(encoding="utf-8").splitlines()
        if env_path.is_file()
        else []
    )
    output: list[str] = []
    replaced: set[str] = set()
    for line in existing:
        candidate = line.lstrip()
        matched_key = next(
            (
                key
                for key in _GUI_LLM_ENV_KEYS
                if candidate.startswith(f"{key}=")
            ),
            None,
        )
        if matched_key is None:
            output.append(line)
            continue
        if matched_key not in replaced:
            output.append(
                f"{matched_key}={json.dumps(values[matched_key], ensure_ascii=False)}"
            )
            replaced.add(matched_key)

    if output and output[-1] != "":
        output.append("")
    for key in _GUI_LLM_ENV_KEYS:
        if key not in replaced:
            output.append(f"{key}={json.dumps(values[key], ensure_ascii=False)}")
    env_path.write_text("\n".join(output) + "\n", encoding="utf-8")
