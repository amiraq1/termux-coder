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
| TERMUX_CODER_SEARCH_PROVIDER | — | duckduckgo |
| TERMUX_CODER_SEARCH_TIMEOUT | — | 10 seconds |
| TERMUX_CODER_SEARCH_MAX_RESPONSE_BYTES | — | 500000 |
| TERMUX_CODER_SEARCH_MAX_RESULTS | — | 5 |

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
- Git discipline: checkpoint قبل المهام، commit ببادئة "agent:".

### تشغيل السياسة المتدرجة

لتمكين التشغيل التلقائي الآمن للقراءة والبحث والتحقق فقط، استخدم:

```sh
export SECURITY=GRANULAR
export TERMUX_CODER_ORCHESTRATOR=1
termux-coder --workspace ~/my-project
```

يبقى Safe Preview والموافقة وRollback مطلوبة قبل أي تعديل، بينما لا تؤدي موافقة الأداة إلى تجاوز Workspace Jail أو الأنماط المحظورة.

## البحث عبر الإنترنت والمعرفة الموثقة

يحتوي النظام على أداة `web_search` للبحث الشبكي للقراءة فقط، وتعمل عبر `Network Policy` ومزود Async قابل للتبديل. نتائج البحث تُعامل دائمًا كبيانات ويب غير موثوقة، ولا تمنح موافقة على تعديل الملفات أو تشغيل الأوامر.

توجد عقود المعرفة في `src/termux_coder/models/research.py`:

| العقد | الوظيفة |
|---|---|
| `TaskIntent` | يحدد المهمة وما إذا كانت تحتاج وثائق حديثة |
| `EvidenceItem` | يمثل مقتطفًا محدودًا من مصدر ويب مع الإصدار والبصمة |
| `ResearchPacket` | يربط الأدلة بالنية والمصادر المختارة ومستوى الثقة |
| `SymbolTarget` | يحدد دالة أو صنفًا أو method فريدًا لتعديل ضيق |

تم تفعيل حالة `RESEARCHING` في `AgentOrchestrator`، وإضافة `fetch_page` لجلب صفحات HTTP(S) العامة للقراءة فقط مع فحص SSRF والـredirects ونوع المحتوى والحجم. كما أصبح `ResearchCoordinator` يُستدعى تلقائيًا للمهام التي تطلب وثائق حديثة، ويحوّل نتائج البحث والصفحات إلى `EvidenceItem` ويجمعها في `ResearchPacket` مع ترتيب المصادر والبصمات ومستوى الثقة. يُحفظ packet في حالة الجلسة، ولا يبدأ الوكيل استدعاء النموذج التنفيذي قبل إكمال بوابة البحث. تبقى الصفحات والنتائج بيانات ويب غير موثوقة ولا تمنح موافقة على تعديل الملفات.

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
