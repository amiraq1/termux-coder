from __future__ import annotations

from enum import Enum
from typing import NamedTuple


class Permission(Enum):
    """مستويات صلاحية الأدوات — يحددها سجل الأدوات، لا النموذج."""
    READ = "read"       # قراءة فقط: read_file, list_dir, search_text, repo_map
    WRITE = "write"     # كتابة الملفات: apply_patch, write_file, rollback_patch
    EXECUTE = "execute" # تنفيذ أوامر: run_command, git_*
    NETWORK = "network" # اتصالات قراءة خارجية: web_search, fetch_page


# صلاحية كل أداة — يحددها المطور، لا النموذج ولا المستدعي
TOOL_PERMISSIONS: dict[str, Permission] = {
    # أدوات قراءة
    "read_file":       Permission.READ,
    "list_dir":        Permission.READ,
        "search_text":    Permission.READ,
    "web_search":     Permission.NETWORK,
    "fetch_page":     Permission.NETWORK,

    "repo_map":        Permission.READ,
    "git_status":      Permission.READ,
    "git_diff":        Permission.READ,
    "git_log":         Permission.READ,
    "get_todos":       Permission.READ,
    # أدوات كتابة
    "apply_patch":     Permission.WRITE,
    "apply_patch_plan": Permission.WRITE,
    "write_file":      Permission.WRITE,
    "delete_file":     Permission.WRITE,
    "rollback_patch":  Permission.WRITE,
    "rollback_patch_plan": Permission.WRITE,
    "update_todos":    Permission.WRITE,
    # أدوات تنفيذ
    "run_command":     Permission.EXECUTE,
    "git_commit":      Permission.EXECUTE,
    "git_restore":     Permission.EXECUTE,
    "git_checkpoint":  Permission.EXECUTE,
}

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
    ":(){ :|:& };:",  # fork bomb
    "base64 -d",      # غالباً لتشفير أوامر خطيرة
]


class PolicyDecision(NamedTuple):
    allowed: bool
    requires_approval: bool
    reason: str


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


class PolicyEngine:
    """
    محرك سياسات مُحسَّن:
    - صلاحية الأداة تأتي من TOOL_PERMISSIONS (سجل موثوق)، لا من النموذج
    - يتحقق من وضع التشغيل (READONLY لا يسمح بالكتابة أو التنفيذ)
    - يُرجع قراراً مُفصَّلاً مع السبب
    """

    def __init__(self, mode: str = "ASK"):
        self.mode = mode.upper()
        self._cmd_policy = CommandPolicy(mode)

    def tool_permission(self, tool_name: str) -> Permission | None:
        """أعد صلاحية الأداة من السجل الموثوق (لا من مدخلات خارجية)."""
        return TOOL_PERMISSIONS.get(tool_name)

    def evaluate_tool(self, tool_name: str) -> PolicyDecision:
        """
        تقييم ما إذا كانت الأداة مسموحاً بها في الوضع الحالي.
        الصلاحية تُستخرج من TOOL_PERMISSIONS، لا تُمرَّر من الخارج.
        """
        perm = self.tool_permission(tool_name)

        if perm is None:
            return PolicyDecision(
                allowed=False,
                requires_approval=False,
                reason=f"unknown tool '{tool_name}' — not in registry",
            )

        if self.mode == "READONLY" and perm not in {Permission.READ, Permission.NETWORK}:
            return PolicyDecision(
                allowed=False,
                requires_approval=False,
                reason=f"READONLY mode: '{tool_name}' requires {perm.value} permission",
            )

        # قراءة واتصالات الشبكة في READONLY لا تعدل مساحة العمل.
        if perm == Permission.READ:
            return PolicyDecision(allowed=True, requires_approval=False, reason="read_ok")
        if perm == Permission.NETWORK and self.mode == "READONLY":
            return PolicyDecision(allowed=True, requires_approval=False, reason="network_read_ok")

        # الكتابة والتنفيذ والبحث الشبكي في ASK تحتاج موافقة، وAUTO يتخطاها.
        needs_approval = self.mode != "AUTO"
        return PolicyDecision(
            allowed=True,
            requires_approval=needs_approval,
            reason=f"{perm.value}_requires_approval" if needs_approval else f"{perm.value}_auto",
        )

    def evaluate_command(self, command: str) -> PolicyDecision:
        """تقييم أمر shell."""
        if not self._cmd_policy.command_allowed_at_all():
            return PolicyDecision(
                allowed=False,
                requires_approval=False,
                reason="READONLY mode: commands not allowed",
            )
        if self._cmd_policy.is_blocked(command):
            return PolicyDecision(
                allowed=False,
                requires_approval=False,
                reason=f"blocked command pattern detected",
            )
        needs_approval = self._cmd_policy.requires_approval(command)
        return PolicyDecision(
            allowed=True,
            requires_approval=needs_approval,
            reason="command_auto" if not needs_approval else "command_requires_approval",
        )
