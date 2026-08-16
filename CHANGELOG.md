# Changelog

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
