"""Local screenshot difference without a second model call."""

from __future__ import annotations

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

_DIFF_SIZE = (160, 90)
DEFAULT_FRAME_DIFF_THRESHOLD = 0.005


class FrameDiffResult(BaseModel):
    """Normalized mean absolute difference between two frames."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    changed: bool
    score: float = Field(ge=0.0, le=1.0)
    threshold: float = Field(gt=0.0, le=1.0)


def compare_frames(
    before: Image.Image,
    after: Image.Image,
    *,
    threshold: float = DEFAULT_FRAME_DIFF_THRESHOLD,
) -> FrameDiffResult:
    """Return whether ``after`` differs from ``before`` above ``threshold``."""
    if threshold <= 0.0 or threshold > 1.0:
        raise ValueError("threshold must be in (0, 1]")
    left = _normalize(before)
    right = _normalize(after)
    left_bytes = left.tobytes()
    right_bytes = right.tobytes()
    if len(left_bytes) != len(right_bytes):
        raise ValueError("normalized frames must have the same byte length")
    total = sum(abs(a - b) for a, b in zip(left_bytes, right_bytes, strict=True))
    score = total / (len(left_bytes) * 255.0)
    return FrameDiffResult(
        changed=score >= threshold,
        score=round(score, 6),
        threshold=threshold,
    )


def _normalize(image: Image.Image) -> Image.Image:
    return image.convert("L").resize(_DIFF_SIZE, Image.Resampling.BILINEAR)
