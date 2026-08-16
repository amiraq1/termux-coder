from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .budget import BudgetManager
    from .estimator import TokenEstimator
    from .priority import ContextItem


class ContextAssembler:
    """
    تجميع السياق النهائي من عناصر مُدارة.
    """

    def __init__(self, estimator: TokenEstimator, budget: BudgetManager):
        self.estimator = estimator
        self.budget = budget

    def assemble(self, items: list[ContextItem]) -> list[dict]:
        """
        تحويل ContextItems إلى رسائل LLM.
        
        1. fit ضمن الميزانية
        2. تحويل إلى message dicts
        """
        fitted = self.budget.fit(items)

        messages = []
        for item in fitted:
            # We map kinds back to standard roles if needed.
            # 'user', 'assistant', 'system', 'tool' are standard.
            # Others like 'map', 'lsp' usually come in as 'system' or are folded.
            # But based on the current logic, they are kept as kind. 
            # We will map non-standard kinds to 'system' to satisfy API.
            role = item.kind if item.kind in ("system", "user", "assistant", "tool") else "system"
            
            msg = {"role": role, "content": item.content}

            # إعادة tool_calls إذا كانت موجودة
            if "tool_calls" in item.metadata:
                msg["tool_calls"] = item.metadata["tool_calls"]

            # إعادة tool_call_id إذا كانت موجودة
            if "tool_call_id" in item.metadata:
                msg["tool_call_id"] = item.metadata["tool_call_id"]

            messages.append(msg)

        return messages

    def stats(self, items: list[ContextItem]) -> dict:
        """إحصائيات السياق للأغراض التشخيصية."""
        total = self.estimator.estimate([item for item in items])
        by_priority = {}
        by_kind = {}

        for item in items:
            size = self.estimator.estimate([item])
            by_priority[item.priority] = by_priority.get(item.priority, 0) + size
            by_kind[item.kind] = by_kind.get(item.kind, 0) + size

        return {
            "total_tokens": total,
            "budget": self.budget.input_budget,
            "usage_pct": (total / self.budget.input_budget * 100) if self.budget.input_budget else 0,
            "by_priority": by_priority,
            "by_kind": by_kind,
        }
