from dragonc import transpile


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
