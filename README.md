# ◈ agent — Termux Coder v1.0

وكيل برمجة مستقل (Autonomous Coding Agent) يعمل داخل Termux فقط،
مستوحى من OpenCode/Aider، مبني على 7 طبقات مرقّمة ومختبرة.

## التثبيت

    pkg install python git grep nodejs
    cd ~/termux-coder
    python -m venv .venv && source .venv/bin/activate
    pip install -e '.[dev]'
    pip install python-lsp-server   # اختياري: LSP

## الفحص والتشغيل

    termux-coder doctor                       # فحص البيئة
    termux-coder --workspace ~/مشروعك         # واجهة TUI
    termux-coder --cli --workspace ~/مشروعك   # وضع CLI

## الإعدادات (env)

| المتغير | البديل المسبوق | الافتراضي |
|---|---|---|
| OPENAI_API_KEY | TERMUX_CODER_OPENAI_API_KEY | EMPTY |
| OPENAI_BASE_URL | TERMUX_CODER_OPENAI_BASE_URL | openai |
| MODEL | TERMUX_CODER_MODEL | gpt-4o-mini |
| SECURITY | — | ASK (أو READONLY / GRANULAR / AUTO) |
| LSP / LSP_WAIT | — | 1 / 0.8 |
| REPO_MAP / REPO_MAP_BUDGET | — | 1 / 6000 |
| TERMUX_CODER_ORCHESTRATOR | — | 0 |
| TERMUX_CODER_SINGLE_TOOL_CALLS | — | 1 |
| TERMUX_CODER_WEB_SEARCH | — | 1 |
| TERMUX_CODER_RESEARCH_AUTO | — | 1 |
| TERMUX_CODER_CAPABILITY_ADAPTERS | — | 1 |
| TERMUX_CODER_SEARCH_PROVIDER | — | duckduckgo (`official_docs` متاح) |
| TERMUX_CODER_OFFICIAL_DOCS_DOMAINS | — | allowlist للنطاقات الرسمية |
| TERMUX_CODER_SEARCH_TIMEOUT | — | 10 seconds |
| TERMUX_CODER_SEARCH_MAX_RESPONSE_BYTES | — | 500000 |
| TERMUX_CODER_SEARCH_MAX_RESULTS | — | 5 |
| TERMUX_CODER_SEARCH_MAX_RETRIES | — | 2 |
| TERMUX_CODER_SEARCH_RETRY_BASE_DELAY | — | 0.25 seconds |
| TERMUX_CODER_SEARCH_CIRCUIT_FAILURES | — | 3 |
| TERMUX_CODER_SEARCH_CIRCUIT_COOLDOWN | — | 60 seconds |
| TERMUX_CODER_SEARCH_CACHE_TTL | — | 30 seconds |
| TERMUX_CODER_SEARCH_CACHE_ENTRIES | — | 32 |

يُرسل `TERMUX_CODER_SINGLE_TOOL_CALLS=1` قيمة `parallel_tool_calls=false` لمزود OpenAI-compatible، وهو الوضع المناسب لنماذج Llama المحلية التي لا تقبل عدة tool calls في الاستجابة نفسها. يمكن ضبطه إلى `0` فقط مع مزود يدعم الاستدعاءات المتوازية.

ملف جاهز: ~/termux-coder/env_nvidia.sh (اقتباسات إنجليزية فقط!)
ثم: echo "source ~/termux-coder/env_nvidia.sh" >> ~/.bashrc

## أوامر الجلسة (داخل الواجهة)

    /sessions   قائمة الجلسات
    /resume     استئناف أحدث جلسة (بعد قتل العملية)
    /new        جلسة جديدة
    /exit       خروج

## اختصارات

    shift+tab   تبديل الوضع: accept edits ↔ plan mode
    ctrl+o      توسيع آخر كتلة قابلة للطي
    ctrl+t      إظهار/إخفاء شجرة الملفات

## نموذج الأمان

- Workspace Jail: resolve + is_relative_to (لا startswith).
- لا write_file: التعديل فقط عبر apply_patch بعد read_file.
- في وضع ASK: القراءة تلقائية، بينما الشبكة والكتابة والأوامر وعمليات Git تطلب موافقة.
- في وضع GRANULAR: القراءة والبحث الشبكي وأوامر التحقق المسموح بها (`pytest` و`ruff` و`mypy` و`pyright` و`python -m pytest/compileall/unittest`) تعمل تلقائيًا؛ التعديل والحذف والأوامر العامة تطلب موافقة، والأنماط الخطرة مرفوضة دائمًا.
- في وضع READONLY: القراءة والبحث مسموحان، والكتابة والتنفيذ مرفوضان. وضع AUTO يتجاوز الموافقة وهو غير موصى به على الهاتف.
- نسخ احتياطية في .termux_coder/backups + تدقيق في audit.jsonl.
- `SecretScrubber` ينقح الحقول الحساسة والأنماط المعروفة قبل كتابة أي سجل JSONL؛ التنقيح طبقة خصوصية وليس ضمانًا لاكتشاف كل سر مخصص.
- Git discipline: checkpoint قبل المهام، commit ببادئة "agent:".

### تشغيل السياسة المتدرجة

لتمكين التشغيل التلقائي الآمن للقراءة والبحث والتحقق فقط، استخدم:

```sh
export SECURITY=GRANULAR
export TERMUX_CODER_ORCHESTRATOR=1
termux-coder --workspace ~/my-project
```

يبقى Safe Preview والموافقة وRollback مطلوبة قبل أي تعديل، بينما لا تؤدي موافقة الأداة إلى تجاوز Workspace Jail أو الأنماط المحظورة.

## P4.1: Audit Redaction

يُمرّر كل payload إلى `SecretScrubber` داخل `AuditLog` قبل التخزين. التنقيح يشمل مفاتيح مثل `api_key` و`password` و`cookie` و`authorization`، وأنماطًا معروفة لمفاتيح OpenAI وGitHub وAWS وBearer tokens وروابط credentials. لا يغيّر التنقيح البيانات المستخدمة في التنفيذ؛ فهو يعمل عند حد التخزين فقط، مع بقاء الحاجة إلى عدم إرسال الأسرار إلى الوكيل أصلًا.

## P4.2: Research Provider Hardening

يمر مزود البحث عبر `ResilientWebSearchProvider` عند تشغيل Agent. الطبقة تضيف retry محدودًا للأخطاء المؤقتة، cache قصيرة العمر، circuit breaker بعد فشل متكرر، وhealth metadata تظهر في أحداث البحث وسجل التدقيق. لا تعيد المحاولة للأخطاء غير المؤقتة، ولا تغيّر سياسة الموافقة أو صلاحية الأداة.

```text
retry: 2 محاولات إضافية كحد افتراضي
backoff: 0.25s ثم 0.5s
circuit: 3 failures → 60s cooldown
cache: 30s TTL و32 نتيجة كحد أقصى
```

## P4.4a: Doctor Report

يحتوي المشروع الآن على تقرير Doctor موحد يعيد فحوصًا محلية معزولة دون تشغيل أوامر التحقق أو فحوص الشبكة. المخرجات باللغة الإنجليزية فقط، ويمكن طلب JSON صالح للـCI:

```sh
python -m termux_coder doctor --workspace ~/my-project
python -m termux_coder doctor --workspace ~/my-project --json
python -m termux_coder doctor --workspace ~/my-project --verbose
```

كل فحص يعيد `ok` أو `warning` أو `error` أو `skipped` مع الفئة والمدة والتفاصيل المنقحة. التحذيرات لا تجعل الأمر يفشل، بينما `error` و`timeout` يعيدان exit code يساوي 1. الخيار `--network` محجوز للمرحلة التالية ولا ينفذ live probes في P4.4a.

## P4.3: Verification Threat Model

تشغيل `pytest` أو أي فحص للمشروع ليس قراءة آمنة تلقائيًا؛ فالفحوص قد تحمل `conftest.py` أو plugins أو كود المشروع. لذلك يطلب `VerificationRunner` صيغة argv في `.termux-coder.toml`، يرفض shell strings و`python -c` وتشغيل ملفات Python مباشرة، يقيّد وحدات Python المسموحة، يفرض timeout صلبًا قدره 30 ثانية، يحد المخرجات، ويوقف process group عند التعليق. كما يوقف حلقة الإصلاح بعد ثلاث محاولات افتراضيًا ويستخدم rollback عند توفر PatchPlan.

التفاصيل والحدود موثقة في [Verification Threat Model](docs/verification-threat-model.md).

## البحث عبر الإنترنت والمعرفة الموثقة

يحتوي النظام على أداة `web_search` للبحث الشبكي للقراءة فقط، وتعمل عبر `Network Policy` ومزود Async قابل للتبديل. نتائج البحث تُعامل دائمًا كبيانات ويب غير موثوقة، ولا تمنح موافقة على تعديل الملفات أو تشغيل الأوامر. يدعم `TERMUX_CODER_SEARCH_PROVIDER=official_docs` مزودًا مقيدًا يعيد فقط النتائج الواقعة ضمن allowlist للنطاقات الرسمية، ويستخدم DuckDuckGo كمحرك جمع أولي دون السماح بمرور الروابط الخارجية.

توجد طبقة `Capability Adapter Layer` في `src/termux_coder/core/capabilities.py`. تسجل هذه الطبقة مزودي القدرات بشكل صريح، وتعرض وصفًا تدقيقيًا لكل قدرة، وتبقي `PolicyEngine` الجهة الوحيدة التي تقرر السماح والموافقة. لا يستطيع الـ adapter الكتابة أو تنفيذ shell commands؛ دوره هو تمرير بيانات البحث غير الموثوقة فقط. يعمل `DuckDuckGoProvider` عبر `WebSearchCapabilityAdapter` افتراضيًا، ويمكن اختيار `OfficialDocsProvider` عبر `TERMUX_CODER_SEARCH_PROVIDER=official_docs`. يمكن الرجوع إلى المسار القديم عبر `TERMUX_CODER_CAPABILITY_ADAPTERS=0`.

توجد عقود المعرفة في `src/termux_coder/models/research.py`:

| العقد | الوظيفة |
|---|---|
| `TaskIntent` | يحدد المهمة وما إذا كانت تحتاج وثائق حديثة |
| `EvidenceItem` | يمثل مقتطفًا محدودًا من مصدر ويب مع الإصدار والبصمة |
| `ResearchPacket` | يربط الأدلة بالنية والمصادر المختارة ومستوى الثقة |
| `SymbolTarget` | يحدد دالة أو صنفًا أو method فريدًا لتعديل ضيق |

تم تفعيل حالة `RESEARCHING` في `AgentOrchestrator`، وإضافة `fetch_page` لجلب صفحات HTTP(S) العامة للقراءة فقط مع فحص SSRF والـredirects ونوع المحتوى والحجم. كما يُستدعى `ResearchCoordinator` تلقائيًا للمهام التي تطلب وثائق حديثة، ويحوّل نتائج البحث والصفحات إلى `EvidenceItem` ويجمعها في `ResearchPacket` مع ترتيب المصادر والبصمات ومستوى الثقة. يُحفظ packet في حالة الجلسة، ولا يبدأ الوكيل استدعاء النموذج التنفيذي قبل إكمال بوابة البحث. تبقى الصفحات والنتائج بيانات ويب غير موثوقة ولا تمنح موافقة على تعديل الملفات. يمر البحث عبر `CapabilityRegistry` عند تفعيل طبقة adapters، مع fallback صريح إلى المزود القديم عند تعطيل feature flag.

يدعم النظام الآن `apply_symbol_patch` لتعديل دالة أو صنف أو method Python بعد حلّه عبر AST. يرفض الرمز المفقود أو المكرر، يتحقق من `expected_signature` وبصمة القراءة، ويولّد Diff ضيقًا يمر عبر Safe Preview والموافقة وVerificationRunner مثل patch العادي. راجع [وثيقة التصميم المعماري](docs/architecture.md) للتدفق الكامل وحدود الثقة.

## الطبقات

    v0.1 النواة + TUI + الأمان + Patch
    v0.2 Repo Map + الجماليات
    v0.3 Git ذري
    v0.4 Sessions (SQLite/WAL)
    v0.5 LSP (pylsp) self-healing
    v0.6 Context Budget Engine
    v0.7 MCP Plugins

## استكشاف الأخطاء

| العَرَض | الحل |
|---|---|
| لوحة المفاتيح لا تظهر | زر ⌨ في صف الأزرار، أو KEYBOARD في termux.properties |
| 401 Unauthorized | source ~/.bashrc (المتغيرات لا تُحمّل تلقائيًا) |
| ascii codec error | قيمة المفتاح تحوي حروفًا عربية/اقتباسات «» |
| قُتلت العملية | أعد التشغيل ثم /resume |
| lsp off | pip install python-lsp-server |

## التطوير

    pytest -q          # حزمة الاختبارات الكاملة
