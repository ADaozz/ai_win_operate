"""Vision helpers for local screenshot comparison."""

from app.vision.frame_diff import (
    DEFAULT_FRAME_DIFF_THRESHOLD,
    FrameDiffResult,
    compare_frames,
)

__all__ = [
    "DEFAULT_FRAME_DIFF_THRESHOLD",
    "FrameDiffResult",
    "compare_frames",
]
