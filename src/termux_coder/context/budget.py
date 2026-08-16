from __future__ import annotations

from .estimator import TokenEstimator
from .priority import ContextItem


class BudgetManager:
    """
    إدارة ميزانية السياق:
    - لا تتجاوز الحد الأقصى
    - تضغط العناصر حسب الأولوية
    - تحتفظ بـ P0 دائمًا
    """

    def __init__(
        self,
        max_tokens: int,
        output_reserve: int,
        estimator: TokenEstimator,
    ):
        self.max_tokens = max_tokens
        self.output_reserve = output_reserve
        self.estimator = estimator

    @property
    def input_budget(self) -> int:
        return self.max_tokens - self.output_reserve

    def fit(self, items: list[ContextItem]) -> list[ContextItem]:
        """
        ضبط العناصر لتناسب الميزانية.
        
        Pipeline:
        1. حساب الحجم الحالي
        2. إذا ضمن الميزانية → إرجاع كما هو
        3. وإلا → ضغط حسب الأولوية (P5 → P4 → P3 → P2)
        4. P0 و P1 لا تُضغط أبدًا
        """
        total = sum(self.estimator.estimate(item.content) for item in items)

        if total <= self.input_budget:
            return items

        # فرز حسب الأولوية (عكسي: P5 أولًا للضغط)
        sorted_items = sorted(items, key=lambda x: -x.priority)

        # المرحلة A: حذف P5 (محادثة قديمة)
        kept = []
        for item in sorted_items:
            if item.priority == 5 and item.compressible:
                continue  # حذف
            kept.append(item)

        total = sum(self.estimator.estimate(item.content) for item in kept)
        if total <= self.input_budget:
            return self._sort_by_original_order(kept, items)

        # المرحلة B: ضغط P4 (tool results قديمة)
        compacted = []
        for item in kept:
            if item.priority == 4 and item.compressible and item.kind == "tool":
                from .compactor import CompactionStrategy
                strategy = CompactionStrategy(self.estimator)
                compacted.append(strategy.compact_tool_output(item))
            else:
                compacted.append(item)

        total = sum(self.estimator.estimate(item.content) for item in compacted)
        if total <= self.input_budget:
            return self._sort_by_original_order(compacted, items)

        # المرحلة C: ضغط P3 (repo map)
        further_compacted = []
        for item in compacted:
            if item.priority == 3 and item.kind == "map":
                from .compactor import CompactionStrategy
                strategy = CompactionStrategy(self.estimator)
                new_content = strategy.compact_repo_map(item.content)
                further_compacted.append(ContextItem(
                    content=new_content,
                    kind=item.kind,
                    priority=item.priority,
                    compressible=False,  # تم الضغط
                    metadata=item.metadata,
                ))
            else:
                further_compacted.append(item)

        total = sum(self.estimator.estimate(item.content) for item in further_compacted)
        if total <= self.input_budget:
            return self._sort_by_original_order(further_compacted, items)

        # المرحلة D: ضغط P2 (ملخصات)
        # هنا يمكن تلخيص المحادثة الكاملة إلى task summary
        # لكن هذا يتطلب معرفة "current task" — نتركها للـ Assembler

        # fallback: حذف P2 compressible
        final = []
        for item in further_compacted:
            if item.priority == 2 and item.compressible:
                continue
            final.append(item)

        return self._sort_by_original_order(final, items)

    def _sort_by_original_order(
        self, items: list[ContextItem], original: list[ContextItem]
    ) -> list[ContextItem]:
        """استعادة الترتيب الأصلي بعد الضغط."""
        # استخدام index في original كـ sort key
        item_set = set(id(item) for item in items)
        return [item for item in original if id(item) in item_set]

    def estimate(self, items: list[ContextItem]) -> int:
        """حساب الحجم الإجمالي."""
        return sum(self.estimator.estimate(item.content) for item in items)
