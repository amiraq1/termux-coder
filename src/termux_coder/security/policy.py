from __future__ import annotations

BLOCKED_PATTERNS = [
    "rm -rf /",
    "rm -rf ~",
    "rm -rf /*",
    "mkfs",
    "dd if=",
    "shutdown",
    "reboot",
    "chmod -r 777 /",
    "> /dev/sd",
    "| sh",
    "| bash",
    "curl | sh",
    "wget | sh",
]


class CommandPolicy:
    def __init__(self, mode: str = "ASK"):
        self.mode = mode.upper()

    def is_blocked(self, command: str) -> bool:
        normalized = command.lower().replace(" ", "")
        return any(p.lower().replace(" ", "") in normalized for p in BLOCKED_PATTERNS)

    def command_allowed_at_all(self) -> bool:
        return self.mode != "READONLY"

    def requires_approval(self, command: str) -> bool:
        # AUTO فقط يتخطى الموافقة، وهو غير افتراضي
        return self.mode != "AUTO"
