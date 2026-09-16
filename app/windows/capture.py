"""Capture only the selected HWND into a Pillow image."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from PIL import Image

from app.common.exceptions import (
    BlackWindowFrameError,
    MinimizedWindowCaptureError,
    UnsupportedPlatformError,
    WindowCaptureError,
)
from app.windows.models import CaptureMetadata, WindowInfo


class WindowInspector(Protocol):
    def get_window(self, hwnd: int) -> WindowInfo: ...

    def is_minimized(self, hwnd: int) -> bool: ...


class CaptureBackend(Protocol):
    def capture_bgra(self, hwnd: int, width: int, height: int) -> bytes: ...


class PyWin32CaptureBackend:
    """Capture an HWND using PrintWindow, with window-DC BitBlt fallback."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise UnsupportedPlatformError("Window capture is available only on Windows")

        import win32con  # type: ignore[import-not-found]
        import win32gui  # type: ignore[import-not-found]
        import win32ui  # type: ignore[import-not-found]

        self._con = win32con
        self._gui = win32gui
        self._ui = win32ui

    def capture_bgra(self, hwnd: int, width: int, height: int) -> bytes:
        window_dc_handle = self._gui.GetWindowDC(hwnd)
        if not window_dc_handle:
            raise WindowCaptureError(f"Unable to acquire window DC: HWND {hwnd}")

        source_dc = None
        memory_dc = None
        bitmap = None
        try:
            source_dc = self._ui.CreateDCFromHandle(window_dc_handle)
            memory_dc = source_dc.CreateCompatibleDC()
            bitmap = self._ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(source_dc, width, height)
            memory_dc.SelectObject(bitmap)

            # PW_RENDERFULLCONTENT improves capture of composed Windows apps.
            print_window = ctypes.windll.user32.PrintWindow  # type: ignore[attr-defined]
            print_window.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
            print_window.restype = wintypes.BOOL
            rendered = print_window(
                hwnd,
                memory_dc.GetSafeHdc(),
                2,
            )
            pixels = bytes(bitmap.GetBitmapBits(True))
            if not rendered or self._is_black_bgra(pixels, width, height):
                memory_dc.BitBlt(
                    (0, 0),
                    (width, height),
                    source_dc,
                    (0, 0),
                    self._con.SRCCOPY,
                )
                pixels = bytes(bitmap.GetBitmapBits(True))
            return pixels
        finally:
            if bitmap is not None:
                self._gui.DeleteObject(bitmap.GetHandle())
            if memory_dc is not None:
                memory_dc.DeleteDC()
            if source_dc is not None:
                source_dc.DeleteDC()
            self._gui.ReleaseDC(hwnd, window_dc_handle)

    @staticmethod
    def _is_black_bgra(pixels: bytes, width: int, height: int) -> bool:
        if len(pixels) != width * height * 4:
            return False
        image = Image.frombuffer(
            "RGB",
            (width, height),
            pixels,
            "raw",
            "BGRX",
            0,
            1,
        )
        return WindowCapture._is_effectively_black(image)


class WindowCapture:
    """Coordinate window inspection, pixel capture, and frame metadata."""

    def __init__(
        self,
        window_manager: WindowInspector,
        backend: CaptureBackend | None = None,
    ) -> None:
        self._window_manager = window_manager
        self._backend = backend or PyWin32CaptureBackend()
        self.last_metadata: CaptureMetadata | None = None

    def capture(self, hwnd: int) -> Image.Image:
        """Capture the current target-window bounds as an RGB image."""
        window = self._window_manager.get_window(hwnd)
        if self._window_manager.is_minimized(hwnd):
            raise MinimizedWindowCaptureError(
                f"Cannot capture minimized window: HWND {hwnd}"
            )

        try:
            pixels = self._backend.capture_bgra(hwnd, window.width, window.height)
        except WindowCaptureError:
            raise
        except Exception as exc:
            raise WindowCaptureError(f"Unable to capture window: HWND {hwnd}") from exc

        expected_bytes = window.width * window.height * 4
        if len(pixels) != expected_bytes:
            raise WindowCaptureError(
                f"Invalid frame buffer for HWND {hwnd}: "
                f"expected {expected_bytes} bytes, got {len(pixels)}"
            )

        image = Image.frombuffer(
            "RGB",
            (window.width, window.height),
            pixels,
            "raw",
            "BGRX",
            0,
            1,
        ).copy()
        if self._is_effectively_black(image):
            raise BlackWindowFrameError(
                f"Target window returned an unusable all-black frame: HWND {hwnd}"
            )
        metadata = CaptureMetadata(
            hwnd=hwnd,
            width=window.width,
            height=window.height,
            timestamp=datetime.now(UTC),
        )
        image.info["capture"] = metadata.model_dump(mode="json")
        self.last_metadata = metadata
        return image

    @staticmethod
    def _is_effectively_black(image: Image.Image) -> bool:
        """Reject near-zero RGB frames while allowing dark UIs with visible details."""
        return all(maximum <= 2 for _minimum, maximum in image.getextrema())

    def save_debug_frame(
        self,
        image: Image.Image,
        directory: Path | str = Path("runs/debug"),
        filename: str | None = None,
    ) -> Path:
        """Save a captured frame as PNG and return its path."""
        target_dir = Path(directory)
        target_dir.mkdir(parents=True, exist_ok=True)

        metadata = self.last_metadata
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            hwnd = metadata.hwnd if metadata is not None else "unknown"
            filename = f"frame_{timestamp}_hwnd_{hwnd}.png"
        if Path(filename).name != filename:
            raise ValueError("Debug frame filename must not contain a directory")

        destination = target_dir / filename
        image.save(destination, format="PNG")
        return destination
