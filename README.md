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
    termux-coder --workspace ~/my-project     # الواجهة الرئيسية: CLI
    termux-coder --tui --workspace ~/my-project  # TUI fallback مؤقت

يعمل CLI افتراضيًا لتوفير واجهة مناسبة لشاشات Termux الصغيرة. يبقى Textual TUI متاحًا مؤقتًا عبر الخيار الصريح `--tui`. الخيار `--cli` القديم مخفي لكنه مدعوم للتوافق مع أوامر التشغيل السابقة.

يُخفى التفكير والتدفق المرحلي افتراضيًا، ولا يتم عرض reasoning الخام أو JSON الخاص باستدعاءات الأدوات. لعرض مؤشرات مختصرة ومؤشر تحميل اختياري استخدم `--show-thinking`، وللإخفاء الصريح استخدم `--hide-thinking`:

    python -m termux_coder run --workspace ~/my-project --show-thinking
    python -m termux_coder run --workspace ~/my-project --hide-thinking

يمكن تفعيل العرض افتراضيًا عبر `TERMUX_CODER_SHOW_THINKING=1`. عند وجود خيار CLI صريح تكون له الأولوية على متغير البيئة.

## الإعدادات (env)

| المتغير | البديل المسبوق | الافتراضي |
|---|---|---|
| PROVIDER | TERMUX_CODER_PROVIDER | auto |
| NVIDIA_API_KEY / NVIDIA_BASE_URL | TERMUX_CODER_NVIDIA_API_KEY / TERMUX_CODER_NVIDIA_BASE_URL | NVIDIA NIM |
| OPENAI_API_KEY / OPENAI_BASE_URL | TERMUX_CODER_OPENAI_API_KEY / TERMUX_CODER_OPENAI_BASE_URL | OpenAI |
| OPENROUTER_API_KEY / OPENROUTER_BASE_URL | TERMUX_CODER_OPENROUTER_API_KEY / TERMUX_CODER_OPENROUTER_BASE_URL | OpenRouter |
| GROQ_API_KEY / GROQ_BASE_URL | TERMUX_CODER_GROQ_API_KEY / TERMUX_CODER_GROQ_BASE_URL | Groq |
| TOGETHER_API_KEY / TOGETHER_BASE_URL | TERMUX_CODER_TOGETHER_API_KEY / TERMUX_CODER_TOGETHER_BASE_URL | Together |
| ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL | TERMUX_CODER_ANTHROPIC_API_KEY / TERMUX_CODER_ANTHROPIC_BASE_URL | Anthropic Messages API |
| GEMINI_API_KEY / GEMINI_BASE_URL | TERMUX_CODER_GEMINI_API_KEY / TERMUX_CODER_GEMINI_BASE_URL | Google Gemini API |
| MODEL | TERMUX_CODER_MODEL | gpt-4o-mini |
| PROVIDERS_CONFIG | TERMUX_CODER_PROVIDERS_CONFIG | optional JSON/YAML provider file |
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

### اختيار مزود النموذج

يدعم الوكيل مزودين متوافقين مع OpenAI API مثل NVIDIA NIM وOpenAI وOpenRouter وGroq وTogether، كما يدعم Anthropic Messages API وGoogle Gemini API عبر adapters مستقلة. الوضع الافتراضي `PROVIDER=auto` يختار أول مزود يملك مفتاحًا مهيأً حسب ترتيب الكتالوج. لا يحاول النظام استنتاج المزود من شكل المفتاح السري؛ يعتمد على اسم متغير البيئة الصريح لتجنب اختيار خاطئ أو كشف بيانات حساسة.

يمكن فرض مزود محدد:

```sh
export TERMUX_CODER_PROVIDER=groq
export GROQ_API_KEY='your-groq-key'
export GROQ_BASE_URL='https://api.groq.com/openai/v1'
```

أو استخدام NVIDIA NIM:

```sh
export TERMUX_CODER_PROVIDER=nvidia
export NVIDIA_API_KEY='your-nvidia-key'
```

للتوافق مع الإعداد القديم، يبقى `OPENAI_API_KEY` و`OPENAI_BASE_URL` مدعومين. أولوية المتغير المسبوق `TERMUX_CODER_` أعلى من المتغير العام. لا تُطبع قيم المفاتيح في CLI أو AuditLog؛ تظهر رسائل الأخطاء أسماء المتغيرات المطلوبة فقط.

### المزودون المخصصون من ملف خارجي

يمكن إضافة مزود OpenAI-compatible مخصص دون تعديل `PROVIDER_SPECS`. يكتشف الوكيل تلقائيًا الملفات التالية بالترتيب:

```text
{workspace}/.termux_coder/providers.json
{workspace}/.termux_coder/providers.yaml
{workspace}/.termux_coder/providers.yml
~/.termux_coder/providers.json
~/.termux_coder/providers.yaml
~/.termux_coder/providers.yml
```

يمكن أيضًا تحديد ملف صريح من CLI أو البيئة:

```sh
python -m termux_coder run \\
  --workspace ~/test-agent \\
  --providers-config ~/.termux_coder/providers.json

# أو
export TERMUX_CODER_PROVIDERS_CONFIG="$HOME/.termux_coder/providers.json"
```

مثال `providers.json`:

```json
{
  "providers": [
    {
      "name": "myprovider",
      "label": "My Provider",
      "category": "Popular",
      "popular": true,
      "protocol": "openai",
      "models": ["my-model-small", "my-model-large"],
      "key_env": "MYPROVIDER_API_KEY",
      "base_url_env": "MYPROVIDER_BASE_URL",
      "default_base_url": "https://api.example.com/v1"
    }
  ],
  "auto_order": ["myprovider", "nvidia", "openai"]
}
```

`key_env` و`base_url_env` هما اسما متغيري البيئة فقط؛ لا تضع قيمة المفتاح داخل الملف. يمكن حذف `base_url_env` عند الاكتفاء بـ`default_base_url`. الحقل `protocol` اختياري وقيمه `openai` أو `anthropic` أو `gemini`، والافتراضي `openai`. الحقول `label` و`category` و`popular` و`models` اختيارية وتستخدم لعرض القائمة التفاعلية؛ `category` يقبل `Popular` أو `Providers`. إذا لم يوجد `auto_order` تُضاف المزودات المخصصة بعد ترتيب المزودات المدمجة. المتغيرات المسبوقة بـ`TERMUX_CODER_` لها أولوية أعلى، مثل `TERMUX_CODER_MYPROVIDER_API_KEY`.

ملفات YAML اختيارية وتتطلب تثبيت `PyYAML`؛ JSON هو الخيار الموصى به في Termux لأنه لا يحتاج dependency إضافية. يرفض المحمل الحقول غير المعروفة، وحقول `shell` أو `headers` أو قيم المفاتيح، والروابط التي تحتوي credentials أو query أو fragment.

لإضافة Anthropic:

```json
{
  "name": "claude",
  "label": "Anthropic Claude",
  "protocol": "anthropic",
  "key_env": "ANTHROPIC_API_KEY",
  "base_url_env": "ANTHROPIC_BASE_URL",
  "default_base_url": "https://api.anthropic.com/v1",
  "models": ["claude-sonnet-4-5", "claude-opus-4-5"]
}
```

ولإضافة Gemini:

```json
{
  "name": "gemini",
  "label": "Google Gemini",
  "protocol": "gemini",
  "key_env": "GEMINI_API_KEY",
  "base_url_env": "GEMINI_BASE_URL",
  "default_base_url": "https://generativelanguage.googleapis.com/v1beta",
  "models": ["gemini-2.5-flash", "gemini-2.5-pro"]
}
```

Anthropic يستخدم Messages API مع `x-api-key` و`anthropic-version`، بينما Gemini يستخدم `generateContent`/`streamGenerateContent` مع `x-goog-api-key` وتحويل `functionCall` و`functionResponse`. لذلك لا يكفي تغيير `base_url` فقط؛ يجب تحديد `protocol` الصحيح. أما المزودون الآخرون فيجب أن يكونوا OpenAI-compatible.

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
    ctrl+a      فتح قائمة اختيار المزود والنموذج في TUI

عند تشغيل TUI، افتح القائمة عبر `Ctrl+A`. اكتب في `Search` لتصفية المزودين، استخدم الأسهم للتنقل و`Enter` للاختيار و`Esc` للإغلاق. تظهر علامة `✓` بجانب المزود الذي يملك مفتاحًا مهيأً. بعد اختيار المزود تظهر قائمة النماذج المعرفة في حقل `models` داخل ملف الإعدادات؛ إذا لم توجد، يعرض الوكيل النموذج الحالي فقط.

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

## P4.4b: Doctor Check Registry

أصبحت الفحوص مسجلة صراحةً عبر `DoctorCheckRegistry` و`CheckSpec`. لكل فحص اسم وفئة وtimeout مستقل بحد أقصى 30 ثانية. فشل فحص أو انتهاء مهله ينتج `CheckResult` مستقلًا ولا يمنع تشغيل الفحوص التالية. هذه الفحوص محلية وغير هدّامة؛ فالـtimeout يعزل نتيجة الفحص، لكنه ليس sandbox لقتل Python thread، لذلك لا يجوز تسجيل فحص يكتب ملفات أو ينفذ أوامر.

## P4.4c: Provider Health Metadata

يعرض فحص `provider_health` الحالة الفعلية للـ`ResilientWebSearchProvider` دون اتصال شبكي. تظهر حالة `healthy` أو `degraded`، وعدد الإخفاقات المتتالية، وحالة circuit breaker، ووقت التهدئة المتبقي، وعدد عناصر cache، وإعدادات resilience غير الحساسة. يعرض Doctor أيضًا `network_probe.performed=false` بوضوح؛ فالـlive probe مؤجل إلى `--network` في المرحلة التالية.

## P4.4d: Live Network Probe

يُفعّل فحص الشبكة صراحةً فقط عبر:

```sh
python -m termux_coder doctor --workspace ~/my-project --network
python -m termux_coder doctor --workspace ~/my-project --network --json
```

ينفذ `LiveNetworkProbe` طلب بحث واحدًا للقراءة فقط باستخدام المزود المهيأ، مع timeout محدود، retry/circuit policy الحالية، ونتيجة مختصرة لا تحتوي محتوى صفحات أو أسرارًا. لا يتم تشغيله في `doctor` العادي، ولا يمنح أي صلاحية كتابة أو تنفيذ. إذا فشل مزود واحد، تبقى بقية فحوص Doctor مستقلة.

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
