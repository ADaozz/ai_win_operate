"""Application entry point."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from app.actions.executor import ValidatedInputService
from app.agent.factory import DefaultRuntimeFactory
from app.common.exceptions import WindowsGuiAgentError
from app.common.logging import configure_logging, get_logger
from app.config.settings import Settings, load_settings
from app.ui.main_window import MainWindow
from app.windows.capture import WindowCapture
from app.windows.input_executor import WindowsInputExecutor
from app.windows.window_manager import WindowManager


def create_application(
    argv: Sequence[str] | None = None,
    settings: Settings | None = None,
) -> tuple[QApplication, MainWindow]:
    """Create the Qt application and its main window."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(list(argv) if argv is not None else sys.argv)

    current_settings = settings or load_settings()
    configure_logging(current_settings.log_level, current_settings.log_dir)
    window_manager = None
    capture = None
    manual_input = None
    runtime_factory = None
    try:
        window_manager = WindowManager()
        capture = WindowCapture(window_manager)
        windows_input = WindowsInputExecutor(window_manager)
        manual_input = ValidatedInputService(
            window_manager,
            windows_input,
            current_settings.allowed_hotkeys,
        )
        runtime_factory = DefaultRuntimeFactory(
            current_settings,
            window_manager,
            capture,
            windows_input,
        )
    except WindowsGuiAgentError as exc:
        get_logger(__name__).warning(
            "windows_runtime_components_unavailable",
            error=str(exc),
        )

    window = MainWindow(
        app_name=current_settings.app_name,
        window_manager=window_manager,
        window_capture=capture,
        input_executor=manual_input,
        runtime_factory=runtime_factory,
        settings=current_settings,
    )
    if runtime_factory is not None:
        window.install_emergency_stop(app, current_settings.emergency_stop_key)
    return app, window


def main() -> int:
    """Start the desktop application."""
    app, window = create_application()
    get_logger(__name__).info("application_started")
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
