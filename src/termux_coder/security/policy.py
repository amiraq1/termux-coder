from __future__ import annotations

import shlex
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
        "apply_patch":    Permission.WRITE,
    "apply_symbol_patch": Permission.WRITE,

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

AUTO_SAFE_COMMANDS = frozenset({"ls", "pwd"})
AUTO_SAFE_GIT_READS = frozenset({"status"})
AUTO_SAFE_PYTHON_MODULES = frozenset({"pytest", "compileall", "unittest"})
AUTO_SAFE_TOOLS = frozenset({"pytest", "ruff", "mypy", "pyright"})


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
    risk: str = "medium"


class CommandPolicy:
    def __init__(self, mode: str = "ASK"):
        self.mode = mode.upper()

    def is_blocked(self, command: str) -> bool:
        normalized = command.lower().replace(" ", "")
        return any(p.lower().replace(" ", "") in normalized for p in BLOCKED_PATTERNS)

    def command_allowed_at_all(self) -> bool:
        return self.mode != "READONLY"

    def is_auto_verification(self, command: str) -> bool:
        """Allow only bounded verification commands in GRANULAR mode."""
        try:
            argv = shlex.split(command, posix=True)
        except ValueError:
            return False
        if not argv or any(token in {"-c", "--command", "&&", "||", ";", "|"} for token in argv):
            return False
        if argv[0] in AUTO_SAFE_TOOLS:
            return True
        return (
            len(argv) >= 3
            and argv[0] in {"python", "python3"}
            and argv[1] == "-m"
            and argv[2] in AUTO_SAFE_PYTHON_MODULES
        )

    def is_auto_allowlisted(self, command: str) -> bool:
        """Return whether AUTO may execute this argv without human approval."""
        try:
            argv = shlex.split(command, posix=True)
        except ValueError:
            return False
        if not argv or any(token in {"-c", "--command", "&&", "||", ";", "|"} for token in argv):
            return False
        if self.is_auto_verification(command):
            return True
        executable = argv[0]
        if executable in AUTO_SAFE_COMMANDS:
            return all(
                not token.startswith("/") and ".." not in token
                for token in argv[1:]
            )
        if executable == "git":
            return len(argv) >= 2 and argv[1] in AUTO_SAFE_GIT_READS
        return False

    def requires_approval(self, command: str) -> bool:
        # AUTO لا يتخطى الموافقة إلا للأوامر الموجودة في allowlist.
        if self.mode == "AUTO":
            return not self.is_auto_allowlisted(command)
        if self.mode == "GRANULAR" and self.is_auto_verification(command):
            return False
        return True


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

    def evaluate_tool(self, tool_name: str, arguments: dict | None = None) -> PolicyDecision:
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

        # GRANULAR: القراءة والبحث الشبكي تلقائيان، بينما الكتابة والحذف
        # والأوامر العامة تحتاج موافقة. أوامر التحقق الآمنة تُقيّم أدناه.
        if self.mode == "GRANULAR" and perm in {Permission.READ, Permission.NETWORK}:
            return PolicyDecision(True, False, f"{perm.value}_auto_granular", "low")
        if self.mode == "GRANULAR" and tool_name == "run_command":
            command = str((arguments or {}).get("command", ""))
            auto = self._cmd_policy.is_auto_verification(command)
            return PolicyDecision(
                True,
                not auto,
                "verification_auto_granular" if auto else "command_requires_approval",
                "low" if auto else "high",
            )

        # قراءة واتصالات الشبكة في READONLY لا تعدل مساحة العمل.
        if perm == Permission.READ:
            return PolicyDecision(True, False, "read_ok", "low")
        if perm == Permission.NETWORK and self.mode == "READONLY":
            return PolicyDecision(True, False, "network_read_ok", "low")

        # الكتابة والتنفيذ والبحث الشبكي في ASK تحتاج موافقة.
        if self.mode == "AUTO" and tool_name == "run_command":
            command = str((arguments or {}).get("command", ""))
            if not self._cmd_policy.is_auto_allowlisted(command):
                return PolicyDecision(
                    False,
                    False,
                    "AUTO mode: command is outside the execution allowlist",
                    "high",
                )
        needs_approval = self.mode != "AUTO"
        risk = "high" if perm in {Permission.WRITE, Permission.EXECUTE} else "medium"
        return PolicyDecision(
            True,
            needs_approval,
            f"{perm.value}_requires_approval" if needs_approval else f"{perm.value}_auto",
            risk,
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
        if self.mode == "AUTO" and not self._cmd_policy.is_auto_allowlisted(command):
            return PolicyDecision(
                allowed=False,
                requires_approval=False,
                reason="AUTO mode: command is outside the execution allowlist",
                risk="high",
            )
        needs_approval = self._cmd_policy.requires_approval(command)
        return PolicyDecision(
            allowed=True,
            requires_approval=needs_approval,
            reason="command_auto" if not needs_approval else "command_requires_approval",
            risk="low" if not needs_approval else "high",
        )
