from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from app.ui.screenshot_panel import ScreenshotPanel
from app.common.exceptions import (
    BlackWindowFrameError,
    MinimizedWindowCaptureError,
    WindowNotFoundError,
)


class FakeCaptureService:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def capture(self, hwnd: int) -> Image.Image:
        self.calls.append(hwnd)
        return Image.new("RGB", (320, 200), (20, 40, 60))


class MissingWindowCaptureService:
    def capture(self, hwnd: int) -> Image.Image:
        raise WindowNotFoundError(f"Window no longer exists: HWND {hwnd}")


class BlackWindowCaptureService:
    def capture(self, hwnd: int) -> Image.Image:
        raise BlackWindowFrameError(
            f"Target window returned an unusable all-black frame: HWND {hwnd}"
        )


class MinimizedWindowCaptureService:
    def capture(self, hwnd: int) -> Image.Image:
        raise MinimizedWindowCaptureError(
            f"Cannot capture minimized window: HWND {hwnd}"
        )


def test_panel_captures_selected_hwnd_and_saves_preview(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    service = FakeCaptureService()
    panel = ScreenshotPanel(service)

    panel.set_target_window(987)

    assert panel.target_hwnd == 987
    assert panel.current_image is not None
    assert panel.current_image.size == (320, 200)
    assert service.calls == [987]
    assert panel.save_button.isEnabled()

    destination = panel.save_screenshot(tmp_path / "capture.png")
    assert destination == tmp_path / "capture.png"
    assert destination.is_file()

    panel.clear_target_window()
    assert panel.target_hwnd is None
    panel.close()
    app.processEvents()


def test_panel_without_capture_service_shows_unavailable_state() -> None:
    app = QApplication.instance() or QApplication([])
    panel = ScreenshotPanel(None)

    panel.set_target_window(123)

    assert panel.current_image is None
    assert panel.preview.text() == "窗口截图功能不可用"
    assert not panel.capture_button.isEnabled()

    panel.close()
    app.processEvents()


def test_preview_scaling_uses_physical_pixels_on_hidpi_display() -> None:
    app = QApplication.instance() or QApplication([])
    source = QPixmap(800, 600)

    scaled = ScreenshotPanel._scale_pixmap_for_preview(
        source,
        QSize(400, 300),
        2.0,
    )

    assert scaled.size() == QSize(800, 600)
    assert scaled.devicePixelRatio() == 2.0
    assert scaled.deviceIndependentSize() == QSize(400, 300)
    app.processEvents()


def test_closed_target_stops_periodic_capture_and_emits_once() -> None:
    app = QApplication.instance() or QApplication([])
    panel = ScreenshotPanel(MissingWindowCaptureService())
    lost: list[int] = []
    panel.target_lost.connect(lost.append)

    panel.set_target_window(765)

    assert lost == [765]
    assert panel.target_hwnd is None
    assert not panel._refresh_timer.isActive()
    assert panel.preview.text() == "目标窗口已关闭，请刷新窗口列表"
    assert not panel.capture_button.isEnabled()
    panel.close()
    app.processEvents()


def test_black_target_stops_refresh_and_reports_capture_unavailable() -> None:
    app = QApplication.instance() or QApplication([])
    panel = ScreenshotPanel(BlackWindowCaptureService())
    unavailable: list[tuple[int, str]] = []
    panel.capture_unavailable.connect(
        lambda hwnd, reason: unavailable.append((hwnd, reason))
    )

    panel.set_target_window(864)

    assert len(unavailable) == 1
    assert unavailable[0][0] == 864
    assert "all-black" in unavailable[0][1]
    assert panel.target_hwnd == 864
    assert panel.current_image is None
    assert not panel._refresh_timer.isActive()
    assert panel.preview.text() == "此窗口无法捕获有效画面（全黑）"
    assert not panel.save_button.isEnabled()
    panel.close()
    app.processEvents()


def test_minimized_target_pauses_periodic_refresh() -> None:
    app = QApplication.instance() or QApplication([])
    panel = ScreenshotPanel(MinimizedWindowCaptureService())

    panel.set_target_window(963)

    assert panel.target_hwnd == 963
    assert not panel._refresh_timer.isActive()
    assert "已最小化" in panel.preview.text()
    assert panel.capture_button.isEnabled()
    assert not panel.save_button.isEnabled()
    panel.close()
    app.processEvents()
