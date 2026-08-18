import ast
from typing import Literal

from pydantic import BaseModel, ConfigDict


class SymbolTarget(BaseModel):
    """
    عقد الاستهداف بناءً على الرمز (Symbol-aware Targeting).
    يُستخدم لتحديد دالة أو صنف معين داخل الملف لتعديله.
    """
    model_config = ConfigDict(extra="forbid")
    path: str
    name: str
    kind: Literal["function", "class", "method"]
    expected_signature: str | None = None


class ExtractedSymbol(BaseModel):
    """رمز تم استخراجه من الكود المصدري."""
    name: str
    kind: Literal["function", "class", "method"]
    signature: str
    start_line: int
    end_line: int


def _get_signature(node: ast.AST, source_lines: list[str]) -> str:
    """يستخرج السطر(الأسطور) الذي يحتوي على توقيع الدالة أو الصنف."""
    if not hasattr(node, "body") or not node.body:
        # إذا لم يكن هناك body، فإن العقدة كلها عبارة عن توقيع
        return "\n".join(source_lines[node.lineno - 1 : node.end_lineno])
    
    # التوقيع يمتد من بداية العقدة إلى ما قبل أول عنصر في الـ body
    first_body_node = node.body[0]
    # start_line لـ body
    body_start = first_body_node.lineno - 1
    # قد يكون هناك مسافات أو تعليقات قبل الـ body أو \n
    # سنأخذ الأسطر من بداية العقدة إلى السطر الذي يسبق الـ body كأفضل تقريب للتوقيع
    # ولكن إذا كان التوقيع والـ body على نفس السطر (مثل def f(): pass)
    if node.lineno - 1 == body_start:
        # التوقيع وجزء من الجسد في نفس السطر. نأخذ السطر الأول كاملا.
        return source_lines[node.lineno - 1]
    
    sig_lines = source_lines[node.lineno - 1 : body_start]
    return "\n".join(sig_lines).strip()


def extract_python_symbols(source: str) -> list[ExtractedSymbol]:
    """يستخرج الدوال والأصناف والطرق من كود Python المصدري باستخدام AST."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    lines = source.splitlines()
    symbols = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            sig = _get_signature(node, lines)
            symbols.append(ExtractedSymbol(
                name=node.name,
                kind="function",
                signature=sig,
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno
            ))
        elif isinstance(node, ast.ClassDef):
            sig = _get_signature(node, lines)
            symbols.append(ExtractedSymbol(
                name=node.name,
                kind="class",
                signature=sig,
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno
            ))
            # استخراج الـ methods داخل الصنف
            for child in node.body:
                if isinstance(child, ast.FunctionDef) or isinstance(child, ast.AsyncFunctionDef):
                    child_sig = _get_signature(child, lines)
                    symbols.append(ExtractedSymbol(
                        name=f"{node.name}.{child.name}",
                        kind="method",
                        signature=child_sig,
                        start_line=child.lineno,
                        end_line=child.end_lineno or child.lineno
                    ))
    return symbols


class SymbolResolutionError(Exception):
    pass


def resolve_symbol(source: str, target: SymbolTarget) -> ExtractedSymbol:
    """
    يبحث عن الرمز المستهدف في الكود المصدري.
    يرفض العثور على رموز مكررة أو غموض.
    """
    symbols = extract_python_symbols(source)
    matches = [s for s in symbols if s.name == target.name and s.kind == target.kind]
    
    if not matches:
        raise SymbolResolutionError(f"Symbol '{target.name}' of kind '{target.kind}' not found.")
    if len(matches) > 1:
        raise SymbolResolutionError(f"Ambiguous symbol '{target.name}': found {len(matches)} occurrences.")
    
    match = matches[0]
    
    # إذا تم توفير التوقيع المتوقع، نتحقق من مطابقته (مطابقة جزئية أو كاملة)
    if target.expected_signature:
        expected = target.expected_signature.strip().replace(" ", "").replace("\n", "")
        actual = match.signature.strip().replace(" ", "").replace("\n", "")
        if expected not in actual:
            raise SymbolResolutionError(
                f"Signature mismatch for '{target.name}'.\n"
                f"Expected: {target.expected_signature}\n"
                f"Actual: {match.signature}"
            )
            
    return match
