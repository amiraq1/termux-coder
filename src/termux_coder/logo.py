from __future__ import annotations

import os
import shutil
import sys
import threading
import time

ENABLE_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")

RESET = "\x1b[0m"
DIM = "\x1b[2m"
TEAL = "\x1b[38;2;77;182;172m"
TEALB = "\x1b[1;38;2;77;182;172m"
DIAMOND = "◈"

BIG_ART = [
    " █████╗  ██████╗ ███████╗███╗   ██╗████████╗",
    "██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝",
    "███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║",
    "██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║",
    "██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║",
    "╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝",
]


def paint(text: str, color: str) -> str:
    return color + text + RESET if ENABLE_COLOR else text


def mini_logo() -> str:
    return paint(f"{DIAMOND} agent", TEALB)


def print_banner() -> None:
    print()
    cols = shutil.get_terminal_size((80, 24)).columns
    if cols < 52:
        print(paint(f"  {DIAMOND} agent", TEALB))
        print(paint("  terminal coding agent — Termux", DIM))
        print()
        return
    print(paint(f"  {DIAMOND}", TEALB))
    for line in BIG_ART:
        print(paint("  " + line, TEAL))
    print(paint("  terminal coding agent — Termux edition", DIM))
    print()


def ctrl(action: str, detail: str = "") -> None:
    line = f"{mini_logo()} {paint('▸', TEAL)} {action}"
    if detail:
        line += f" {paint(detail, DIM)}"
    print(line)


class Thinking:
    def __init__(self, label: str = "thinking"):
        self.label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _spin(self) -> None:
        frames = ["◈", "◇", "◆", "◇"]
        i = 0
        while not self._stop.is_set():
            sys.stdout.write("\r" + paint(f"{frames[i % 4]} agent — {self.label}...", TEAL) + " ")
            sys.stdout.flush()
            i += 1
            time.sleep(0.25)

    def __enter__(self):
        if ENABLE_COLOR:
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc) -> bool:
        if self._thread:
            self._stop.set()
            self._thread.join()
            cols = shutil.get_terminal_size((80, 24)).columns
            sys.stdout.write("\r" + " " * cols + "\r")
            sys.stdout.flush()
        return False
