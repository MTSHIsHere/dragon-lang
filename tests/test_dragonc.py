import pytest

from dragonc import DragonSyntaxError, transpile


def test_transpile_let_and_print():
    src = 'let nome = "Dragon"\nprint(nome)\n'
    py = transpile(src).python_code
    assert 'nome = "Dragon"' in py
    assert "print(nome)" in py


def test_transpile_function():
    src = "func soma(a, b)\nreturn a + b\nend\n"
    py = transpile(src).python_code
    assert "def soma(a, b):" in py
    assert "return a + b" in py


def test_transpile_if_else():
    src = "let x = 1\nif x == 1\nprint(\"ok\")\nelse\nprint(\"erro\")\nend\n"
    py = transpile(src).python_code
    assert "if x == 1:" in py
    assert "else:" in py


def test_transpile_while():
    src = "let x = 0\nwhile x < 3\nprint(x)\nlet x = x + 1\nend\n"
    py = transpile(src).python_code
    assert "while x < 3:" in py
    assert "x = x + 1" in py


def test_else_without_if_raises_syntax_error():
    src = "else\nprint(\"erro\")\nend\n"
    with pytest.raises(DragonSyntaxError):
        transpile(src)


def test_transpile_input():
    src = 'let nome = input("Seu nome: ")\nprint(nome)\n'
    py = transpile(src).python_code
    assert 'nome = input("Seu nome: ")' in py
    assert 'print(nome)' in py
