"""Print eligible top-level Windows windows for Milestone 1 debugging."""

from __future__ import annotations

from app.common.exceptions import WindowsGuiAgentError
from app.windows.window_manager import WindowManager


def main() -> int:
    try:
        windows = WindowManager().list_windows()
    except WindowsGuiAgentError as exc:
        print(f"Unable to enumerate windows: {exc}")
        return 1

    print(f"{'HWND':>10} {'PID':>8} {'WIDTH':>7} {'HEIGHT':>7} TITLE")
    for window in windows:
        print(
            f"{window.hwnd:>10} {window.pid:>8} "
            f"{window.width:>7} {window.height:>7} {window.title}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
