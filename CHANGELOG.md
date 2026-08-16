# Changelog

## v1.4.0
- Multi-model routing: fast (8B) استكشاف قرائي فقط، smart (70B) تعديل/تنفيذ/التزام.
- FAST_EXCLUDE يشمل run_command: الفصل "قراءة مقابل هندسة" حقيقي وليس شكليًا.
- edit_mode لاصق داخل الـ turn فقط (begin_turn يعيدها False).
- REPAIR_SIGNALS محددة (لا "error:" الفضفاضة) وتُفحص من آخر نتيجة أداة فقط.
- كل قرار توجيه يُبث مع reason؛ التصعيد يُسجل كحدث
  escalated · edit_intent_without_tool / run_intent_without_tool.
- أوامر /fast /smart /auto للإجبار.

## v1.3.0
- بث tokens حي داخل الـ TUI مع تحديث مخنق (150ms).
- إنهاء صمت "Thought for Ns": أول token يظهر فور وصوله.

## v1.2.0
- Recovery Layer for non-native tool-calling models (استخراج الأداة من النص وصيغ patch البسيطة).

## v1.1.0
- هندسة إصدار: wheel قابلة للتثبيت على أي جهاز Termux.
- scripts/install_termux.sh للتثبيت بأمرة واحدة.
- scripts/check_secrets.sh + env.example.sh + .gitignore للأسرار.
- LICENSE (MIT).

## v1.0.0
- إغلاق جميع الطبقات + `doctor` + توثيق شامل.
- تحصين Provider: تنظيف ASCII للمفتاح/الرابط + RuntimeError واضح.
- عرض الإعدادات الفعّالة عند الإقلاع (key masked).

## v0.7.0
- MCP Plugins: عميل JSON-RPC، مدير خوادم، تسجيل أدوات ديناميكي،
  خادم Termux:API مرجعي.

## v0.6.0
- Context Budget Engine: estimator، أولويات P0–P5،
  compaction متعدد المراحل، حماية من context_length_exceeded.

## v0.5.0
- LSP pylsp: حلقة إصلاح ذاتي، تشخيصات تُلحق بالترقيع، تحلّل تدريجي.

## v0.4.0
- Sessions SQLite/WAL: حفظ لكل رسالة، /resume، تعقيم الذيل المعلّق.

## v0.3.0
- Git ذري: status/diff/log/init/checkpoint/commit/restore بموافقات.

## v0.2.0
- Repo Map (AST+regex، ترتيب بالمرجعية، ميزانية رموز).
- واجهة جمالية: badges، diffs أسطر، status متحرك، modes.

## v0.1.0
- النواة: TUI Textual، Jail آمن، Patch SEARCH/REPLACE، موافقات، تدقيق.
