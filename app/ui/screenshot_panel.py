"""Target-window screenshot preview and save controls."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from PIL import Image
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.common.exceptions import (
    BlackWindowFrameError,
    MinimizedWindowCaptureError,
    WindowNotFoundError,
    WindowsGuiAgentError,
)
from app.common.logging import get_logger

logger = get_logger(__name__)


class CaptureService(Protocol):
    def capture(self, hwnd: int) -> Image.Image: ...


class ScreenshotPanel(QWidget):
    """Display manual and periodically refreshed captures for one HWND."""

    status_changed = Signal(str)
    frame_captured = Signal(int, int)
    target_lost = Signal(int)
    capture_unavailable = Signal(int, str)

    def __init__(
        self,
        capture_service: CaptureService | None = None,
        parent: QWidget | None = None,
        *,
        refresh_interval_ms: int = 1000,
    ) -> None:
        super().__init__(parent)
        if refresh_interval_ms <= 0:
            raise ValueError("Refresh interval must be positive")

        self._capture_service = capture_service
        self._target_hwnd: int | None = None
        self._image: Image.Image | None = None
        self._pixmap: QPixmap | None = None
        self._capture_blocked = False

        self.preview = QLabel("请选择目标窗口", self)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(560, 350)
        self.preview.setStyleSheet("QLabel { background: #202124; color: #dddddd; }")

        self.capture_button = QPushButton("立即截图", self)
        self.save_button = QPushButton("保存截图", self)
        self.capture_button.setEnabled(False)
        self.save_button.setEnabled(False)

        controls = QHBoxLayout()
        controls.addWidget(self.capture_button)
        controls.addWidget(self.save_button)
        controls.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.preview, stretch=1)
        layout.addLayout(controls)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(refresh_interval_ms)
        self._refresh_timer.timeout.connect(self.capture_now)
        self.capture_button.clicked.connect(self.capture_and_resume)
        self.save_button.clicked.connect(lambda: self.save_screenshot())

    @property
    def current_image(self) -> Image.Image | None:
        return self._image

    @property
    def target_hwnd(self) -> int | None:
        return self._target_hwnd

    def set_target_window(self, hwnd: int) -> None:
        """Switch capture to *hwnd* and immediately refresh the preview."""
        self._target_hwnd = hwnd
        self._image = None
        self._pixmap = None
        self._capture_blocked = False
        available = self._capture_service is not None
        self.capture_button.setEnabled(available)
        self.save_button.setEnabled(False)

        if not available:
            self._refresh_timer.stop()
            self.preview.setText("窗口截图功能不可用")
            return

        self.capture_now()
        if self._target_hwnd == hwnd and not self._capture_blocked:
            self._refresh_timer.start()

    def clear_target_window(self) -> None:
        """Stop refresh and clear the selected HWND."""
        self._refresh_timer.stop()
        self._target_hwnd = None
        self._image = None
        self._pixmap = None
        self._capture_blocked = False
        self.capture_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.preview.setPixmap(QPixmap())
        self.preview.setText("请选择目标窗口")

    def capture_now(self) -> Image.Image | None:
        """Capture the selected HWND and update the preview."""
        if self._capture_service is None or self._target_hwnd is None:
            return None
        try:
            image = self._capture_service.capture(self._target_hwnd)
        except WindowNotFoundError as exc:
            lost_hwnd = self._target_hwnd
            logger.warning(
                "screenshot_target_lost",
                hwnd=lost_hwnd,
                error=str(exc),
            )
            self._refresh_timer.stop()
            self._target_hwnd = None
            self._image = None
            self._pixmap = None
            self.preview.setPixmap(QPixmap())
            self.preview.setText("目标窗口已关闭，请刷新窗口列表")
            self.capture_button.setEnabled(False)
            self.save_button.setEnabled(False)
            self.status_changed.emit("目标窗口已关闭")
            self.target_lost.emit(lost_hwnd)
            return None
        except BlackWindowFrameError as exc:
            blocked_hwnd = self._target_hwnd
            logger.warning(
                "screenshot_capture_unavailable",
                hwnd=blocked_hwnd,
                error_type=type(exc).__name__,
            )
            self._refresh_timer.stop()
            self._capture_blocked = True
            self._image = None
            self._pixmap = None
            self.preview.setPixmap(QPixmap())
            self.preview.setText("此窗口无法捕获有效画面（全黑）")
            self.save_button.setEnabled(False)
            self.status_changed.emit("此窗口无法捕获有效画面")
            self.capture_unavailable.emit(blocked_hwnd, str(exc))
            return None
        except MinimizedWindowCaptureError as exc:
            blocked_hwnd = self._target_hwnd
            logger.warning(
                "screenshot_target_minimized",
                hwnd=blocked_hwnd,
                error_type=type(exc).__name__,
            )
            self._refresh_timer.stop()
            self._capture_blocked = True
            self._image = None
            self._pixmap = None
            self.preview.setPixmap(QPixmap())
            self.preview.setText("目标窗口已最小化；恢复后点击“立即截图”")
            self.save_button.setEnabled(False)
            self.status_changed.emit("目标窗口已最小化")
            self.capture_unavailable.emit(blocked_hwnd, str(exc))
            return None
        except WindowsGuiAgentError as exc:
            logger.error(
                "screenshot_capture_failed",
                hwnd=self._target_hwnd,
                error=str(exc),
            )
            self.preview.setPixmap(QPixmap())
            self.preview.setText(f"截图失败：{exc}")
            self.save_button.setEnabled(False)
            self.status_changed.emit("截图失败")
            return None
        except Exception as exc:
            logger.exception(
                "unexpected_screenshot_failure",
                hwnd=self._target_hwnd,
                error=str(exc),
            )
            self.preview.setPixmap(QPixmap())
            self.preview.setText("截图失败")
            self.save_button.setEnabled(False)
            self.status_changed.emit("截图失败")
            return None

        self.display_image(image)
        self.frame_captured.emit(image.width, image.height)
        self.status_changed.emit(
            f"已截图：HWND {self._target_hwnd} — {image.width}×{image.height}"
        )
        return image

    def capture_and_resume(self) -> Image.Image | None:
        """Manual retry that resumes periodic capture after a valid frame."""
        image = self.capture_now()
        if image is not None and self._target_hwnd is not None:
            self._refresh_timer.start()
        return image

    def display_image(self, image: Image.Image) -> None:
        """Display an in-memory runtime frame without saving or serializing it."""
        self._image = image
        self._capture_blocked = False
        self._pixmap = self._to_pixmap(image)
        self._update_scaled_preview()
        self.save_button.setEnabled(True)

    def set_periodic_refresh_enabled(self, enabled: bool) -> None:
        """Avoid concurrent manual captures while the Agent worker is running."""
        if (
            enabled
            and self._target_hwnd is not None
            and self._capture_service is not None
            and not self._capture_blocked
        ):
            self._refresh_timer.start()
        else:
            self._refresh_timer.stop()

    def save_screenshot(self, destination: Path | str | None = None) -> Path | None:
        """Save the current preview as PNG, prompting when no path is supplied."""
        if self._image is None:
            return None

        if destination is None:
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "保存截图",
                f"window_{self._target_hwnd}.png",
                "PNG 图片 (*.png);;JPEG 图片 (*.jpg *.jpeg)",
            )
            if not filename:
                return None
            target = Path(filename)
        else:
            target = Path(destination)

        target.parent.mkdir(parents=True, exist_ok=True)
        self._image.save(target)
        logger.info("screenshot_saved", hwnd=self._target_hwnd, path=str(target))
        self.status_changed.emit(f"已保存：{target}")
        return target

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_scaled_preview()

    def _update_scaled_preview(self) -> None:
        if self._pixmap is None:
            return

        scaled = self._scale_pixmap_for_preview(
            self._pixmap,
            self.preview.size(),
            self.preview.devicePixelRatioF(),
        )
        self.preview.setPixmap(scaled)

    @staticmethod
    def _scale_pixmap_for_preview(
        pixmap: QPixmap,
        logical_size: QSize,
        device_pixel_ratio: float,
    ) -> QPixmap:
        """Scale at the display's physical resolution to keep HiDPI text sharp."""
        ratio = max(1.0, device_pixel_ratio)
        physical_size = QSize(
            max(1, round(logical_size.width() * ratio)),
            max(1, round(logical_size.height() * ratio)),
        )
        scaled = pixmap.scaled(
            physical_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(ratio)
        return scaled

    @staticmethod
    def _to_pixmap(image: Image.Image) -> QPixmap:
        rgb_image = image.convert("RGB")
        pixels = rgb_image.tobytes("raw", "RGB")
        qimage = QImage(
            pixels,
            rgb_image.width,
            rgb_image.height,
            rgb_image.width * 3,
            QImage.Format.Format_RGB888,
        ).copy()
        return QPixmap.fromImage(qimage)
