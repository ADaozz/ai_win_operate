"""Windows integration package."""

from app.windows.capture import WindowCapture
from app.windows.input_executor import WindowsInputExecutor
from app.windows.models import CaptureMetadata, WindowInfo
from app.windows.window_manager import WindowManager

__all__ = [
    "CaptureMetadata",
    "WindowCapture",
    "WindowInfo",
    "WindowManager",
    "WindowsInputExecutor",
]
