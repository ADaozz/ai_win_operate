"""Dialog for editing the OpenAI-compatible model connection."""

from __future__ import annotations

from pydantic import HttpUrl, SecretStr, ValidationError
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from app.config.settings import Settings


class LLMSettingsDialog(QDialog):
    """Collect and validate the three connection values exposed by the GUI."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("模型设置")
        self.setModal(True)
        self.setMinimumWidth(520)

        self.model_input = QLineEdit(settings.llm_model, self)
        self.model_input.setPlaceholderText("例如：qwen3.7-plus")
        self.base_url_input = QLineEdit(str(settings.llm_base_url), self)
        self.base_url_input.setPlaceholderText("例如：http://127.0.0.1:8000/v1")
        current_key = settings.resolved_llm_api_key
        self.api_key_input = QLineEdit(
            current_key.get_secret_value() if current_key is not None else "",
            self,
        )
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("无鉴权接口可留空")

        self.show_api_key = QCheckBox("显示 API Key", self)
        self.show_api_key.toggled.connect(self._set_api_key_visible)

        form = QFormLayout()
        form.addRow("Model Name：", self.model_input)
        form.addRow("Base URL：", self.base_url_input)
        form.addRow("API Key：", self.api_key_input)
        form.addRow("", self.show_api_key)

        note = QLabel("保存后将从下一次 AI 任务开始使用新配置。", self)
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            Qt.Orientation.Horizontal,
            self,
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self._validate_and_accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(self.buttons)

    @property
    def model_name(self) -> str:
        return self.model_input.text().strip()

    @property
    def base_url(self) -> HttpUrl:
        return HttpUrl(self.base_url_input.text().strip())

    @property
    def api_key(self) -> SecretStr:
        return SecretStr(self.api_key_input.text())

    def _set_api_key_visible(self, visible: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        self.api_key_input.setEchoMode(mode)

    def _validate_and_accept(self) -> None:
        if not self.model_name:
            QMessageBox.warning(self, "配置无效", "Model Name 不能为空。")
            self.model_input.setFocus()
            return
        try:
            self.base_url
        except ValidationError:
            QMessageBox.warning(
                self,
                "配置无效",
                "Base URL 必须是有效的 http:// 或 https:// 地址。",
            )
            self.base_url_input.setFocus()
            return
        self.accept()
