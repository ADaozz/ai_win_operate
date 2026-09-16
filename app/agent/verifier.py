"""Local post-action verification using Frame Diff (no Verifier LLM)."""

from __future__ import annotations

from PIL import Image

from app.actions.schema import ActionResult, AgentAction
from app.vision.frame_diff import (
    DEFAULT_FRAME_DIFF_THRESHOLD,
    FrameDiffResult,
    compare_frames,
)

# Actions where a visible change is informative in the result message.
_EXPECT_UI_CHANGE = frozenset(
    {
        "click",
        "double_click",
        "right_click",
        "scroll",
    }
)
# Only these abort remaining plan steps when pixels barely move.
# Clicks/type often focus fields or tick tiny controls; Frame Diff stays advisory.
_ABORT_PLAN_WITHOUT_CHANGE = frozenset({"scroll"})


class LocalResultVerifier:
    """Enrich an execution result with Frame Diff metadata for the next step."""

    def __init__(
        self,
        *,
        threshold: float = DEFAULT_FRAME_DIFF_THRESHOLD,
    ) -> None:
        if threshold <= 0.0 or threshold > 1.0:
            raise ValueError("threshold must be in (0, 1]")
        self._threshold = threshold

    @property
    def threshold(self) -> float:
        return self._threshold

    def expects_ui_change(self, action: AgentAction) -> bool:
        return action.type in _EXPECT_UI_CHANGE

    def verify(
        self,
        action: AgentAction,
        execution_result: ActionResult,
        before: Image.Image,
        after: Image.Image,
    ) -> tuple[ActionResult, FrameDiffResult]:
        """Attach Frame Diff to a successful delivery result."""
        frame_diff = compare_frames(
            before,
            after,
            threshold=self._threshold,
        )
        if not execution_result.success:
            message = (
                f"{execution_result.message}; "
                f"frame_diff score={frame_diff.score:.4f}, "
                f"changed={frame_diff.changed}"
            ).strip("; ")
            return (
                ActionResult(
                    success=False,
                    message=message,
                    duration_ms=execution_result.duration_ms,
                    frame_diff_score=frame_diff.score,
                    ui_changed=frame_diff.changed,
                ),
                frame_diff,
            )

        expected = self.expects_ui_change(action)
        if expected and not frame_diff.changed:
            message = (
                f"{execution_result.message}; "
                f"UI did not change meaningfully "
                f"(frame_diff score={frame_diff.score:.4f}, "
                f"threshold={frame_diff.threshold:.4f}); "
                "treat as soft evidence for the next decision, not an automatic miss"
            )
        elif frame_diff.changed:
            message = (
                f"{execution_result.message}; "
                f"UI changed (frame_diff score={frame_diff.score:.4f})"
            )
        else:
            message = (
                f"{execution_result.message}; "
                f"no meaningful UI change "
                f"(frame_diff score={frame_diff.score:.4f}); "
                "acceptable for this action type"
            )
        return (
            ActionResult(
                success=True,
                message=message,
                duration_ms=execution_result.duration_ms,
                frame_diff_score=frame_diff.score,
                ui_changed=frame_diff.changed,
            ),
            frame_diff,
        )

    def should_abort_plan(
        self,
        action: AgentAction,
        result: ActionResult,
    ) -> bool:
        """Stop remaining planned actions only on hard failures or failed scrolls."""
        if not result.success:
            return True
        if action.type not in _ABORT_PLAN_WITHOUT_CHANGE:
            return False
        return result.ui_changed is False
