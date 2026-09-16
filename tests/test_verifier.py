from __future__ import annotations

from PIL import Image

from app.actions.schema import ActionResult, parse_action
from app.agent.verifier import LocalResultVerifier


def test_verifier_marks_missing_ui_change_for_click_without_aborting() -> None:
    verifier = LocalResultVerifier(threshold=0.02)
    before = Image.new("RGB", (64, 64), "white")
    after = before.copy()
    action = parse_action({"type": "click", "x": 0.5, "y": 0.5})
    delivered = ActionResult(success=True, message="click input delivered")

    result, frame_diff = verifier.verify(action, delivered, before, after)

    assert result.success is True
    assert result.ui_changed is False
    assert result.frame_diff_score == frame_diff.score
    assert "did not change meaningfully" in result.message
    assert "soft evidence" in result.message
    assert verifier.should_abort_plan(action, result) is False


def test_verifier_accepts_visible_change() -> None:
    verifier = LocalResultVerifier(threshold=0.02)
    before = Image.new("RGB", (64, 64), "white")
    after = Image.new("RGB", (64, 64), "black")
    action = parse_action({"type": "click", "x": 0.2, "y": 0.3})
    delivered = ActionResult(success=True, message="click input delivered")

    result, frame_diff = verifier.verify(action, delivered, before, after)

    assert result.ui_changed is True
    assert frame_diff.changed is True
    assert "UI changed" in result.message
    assert verifier.should_abort_plan(action, result) is False


def test_wait_does_not_require_ui_change() -> None:
    verifier = LocalResultVerifier(threshold=0.02)
    image = Image.new("RGB", (64, 64), "white")
    action = parse_action({"type": "wait", "milliseconds": 100})
    delivered = ActionResult(success=True, message="waited")

    result, _frame_diff = verifier.verify(action, delivered, image, image.copy())

    assert result.ui_changed is False
    assert "acceptable for this action type" in result.message
    assert verifier.should_abort_plan(action, result) is False


def test_scroll_without_change_aborts_remaining_plan() -> None:
    verifier = LocalResultVerifier(threshold=0.02)
    image = Image.new("RGB", (64, 64), "white")
    action = parse_action({"type": "scroll", "direction": "down", "amount": 3})
    delivered = ActionResult(success=True, message="scrolled")

    result, _frame_diff = verifier.verify(action, delivered, image, image.copy())

    assert result.ui_changed is False
    assert verifier.should_abort_plan(action, result) is True


def test_failed_execution_still_attaches_frame_diff() -> None:
    verifier = LocalResultVerifier(threshold=0.02)
    before = Image.new("RGB", (64, 64), "white")
    after = Image.new("RGB", (64, 64), "black")
    action = parse_action({"type": "type", "text": "hi"})
    failed = ActionResult(success=False, message="input failed")

    result, frame_diff = verifier.verify(action, failed, before, after)

    assert result.success is False
    assert result.ui_changed is True
    assert result.frame_diff_score == frame_diff.score
    assert verifier.should_abort_plan(action, result) is True
