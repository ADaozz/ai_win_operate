"""Capture one HWND and save a PNG for Milestone 2 debugging."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from app.common.exceptions import WindowsGuiAgentError
from app.windows.capture import WindowCapture
from app.windows.window_manager import WindowManager


def parse_hwnd(value: str) -> int:
    """Parse a decimal or 0x-prefixed HWND."""
    try:
        hwnd = int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("HWND must be an integer") from exc
    if hwnd <= 0:
        raise argparse.ArgumentTypeError("HWND must be positive")
    return hwnd


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hwnd", type=parse_hwnd, help="target HWND (decimal or hex)")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("runs/debug"),
        help="directory for the PNG frame",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manager = WindowManager()
        capture = WindowCapture(manager)
        image = capture.capture(args.hwnd)
        destination = capture.save_debug_frame(image, args.output_dir)
    except WindowsGuiAgentError as exc:
        print(f"Unable to capture window: {exc}")
        return 1

    print(f"Saved {image.width}x{image.height} frame to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
