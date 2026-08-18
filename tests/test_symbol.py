import pytest
from pydantic import ValidationError

from termux_coder.tools.symbol import (
    SymbolTarget,
    ExtractedSymbol,
    extract_python_symbols,
    resolve_symbol,
    SymbolResolutionError,
)


def test_extract_function():
    source = "def foo(a, b):\n    return a + b\n"
    symbols = extract_python_symbols(source)
    assert len(symbols) == 1
    assert symbols[0].name == "foo"
    assert symbols[0].kind == "function"
    assert symbols[0].signature == "def foo(a, b):"


def test_extract_class_and_method():
    source = '''
class MyClass:
    """docstring"""
    
    def my_method(self):
        pass
    
    async def my_async_method(self):
        pass
'''
    symbols = extract_python_symbols(source)
    assert len(symbols) == 3
    assert symbols[0].name == "MyClass"
    assert symbols[0].kind == "class"
    assert symbols[0].signature == "class MyClass:"
    
    assert symbols[1].name == "MyClass.my_method"
    assert symbols[1].kind == "method"
    assert symbols[1].signature == "def my_method(self):"

    assert symbols[2].name == "MyClass.my_async_method"
    assert symbols[2].kind == "method"
    assert symbols[2].signature == "async def my_async_method(self):"


def test_resolve_symbol_success():
    source = "def foo(a, b):\n    return a + b\n"
    target = SymbolTarget(path="test.py", name="foo", kind="function", expected_signature="def foo(a, b):")
    match = resolve_symbol(source, target)
    assert match.name == "foo"


def test_resolve_symbol_not_found():
    source = "def bar(): pass\n"
    target = SymbolTarget(path="test.py", name="foo", kind="function")
    with pytest.raises(SymbolResolutionError, match="not found"):
        resolve_symbol(source, target)


def test_resolve_symbol_ambiguous():
    source = "def foo(): pass\n\ndef foo(): pass\n"
    target = SymbolTarget(path="test.py", name="foo", kind="function")
    with pytest.raises(SymbolResolutionError, match="Ambiguous"):
        resolve_symbol(source, target)


def test_resolve_symbol_signature_mismatch():
    source = "def foo(a, b):\n    return a + b\n"
    target = SymbolTarget(path="test.py", name="foo", kind="function", expected_signature="def foo(c):")
    with pytest.raises(SymbolResolutionError, match="Signature mismatch"):
        resolve_symbol(source, target)


def test_resolve_symbol_signature_match_multiline():
    source = "def foo(\n    a,\n    b\n):\n    return a + b\n"
    target = SymbolTarget(path="test.py", name="foo", kind="function", expected_signature="def foo(a, b):")
    match = resolve_symbol(source, target)
    assert match.name == "foo"
