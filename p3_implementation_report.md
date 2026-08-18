# تقرير تنفيذ P3

## الحالة

تم تنفيذ النسخة المتوافقة مع بنية `termux-coder` الحالية. لم تُستخدم واجهات المسودة القديمة مثل `termux_opencode` أو `WorkspaceService` أو `PatchEngine` أو `ApprovalToken`.

## المنجز

| المكون | التنفيذ |
|---|---|
| E2E | إضافة `tests/e2e/` بfixtures مبنية على `WorkspaceJail` و`ToolContext` و`AgentOrchestrator.run_turn()` و`grant_approval()` |
| دورة Safe Preview | اختبار النجاح والرفض وتغير الملف بعد المعاينة والتراجع |
| VerificationRunner | إضافة `core/verification.py` مع TOML مضبوط، argv، allowlist، timeout، bounded output، process-group cleanup |
| VERIFYING | دمج مرحلة التحقق في `AgentOrchestrator` مع نتائج منظمة محفوظة كسجل tool ورسائل تدقيق ومحاولات إصلاح محدودة |
| Settings | إضافة مفاتيح `VERIFICATION`, `VERIFICATION_TIMEOUT`, `VERIFICATION_MAX_OUTPUT`, `VERIFICATION_MAX_REPAIRS` |
| CLI/TUI | عرض بداية التحقق ونتيجته للمستخدم |
| doctor | فحص WorkspaceJail وملف TOML باستخدام نفس VerificationRunner دون تنفيذ الأمر أو كشف مفتاح API |
| Python 3.10 | إضافة fallback إلى `tomli` واعتماد مشروط في `pyproject.toml` |

## الضوابط الأمنية

لا يُسمح بأمر Shell واحد من إعداد المشروع؛ يجب أن يكون الأمر argv في TOML. برامج التحقق محكومة بقائمة allowlist، وPython لا يُسمح له إلا بوحدات `pytest` أو `py_compile` أو `ruff` أو `mypy` عبر `-m`. لا يستخدم VerificationRunner `shell=True`، ويُنشئ process group ويُنهي المجموعة عند timeout أو إلغاء. تُحد المخرجات أثناء القراءة، ولا تُسجل مفاتيح API.

## نتائج الاختبارات

```text
149 passed, 1 skipped
```

كما نجحت اختبارات E2E وVerificationRunner و`git diff --check` وفحص الصياغة عبر `compileall`.

## حدود الإصدار

المسار القديم يبقى افتراضيًا لأن `TERMUX_CODER_ORCHESTRATOR` ما زال Feature Flag. لم يُنفذ بعد اختبار جهاز Termux فعلي أو اتصال مزود حقيقي. قبل جعل Orchestrator افتراضيًا، يجب تشغيل مصفوفة المزودين واختبار الاستئناف عبر subprocess مستقل على جهاز Android/Termux.
