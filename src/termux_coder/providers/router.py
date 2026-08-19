from __future__ import annotations

EDIT_KEYWORDS = (
    "عدّل", "عدل", "غيّر", "غير", "أصلح", "اصلح", "أضف", "اضف",
    "أنشئ", "انشئ", "احذف", "استبدل", "بدّل", "رقّع", "اكتب",
    "fix", "change", "edit", "patch", "refactor", "implement",
    "create", "write", "remove", "delete", "replace", "update", "add ",
)

RUN_KEYWORDS = (
    "شغّل", "شغل", "اختبر", "نفّذ", "نفذ",
    "run ", "execute", "pytest", "npm test", "build", "install",
)

# طلبات إنتاج مخرجات أو حفظ نتيجة البحث في ملف تحتاج أدوات smart.
SOFTWARE_TASK_KEYWORDS = (
    "code", "coding", "repository", "repo", "workspace", "file", "function",
    "class", "module", "package", "python", "rust", "javascript", "typescript",
    "bug", "error", "exception", "test", "tests", "pytest", "diagnostic",
    "lsp", "api", "dependency", "dependencies", "refactor", "review", "implement",
)


OUTPUT_KEYWORDS = (
    "في ملف", "بملف", "احفظ", "سجل", "خزّن", "ملف اسمه", "ملف باسم",
    "into a file", "to a file", "save it", "save as", "write to",
    "summarize into", "report file", "output file",
)

# إشارات فشل محددة فقط — لا "error:" الفضفاضة
REPAIR_SIGNALS = (
    "patch error",
    "lsp diagnostics:",
    "traceback",
    "failed",
    "exit: 1",
    "exit=1",
    "process exited with code 1",
    "test failed",
    "syntaxerror",
    "nameerror",
    "typeerror",
    "importerror",
    "modulenotfounderror",
    "rejected",
)

# fast = استكشاف قرائي فقط؛ أي تعديل/تنفيذ حصري لـ smart
FAST_EXCLUDE = {
    "apply_patch",
    "apply_symbol_patch",
    "apply_patch_plan",
    "write_file",
    "delete_file",
    "run_command",
    "git_commit",
    "git_restore",
}


class ModelRouter:
    """توجيه حتمي رخيص، بأسباب قابلة للتدقيق في كل قرار."""

    def __init__(
        self,
        fast,
        smart,
        fast_label: str,
        smart_label: str,
        ui,
        software_engineer_mode: bool = False,
    ):
        self.fast = fast
        self.smart = smart
        self.fast_label = fast_label
        self.smart_label = smart_label
        self.ui = ui
        self.software_engineer_mode = software_engineer_mode
        self.forced: str | None = None
        self.edit_mode = False  # لاصق داخل الـ turn فقط

    def begin_turn(self) -> None:
        """بداية كل user turn: يعود الاستكشاف الرخيص ممكنًا."""
        self.edit_mode = False

    @staticmethod
    def looks_like_edit(text: str) -> bool:
        low = text.lower()
        return any(k in low for k in EDIT_KEYWORDS) or any(k in low for k in OUTPUT_KEYWORDS)

    @staticmethod
    def looks_like_run(text: str) -> bool:
        low = text.lower()
        return any(k in low for k in RUN_KEYWORDS)

    @staticmethod
    def looks_like_software_task(text: str) -> bool:
        low = text.lower()
        return any(k in low for k in SOFTWARE_TASK_KEYWORDS)

    def tier_for_round(self, round_idx: int, user_text: str, messages: list[dict]):
        """يعيد (tier, reason) — السبب يُسجل كحدث للتدقيق."""
        if round_idx == 0:
            if self.forced:
                return self.forced, "forced"
            if self.looks_like_edit(user_text):
                return "smart", "edit_intent"
            if self.looks_like_run(user_text):
                return "smart", "run_intent"
            if self.software_engineer_mode and self.looks_like_software_task(user_text):
                return "smart", "software_engineer_mode"
            if self.edit_mode:
                return "smart", "edit_mode"
            return "fast", "exploration"

        if self.forced:
            return self.forced, "forced"
        if self.edit_mode:
            return "smart", "edit_mode"

        # آخر نتيجة أداة فقط — لا نبش في التاريخ
        for m in reversed(messages):
            if m.get("role") == "tool":
                content = (m.get("content") or "").lower()
                if any(s in content for s in REPAIR_SIGNALS):
                    return "smart", "repair_signal"
                break
        return "fast", "exploration"

    def provider_for(self, tier: str):
        return self.smart if tier == "smart" else self.fast

    def label_for(self, tier: str) -> str:
        return self.smart_label if tier == "smart" else self.fast_label

    def note_edit(self, tool_name: str) -> None:
        if tool_name in {"apply_patch", "apply_symbol_patch", "apply_patch_plan", "write_file", "delete_file", "git_commit", "git_restore"}:
            self.edit_mode = True
