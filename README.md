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
| SECURITY | — | ASK (أو READONLY / AUTO) |
| LSP / LSP_WAIT | — | 1 / 0.8 |
| REPO_MAP / REPO_MAP_BUDGET | — | 1 / 6000 |

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
- كل كتابة/أمر/commit/restore يمر بنافذة موافقة (وضع ASK).
- نسخ احتياطية في .termux_coder/backups + تدقيق في audit.jsonl.
- Git discipline: checkpoint قبل المهام، commit ببادئة "agent:".

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
