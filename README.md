# ◈ agent — Termux Coder v0.1

وكيل برمجة 안전第一 (safety-first) يعمل داخل Termux.

## التثبيت

    pkg install python git grep
    cd ~/termux-coder
    python -m venv .venv && source .venv/bin/activate
    pip install -e '.[dev]'

## الاختبارات

    pytest -q

## التشغيل

    export TERMUX_CODER_OPENAI_API_KEY="..."
    export TERMUX_CODER_MODEL="gpt-4o-mini"
    termux-coder --workspace ~/myproject          # TUI
    termux-coder --cli --workspace ~/myproject    # CLI

## الأوضاع الأمنية

- ASK (افتراضي): كل كتابة/أمر يتطلب موافقة.
- READONLY: القراءة والبحث فقط.
- AUTO: بدون موافقة (غير منصوح به).

## قواعد v0.1

- لا توجد أداة write_file؛ التعديل فقط عبر apply_patch.
- لا يمكن ترقيع ملف لم يُقرأ عبر read_file في نفس الجلسة.
- كل ترقيع يعرض diff ويطلب موافقة، مع نسخة احتياطية في
  `.termux_coder/backups/`.
- كل الأحداث تُسجل في `.termux_coder/audit.jsonl`.
