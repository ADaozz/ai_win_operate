from __future__ import annotations

from PIL import Image

from app.vision.frame_diff import compare_frames


def test_identical_frames_are_unchanged() -> None:
    image = Image.new("RGB", (320, 200), "white")
    result = compare_frames(image, image.copy(), threshold=0.02)

    assert result.changed is False
    assert result.score == 0.0
    assert result.threshold == 0.02


def test_different_frames_are_changed() -> None:
    before = Image.new("RGB", (320, 200), "white")
    after = Image.new("RGB", (320, 200), "black")
    result = compare_frames(before, after, threshold=0.02)

    assert result.changed is True
    assert result.score > 0.5


def test_threshold_controls_changed_flag() -> None:
    before = Image.new("RGB", (100, 100), (128, 128, 128))
    after = before.copy()
    after.putpixel((50, 50), (255, 255, 255))
    low = compare_frames(before, after, threshold=0.00001)
    high = compare_frames(before, after, threshold=0.5)

    assert low.changed is True
    assert high.changed is False
