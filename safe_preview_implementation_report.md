# تقرير تنفيذ Safe Preview

## الحالة

تم تنفيذ محرك معاينة آمن متوافق مع البنية الحالية لمستودع `termux-coder` دون إنشاء طبقة PatchEngine موازية. يعتمد التنفيذ على `WorkspaceJail` و`tools.patch.parse_blocks()` و`apply_blocks()` و`make_diff()` نفسها التي يستخدمها `apply_patch`.

## التغييرات

| الملف | التغيير |
|---|---|
| `tools/preview.py` | إضافة `PatchPreviewService` و`PatchPreview` لحساب Diff وبصمات المصدر والترقيع والنتيجة دون كتابة |
| `models/contracts.py` | إضافة `PREVIEW_FAILED`، وربط `ApprovalGrant` ببصمات Preview، وإضافة Preview إلى `EvaluatedToolCall` |
| `core/orchestrator.py` | إنشاء Preview قبل موافقة `apply_patch`، عرض Diff الحقيقي، تسجيل preview في AuditLog، والتحقق من بصمات الموافقة قبل التنفيذ |
| `core/agent.py` | حقن خدمة Preview في Orchestrator الحقيقي فقط، مع إبقاء Mock Contexts مستقلة |
| `tools/edit.py` | التحقق من تطابق المسار والمصدر والترقيع والنتيجة مع Preview قبل الكتابة |
| `tests/test_preview.py` | اختبارات المعاينة، القراءة المسبقة، الغموض، بصمات الموافقة، وحمولة Diff المعروضة للمستخدم |

## الضمانات

قبل عرض الموافقة، يتحقق النظام من أن الملف داخل `WorkspaceJail`، وأن الملف الموجود تمت قراءته مسبقًا، وأن hash الملف لم يتغير، وأن كتل SEARCH/REPLACE صالحة وغير غامضة. ثم يحسب التغيير في الذاكرة فقط ويصدر Unified Diff من نفس محرك الترقيع الفعلي.

بعد موافقة المستخدم، تُربط الموافقة بـ`call_id` وبصمة المعاملات وبصمات المصدر والترقيع والنتيجة. وقبل الكتابة، تعيد `apply_patch` حساب هذه القيم وترفض التنفيذ إذا تغير أي جزء من المعاينة.

## نتائج الاختبار

```text
138 passed, 1 skipped
compileall: passed
git diff --check: passed
```

## حالة Git

التغييرات موجودة محليًا وغير مرفوعة بعد إلى GitHub. الملفات المعدلة أو الجديدة هي:

```text
src/termux_coder/core/agent.py
src/termux_coder/core/orchestrator.py
src/termux_coder/models/contracts.py
src/termux_coder/tools/edit.py
src/termux_coder/tools/preview.py
 tests/test_preview.py
```

لا يتم رفع هذه التغييرات إلا بعد طلب صريح منفصل.
