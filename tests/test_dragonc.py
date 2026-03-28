import pytest

from dragonc import DragonSyntaxError, DragonTypeError, transpile


def test_transpile_typed_let_and_print():
    src = 'let nome: string = "Dragon"\nprint(nome)\n'
    py = transpile(src).python_code
    assert 'nome: str = "Dragon"' in py
    assert "print(nome)" in py


def test_transpile_function_with_typed_params():
    src = "func soma(a: int, b: int)\nreturn a + b\nend\n"
    py = transpile(src).python_code
    assert "def soma(a: int, b: int):" in py
    assert "return a + b" in py


def test_function_call_with_string_return_type():
    src = (
        "func saudacao(nome: string)\n"
        'return "Olá, " + nome\n'
        "end\n"
        'let msg: string = saudacao("Dragon")\n'
        "print(msg)\n"
    )
    py = transpile(src).python_code
    assert 'msg: str = saudacao("Dragon")' in py


def test_transpile_if_else_requires_bool_condition():
    src = 'let x: int = 1\nif x == 1\nprint("ok")\nelse\nprint("erro")\nend\n'
    py = transpile(src).python_code
    assert "if x == 1:" in py
    assert "else:" in py


def test_transpile_while():
    src = "let x: int = 0\nwhile x < 3\nprint(x)\nx = x + 1\nend\n"
    py = transpile(src).python_code
    assert "while x < 3:" in py
    assert "x = x + 1" in py


def test_else_without_if_raises_syntax_error():
    src = 'else\nprint("erro")\nend\n'
    with pytest.raises(DragonSyntaxError):
        transpile(src)


def test_transpile_input_string_type():
    src = 'let nome: string = input("Seu nome: ")\nprint(nome)\n'
    py = transpile(src).python_code
    assert 'nome: str = input("Seu nome: ")' in py
    assert "print(nome)" in py


def test_type_error_on_mismatched_typed_let():
    src = 'let ativo: bool = 10\n'
    with pytest.raises(DragonTypeError):
        transpile(src)


def test_type_error_on_reassignment():
    src = 'let idade: int = 20\nidade = "vinte"\n'
    with pytest.raises(DragonTypeError):
        transpile(src)


def test_type_error_on_if_non_bool_condition():
    src = 'let x: int = 1\nif x\nprint("x")\nend\n'
    with pytest.raises(DragonTypeError):
        transpile(src)


def test_type_error_on_unknown_variable_use():
    src = "print(nome)\n"
    with pytest.raises(DragonTypeError):
        transpile(src)


def test_bool_literal_lowercase_is_supported():
    src = "let ativo: bool = true\nif ativo\nprint(\"ok\")\nend\n"
    py = transpile(src).python_code
    assert "ativo: bool = True" in py


def test_type_error_on_conflicting_function_return_types():
    src = "func foo(a: bool)\nif a\nreturn 1\nelse\nreturn false\nend\nend\n"
    with pytest.raises(DragonTypeError):
        transpile(src)
