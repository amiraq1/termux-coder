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

    def fit(
        self,
        items: list[ContextItem],
        current_task: str = "",
        active_task_id: str | None = None,
        active_related_paths: set[str] | None = None,
    ) -> list[ContextItem]:
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

        def is_active(item: ContextItem) -> bool:
            if active_task_id and item.metadata.get("task_id") == active_task_id:
                return True
            if active_related_paths:
                item_paths = item.metadata.get("related_paths", [])
                if isinstance(item_paths, (list, tuple, set)):
                    return bool(set(item_paths) & active_related_paths)
            return False

        # المرحلة A: تلخيص P5 القديم، لكن لا نلمس عناصر Turn Bundle النشط.
        kept = []
        old_conversation = []
        for item in sorted_items:
            if item.priority == 5 and item.compressible and not is_active(item):
                old_conversation.append(item)
                continue
            kept.append(item)

        if old_conversation:
            from .compactor import CompactionStrategy

            strategy = CompactionStrategy(self.estimator)
            kept.append(
                strategy.compact_conversation(
                    old_conversation,
                    current_task or "continue the current task",
                )
            )

        total = sum(self.estimator.estimate(item.content) for item in kept)
        if total <= self.input_budget:
            return self._sort_by_original_order(kept, items)

        # المرحلة B: ضغط P4 (tool results قديمة)
        compacted = []
        for item in kept:
            if (
                item.priority == 4
                and item.compressible
                and item.kind == "tool"
                and not is_active(item)
            ):
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
            if item.priority == 3 and item.kind == "map" and not is_active(item):
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

        # المرحلة D: الملخص الناتج عن compact_conversation غير قابل للضغط.
        # تبقى P0/P1 محفوظة، ويمكن حذف P2 القابلة للضغط كحل أخير.

        # fallback: حذف P2 compressible
        final = []
        for item in further_compacted:
            if item.priority == 2 and item.compressible and not is_active(item):
                continue
            final.append(item)

        return self._sort_by_original_order(final, items)

    def _sort_by_original_order(
        self, items: list[ContextItem], original: list[ContextItem]
    ) -> list[ContextItem]:
        """استعادة الترتيب مع إبقاء العناصر الجديدة الناتجة عن الضغط."""
        original_order = {id(item): index for index, item in enumerate(original)}
        # Generated summaries/compacted items are appended stably after their
        # surviving originals instead of being discarded as unknown identities.
        return sorted(
            items,
            key=lambda item: original_order.get(id(item), len(original)),
        )

    def estimate(self, items: list[ContextItem]) -> int:
        """حساب الحجم الإجمالي."""
        return sum(self.estimator.estimate(item.content) for item in items)
