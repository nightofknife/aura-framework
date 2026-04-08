from __future__ import annotations

import argparse
import ctypes
import json
import sys
from dataclasses import asdict, dataclass


user32 = ctypes.windll.user32
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    visible: bool


def _get_window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def list_windows(include_invisible: bool, include_empty: bool) -> list[WindowInfo]:
    windows: list[WindowInfo] = []

    @EnumWindowsProc
    def _enum_callback(hwnd: int, lparam: int) -> bool:
        visible = bool(user32.IsWindowVisible(hwnd))
        if not include_invisible and not visible:
            return True

        title = _get_window_title(hwnd)
        if not include_empty and not title.strip():
            return True

        windows.append(WindowInfo(hwnd=hwnd, title=title, visible=visible))
        return True

    user32.EnumWindows(_enum_callback, 0)
    return windows


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

    parser = argparse.ArgumentParser(
        description="List current top-level window titles on Windows."
    )
    parser.add_argument(
        "--include-invisible",
        action="store_true",
        help="Include invisible windows.",
    )
    parser.add_argument(
        "--include-empty",
        action="store_true",
        help="Include windows with empty titles.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON output.",
    )
    args = parser.parse_args()

    windows = list_windows(
        include_invisible=args.include_invisible,
        include_empty=args.include_empty,
    )

    if args.json:
        payload = [
            {
                **asdict(item),
                "hwnd_hex": f"0x{item.hwnd:08X}",
            }
            for item in windows
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if not windows:
        print("No windows found.")
        return 0

    for i, item in enumerate(windows, start=1):
        print(f"{i:>3}. {item.title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
