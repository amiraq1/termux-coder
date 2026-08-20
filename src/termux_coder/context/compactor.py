from __future__ import annotations

import re
from .estimator import TokenEstimator
from .priority import ContextItem


class CompactionStrategy:
    """
    استراتيجيات الضغط:
    A. حذف outputs قديمة غير مهمة
    B. اختصار المحادثة إلى ملخص
    C. اختصار Repo Map
    """

    def __init__(self, estimator: TokenEstimator):
        self.estimator = estimator

    def compact_tool_output(self, item: ContextItem) -> ContextItem:
        """
        ضغط مخرجات أداة طويلة إلى ملخص.
        يحتفظ بـ: command, exit code, summary, أول 3 أخطاء.
        """
        text = item.content

        # استخراج command من metadata
        command = item.metadata.get("command", "unknown")
        exit_code = item.metadata.get("exit", "?")

        # تلخيص
        lines = text.splitlines()
        total_lines = len(lines)

        # استخراج الأخطاء
        errors = []
        for line in lines:
            if re.search(r"\b(error|fail|exception)\b", line, re.IGNORECASE):
                errors.append(line.strip())
                if len(errors) >= 3:
                    break

        # بناء الملخص
        summary_lines = [
            f"Command: {command}",
            f"Exit: {exit_code}",
            f"Output: {total_lines} lines",
        ]

        if errors:
            summary_lines.append("")
            summary_lines.append("Errors:")
            summary_lines.extend(errors[:3])
        else:
            summary_lines.append("Status: success (no errors)")

        compacted = "\n".join(summary_lines)

        return ContextItem(
            content=compacted,
            kind="tool_summary",
            priority=item.priority,
            compressible=False,  # الملخص النهائي
            source_messages=[seq for seq in item.source_messages] if item.source_messages else [],
            metadata={
                "original_size": self.estimator.estimate(text),
                "compacted_size": self.estimator.estimate(compacted),
                "tool_call_id": item.metadata.get("tool_call_id"),
            },
        )

    def compact_conversation(
        self, items: list[ContextItem], current_task: str
    ) -> ContextItem:
        """
        ضغط محادثة قديمة إلى ملخص مهمة.
        
        يُنتج:
        Task: <current_task>
        Progress:
        - <action 1>
        - <action 2>
        - ...
        """
        progress = []

        for item in items:
            if item.kind == "tool":
                # استخراج اسم الأداة من metadata
                tool_name = item.metadata.get("tool_name", "tool")
                progress.append(f"- Used {tool_name}")
            elif item.kind == "user" and item.content:
                first_sentence = item.content.split(".")[0][:100]
                progress.append(f"- Requested: {first_sentence}")
            elif item.kind == "assistant" and item.content:
                # استخراج أول جملة
                first_sentence = item.content.split(".")[0][:100]
                progress.append(f"- {first_sentence}")

        # إزالة التكرارات
        progress = list(dict.fromkeys(progress))[:10]

        summary = f"Task: {current_task}\n\nProgress:\n" + "\n".join(progress)

        source_seqs = []
        for item in items:
            source_seqs.extend(item.source_messages)

        return ContextItem(
            content=summary,
            kind="summary",
            priority=2,  # الملخص نفسه P2
            compressible=False,
            source_messages=source_seqs,
            metadata={"original_items": len(items)},
        )

    def compact_repo_map(self, map_text: str, focus: str = "") -> str:
        """
        ضغط Repo Map: الاحتفاظ فقط بالرموز المتعلقة بـ focus.
        """
        if not focus:
            # لا focus → الاحتفاظ بأول 50% فقط
            lines = map_text.splitlines()
            half = len(lines) // 2
            return "\n".join(lines[:half]) + "\n... (truncated)"

        # focus موجود → فلترة
        focus_lower = focus.lower()
        lines = map_text.splitlines()
        filtered = []

        for line in lines:
            if focus_lower in line.lower():
                filtered.append(line)

        if not filtered:
            # لا تطابق → الاحتفاظ بأول 30%
            third = len(lines) // 3
            return "\n".join(lines[:third]) + "\n... (truncated, no matches)"

        return "\n".join(filtered)
