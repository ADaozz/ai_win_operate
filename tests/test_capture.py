from __future__ import annotations

from pathlib import Path

import pytest

from app.common.exceptions import BlackWindowFrameError, WindowCaptureError
from app.windows.capture import WindowCapture
from app.windows.models import WindowInfo


class FakeWindowInspector:
    def __init__(self, window: WindowInfo, *, minimized: bool = False) -> None:
        self.window = window
        self.minimized = minimized

    def get_window(self, hwnd: int) -> WindowInfo:
        assert hwnd == self.window.hwnd
        return self.window

    def is_minimized(self, hwnd: int) -> bool:
        assert hwnd == self.window.hwnd
        return self.minimized


class SolidBgraBackend:
    def __init__(self, pixel: bytes = bytes((10, 20, 30, 0))) -> None:
        self.pixel = pixel
        self.calls: list[tuple[int, int, int]] = []

    def capture_bgra(self, hwnd: int, width: int, height: int) -> bytes:
        self.calls.append((hwnd, width, height))
        return self.pixel * width * height


def make_window(width: int = 2, height: int = 1) -> WindowInfo:
    return WindowInfo(
        hwnd=321,
        title="Editor",
        pid=654,
        left=-50,
        top=25,
        width=width,
        height=height,
    )


def test_capture_uses_current_window_size_and_records_metadata() -> None:
    inspector = FakeWindowInspector(make_window())
    backend = SolidBgraBackend()
    capture = WindowCapture(inspector, backend)

    image = capture.capture(321)

    assert image.size == (2, 1)
    assert image.getpixel((0, 0)) == (30, 20, 10)
    assert backend.calls == [(321, 2, 1)]
    assert image.info["capture"]["hwnd"] == 321
    assert image.info["capture"]["width"] == 2
    assert capture.last_metadata is not None
    assert capture.last_metadata.height == 1

    inspector.window = make_window(width=4, height=3)
    assert capture.capture(321).size == (4, 3)
    assert backend.calls[-1] == (321, 4, 3)


def test_capture_rejects_minimized_window() -> None:
    inspector = FakeWindowInspector(make_window(), minimized=True)
    capture = WindowCapture(inspector, SolidBgraBackend())

    with pytest.raises(WindowCaptureError, match="minimized"):
        capture.capture(321)


def test_capture_rejects_incomplete_pixel_buffer() -> None:
    class IncompleteBackend:
        def capture_bgra(self, hwnd: int, width: int, height: int) -> bytes:
            return b"\x00"

    capture = WindowCapture(FakeWindowInspector(make_window()), IncompleteBackend())

    with pytest.raises(WindowCaptureError, match="Invalid frame buffer"):
        capture.capture(321)


def test_capture_rejects_all_black_frame_before_model_use() -> None:
    capture = WindowCapture(
        FakeWindowInspector(make_window(width=4, height=3)),
        SolidBgraBackend(bytes((0, 0, 0, 0))),
    )

    with pytest.raises(BlackWindowFrameError, match="all-black"):
        capture.capture(321)

    assert capture.last_metadata is None


def test_save_debug_frame_creates_png(tmp_path: Path) -> None:
    capture = WindowCapture(FakeWindowInspector(make_window()), SolidBgraBackend())
    image = capture.capture(321)

    destination = capture.save_debug_frame(image, tmp_path, "frame_001.png")

    assert destination == tmp_path / "frame_001.png"
    assert destination.read_bytes().startswith(b"\x89PNG")

    with pytest.raises(ValueError, match="must not contain"):
        capture.save_debug_frame(image, tmp_path, "../outside.png")
