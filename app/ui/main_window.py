"""Main desktop window for manual debugging and the Milestone 6 Agent Loop."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QCoreApplication, QThread, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.actions.executor import ValidatedInputService
from app.agent.factory import RuntimeFactory
from app.agent.runtime import AgentRuntime, RuntimeEvent
from app.agent.state import AgentState, AgentStatus
from app.common.exceptions import WindowsGuiAgentError
from app.common.logging import get_logger
from app.config.settings import DEFAULT_ENV_PATH, Settings, save_llm_settings
from app.ui.agent_control_panel import AgentControlPanel
from app.ui.agent_worker import AgentWorker
from app.ui.debug_panel import ActionDebugPanel, InputService
from app.ui.log_panel import AgentLogPanel
from app.ui.runtime_monitor import RuntimeMonitor
from app.ui.screenshot_panel import CaptureService, ScreenshotPanel
from app.ui.settings_dialog import LLMSettingsDialog
from app.ui.window_picker import WindowPicker, WindowProvider
from app.windows.capture import WindowCapture
from app.windows.emergency_stop import EmergencyStopHotkey
from app.windows.input_executor import WindowsInputExecutor
from app.windows.window_manager import WindowManager

logger = get_logger(__name__)

_STATUS_LABELS = {
    AgentStatus.IDLE: "空闲",
    AgentStatus.RUNNING: "运行中",
    AgentStatus.PAUSED: "已暂停",
    AgentStatus.FINISHED: "已完成",
    AgentStatus.FAILED: "失败",
    AgentStatus.STOPPED: "已停止",
}


class MainWindow(QMainWindow):
    """Keep Qt responsive while a protocol-driven runtime controls one HWND."""

    runtime_event_received = Signal(object)
    runtime_frame_received = Signal(object)

    def __init__(
        self,
        app_name: str = "Windows GUI 智能助手",
        window_manager: WindowProvider | None = None,
        window_capture: CaptureService | None = None,
        input_executor: InputService | None = None,
        runtime_factory: RuntimeFactory | None = None,
        settings: Settings | None = None,
        settings_path: Path = DEFAULT_ENV_PATH,
    ) -> None:
        super().__init__()
        self._runtime_factory = runtime_factory
        self._settings = settings or Settings()
        self._settings_path = settings_path
        self._runtime: AgentRuntime | None = None
        self._agent_thread: QThread | None = None
        self._agent_worker: AgentWorker | None = None
        self._emergency_hotkey: EmergencyStopHotkey | None = None
        self.runtime_monitor = RuntimeMonitor(self)

        self.setWindowTitle(app_name)
        self.resize(1180, 780)

        central_widget = QWidget(self)
        central_layout = QVBoxLayout(central_widget)

        toolbar_layout = QHBoxLayout()
        toolbar_layout.addStretch(1)
        self.settings_button = QPushButton("设置", central_widget)
        self.settings_button.setToolTip("配置 Model Name、Base URL 和 API Key")
        toolbar_layout.addWidget(self.settings_button)

        target_group = QGroupBox("目标窗口", central_widget)
        target_layout = QVBoxLayout(target_group)
        self.window_picker = WindowPicker(window_manager, target_group)
        target_layout.addWidget(self.window_picker)

        task_group = QGroupBox("AI 任务", central_widget)
        task_layout = QVBoxLayout(task_group)
        self.agent_control = AgentControlPanel(task_group)
        self.agent_control.set_runtime_available(runtime_factory is not None)
        task_layout.addWidget(self.agent_control)

        capture_service = window_capture or self._create_capture_service()
        preview_group = QGroupBox("窗口预览", central_widget)
        preview_layout = QVBoxLayout(preview_group)
        self.screenshot_panel = ScreenshotPanel(capture_service, preview_group)
        preview_layout.addWidget(self.screenshot_panel)
        self.screenshot_panel.status_changed.connect(self.statusBar().showMessage)
        self.screenshot_panel.target_lost.connect(self._on_target_lost)
        self.screenshot_panel.capture_unavailable.connect(
            self._on_capture_unavailable
        )
        self.screenshot_panel.frame_captured.connect(self._on_capture_recovered)

        log_group = QGroupBox("Agent 运行记录", central_widget)
        log_layout = QVBoxLayout(log_group)
        self.agent_log = AgentLogPanel(log_group)
        log_layout.addWidget(self.agent_log)

        splitter = QSplitter(Qt.Orientation.Horizontal, central_widget)
        splitter.addWidget(preview_group)
        splitter.addWidget(log_group)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        self.debug_group = QGroupBox(
            "动作调试面板（开发工具，点击展开）",
            central_widget,
        )
        self.debug_group.setCheckable(True)
        self.debug_group.setChecked(False)
        debug_layout = QHBoxLayout(self.debug_group)
        input_service = input_executor or self._create_input_service()
        self.debug_panel = ActionDebugPanel(input_service, self.debug_group)
        self.debug_panel.setVisible(False)
        self.debug_group.toggled.connect(self.debug_panel.setVisible)
        debug_layout.addWidget(self.debug_panel)
        self.debug_panel.status_changed.connect(self.statusBar().showMessage)

        central_layout.addLayout(toolbar_layout)
        central_layout.addWidget(target_group)
        central_layout.addWidget(task_group)
        central_layout.addWidget(splitter, stretch=1)
        central_layout.addWidget(self.debug_group)
        self.setCentralWidget(central_widget)
        self.statusBar().showMessage("空闲 — 请选择窗口并输入 AI 任务")

        self.window_picker.window_selected.connect(self._on_target_selected)
        self.window_picker.selection_cleared.connect(self._on_target_cleared)
        self.settings_button.clicked.connect(self._open_settings)
        self.agent_control.start_requested.connect(self._start_agent)
        self.agent_control.pause_requested.connect(self._pause_agent)
        self.agent_control.resume_requested.connect(self._resume_agent)
        self.agent_control.stop_requested.connect(self._stop_agent)
        self.runtime_event_received.connect(self._on_runtime_event)
        self.runtime_frame_received.connect(self._on_runtime_frame)

        selected = self.window_picker.selected_window
        if selected is not None:
            self._on_target_selected(selected.hwnd)
        else:
            self.agent_control.set_target_available(False)

    @Slot()
    def _open_settings(self) -> None:
        dialog = LLMSettingsDialog(self._settings, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        old_model = self._settings.llm_model
        old_base_url = self._settings.llm_base_url
        old_auth_mode = self._settings.llm_auth_mode
        old_api_key = self._settings.llm_api_key
        self._settings.llm_model = dialog.model_name
        self._settings.llm_base_url = dialog.base_url
        self._settings.llm_api_key = dialog.api_key
        self._settings.llm_auth_mode = (
            "bearer" if dialog.api_key.get_secret_value() else "none"
        )
        try:
            save_llm_settings(self._settings, self._settings_path)
        except (OSError, ValueError) as exc:
            self._settings.llm_model = old_model
            self._settings.llm_base_url = old_base_url
            self._settings.llm_auth_mode = old_auth_mode
            self._settings.llm_api_key = old_api_key
            logger.exception("llm_settings_save_failed", error_type=type(exc).__name__)
            QMessageBox.critical(self, "保存失败", f"无法保存模型配置：{exc}")
            return
        self.statusBar().showMessage(
            f"模型配置已保存：{self._settings.llm_model}（下次任务生效）"
        )

    def install_emergency_stop(
        self,
        application: QCoreApplication,
        key: str = "F8",
    ) -> bool:
        """Reserve a Windows global hotkey; failure leaves normal Stop available."""
        try:
            hotkey = EmergencyStopHotkey(self._emergency_stop, key)
            hotkey.install(application)
        except WindowsGuiAgentError as exc:
            logger.warning("emergency_stop_hotkey_unavailable", error=str(exc))
            self.statusBar().showMessage(f"警告：{exc}")
            self.agent_control.shortcut_label.setText(
                "F8 注册失败：请使用停止按钮"
            )
            self.runtime_monitor.set_emergency_stop_available(False)
            return False
        self._emergency_hotkey = hotkey
        self.runtime_monitor.set_emergency_stop_available(True)
        return True

    @Slot(int)
    def _on_target_selected(self, hwnd: int) -> None:
        self.debug_panel.set_target_window(hwnd)
        self.agent_control.set_target_available(True)
        self.screenshot_panel.set_target_window(hwnd)

    @Slot()
    def _on_target_cleared(self) -> None:
        self.screenshot_panel.clear_target_window()
        self.debug_panel.clear_target_window()
        self.agent_control.set_target_available(False)

    @Slot(int)
    def _on_target_lost(self, _hwnd: int) -> None:
        self.debug_panel.clear_target_window()
        self.agent_control.set_target_available(False)
        self.statusBar().showMessage("目标窗口已关闭，请刷新窗口列表")

    @Slot(int, str)
    def _on_capture_unavailable(self, _hwnd: int, _reason: str) -> None:
        self.agent_control.set_target_available(False)
        self.statusBar().showMessage(
            "该窗口无法获得有效截图，已阻止发送给 AI；请选择其他窗口"
        )

    @Slot(int, int)
    def _on_capture_recovered(self, _width: int, _height: int) -> None:
        if self.window_picker.selected_window is not None:
            self.agent_control.set_target_available(True)

    @Slot(str)
    def _start_agent(self, task: str) -> None:
        selected = self.window_picker.selected_window
        if (
            selected is None
            or self._runtime_factory is None
            or (self._agent_thread is not None and self._agent_thread.isRunning())
        ):
            return

        self.agent_log.clear()
        self.agent_control.reset_runtime_display()
        self.runtime_monitor.begin()
        self.screenshot_panel.set_periodic_refresh_enabled(False)
        self.window_picker.setEnabled(False)
        self.debug_group.setEnabled(False)
        try:
            runtime = self._runtime_factory.create(
                task,
                selected.hwnd,
                self.runtime_event_received.emit,
                self.runtime_frame_received.emit,
            )
        except Exception as exc:
            logger.exception(
                "agent_runtime_creation_failed",
                error_type=type(exc).__name__,
            )
            self.runtime_monitor.hide()
            self._restore_idle_controls()
            self.statusBar().showMessage("无法创建 Agent Runtime")
            return

        thread = QThread(self)
        worker = AgentWorker(runtime)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._on_agent_completed)
        worker.completed.connect(thread.quit)
        worker.completed.connect(worker.deleteLater)
        thread.finished.connect(self._on_agent_thread_finished)
        thread.finished.connect(thread.deleteLater)

        self._runtime = runtime
        self._agent_thread = thread
        self._agent_worker = worker
        self.agent_control.set_status(AgentStatus.RUNNING)
        thread.start()

    @Slot()
    def _pause_agent(self) -> None:
        if self._runtime is not None and self._runtime.pause():
            self.agent_control.set_status(AgentStatus.PAUSED)

    @Slot()
    def _resume_agent(self) -> None:
        if self._runtime is not None and self._runtime.resume():
            self.agent_control.set_status(AgentStatus.RUNNING)

    @Slot()
    def _stop_agent(self) -> None:
        if self._runtime is not None:
            self._runtime.stop()

    def _emergency_stop(self) -> None:
        if self._runtime is not None and self._runtime.stop():
            self.statusBar().showMessage("F8 紧急停止已触发；后续输入已阻止")

    @Slot(object)
    def _on_runtime_event(self, event: object) -> None:
        if not isinstance(event, RuntimeEvent):
            return
        self.agent_log.append_event(event)
        self.agent_control.update_runtime_event(event)
        self.runtime_monitor.update_event(event)
        status = _STATUS_LABELS[event.status]
        self.statusBar().showMessage(
            f"{status} — 步骤 {event.step}/{event.max_steps} — F8：紧急停止"
        )

    @Slot(object)
    def _on_runtime_frame(self, frame: object) -> None:
        if isinstance(frame, Image.Image):
            self.screenshot_panel.display_image(frame)

    @Slot(object)
    def _on_agent_completed(self, state: object) -> None:
        self.agent_control.set_runtime_available(False)
        if isinstance(state, AgentState):
            self.agent_control.show_final_state(state)
            self.runtime_monitor.show_final(state)
            self.statusBar().showMessage(
                f"{_STATUS_LABELS[state.status]} — {state.message} — "
                f"步骤 {state.step}/{state.max_steps}"
            )
        self._restore_idle_controls()

    @Slot()
    def _on_agent_thread_finished(self) -> None:
        self._agent_thread = None
        self._agent_worker = None
        self._runtime = None
        self.agent_control.set_runtime_available(self._runtime_factory is not None)

    def _restore_idle_controls(self) -> None:
        self.window_picker.setEnabled(True)
        self.debug_group.setEnabled(True)
        self.screenshot_panel.set_periodic_refresh_enabled(True)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._runtime is not None:
            self._runtime.stop()
        thread = self._agent_thread
        if thread is not None and thread.isRunning() and not thread.wait(5000):
            logger.error("agent_thread_did_not_stop_before_close")
            event.ignore()
            self.statusBar().showMessage("Agent 仍在停止中，请稍后再次关闭")
            return
        application = QCoreApplication.instance()
        if self._emergency_hotkey is not None and application is not None:
            self._emergency_hotkey.close(application)
            self._emergency_hotkey = None
        self.runtime_monitor.close()
        super().closeEvent(event)

    def _create_capture_service(self) -> WindowCapture | None:
        provider = self.window_picker.window_manager
        if not isinstance(provider, WindowManager):
            return None
        try:
            return WindowCapture(provider)
        except WindowsGuiAgentError as exc:
            logger.warning("window_capture_unavailable", error=str(exc))
            return None

    def _create_input_service(self) -> ValidatedInputService | None:
        provider = self.window_picker.window_manager
        if not isinstance(provider, WindowManager):
            return None
        try:
            input_executor = WindowsInputExecutor(provider)
            return ValidatedInputService(provider, input_executor)
        except WindowsGuiAgentError as exc:
            logger.warning("input_executor_unavailable", error=str(exc))
            return None
