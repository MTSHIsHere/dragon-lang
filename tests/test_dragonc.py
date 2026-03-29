import pytest

from dragonc import (
    DragonSyntaxError,
    DragonTypeError,
    cmd_compile,
    cmd_build,
    cmd_run,
    cmd_runbc,
    compile_to_bytecode,
    deserialize_bytecode,
    run_bytecode,
    serialize_bytecode,
    transpile,
)


def test_transpile_typed_let_and_print():
    src = 'let name: string = "Dragon"\nprint(name)\n'
    py = transpile(src).python_code
    assert 'name: str = "Dragon"' in py
    assert "print(name)" in py


def test_transpile_function_with_typed_params():
    src = "func add(a: int, b: int)\nreturn a + b\nend\n"
    py = transpile(src).python_code
    assert "def add(a: int, b: int):" in py
    assert "return a + b" in py


def test_function_call_with_string_return_type():
    src = (
        "func greeting(name: string)\n"
        'return "Hello, " + name\n'
        "end\n"
        'let msg: string = greeting("Dragon")\n'
        "print(msg)\n"
    )
    py = transpile(src).python_code
    assert 'msg: str = greeting("Dragon")' in py


def test_transpile_if_else_requires_bool_condition():
    src = 'let x: int = 1\nif x == 1\nprint("ok")\nelse\nprint("error")\nend\n'
    py = transpile(src).python_code
    assert "if x == 1:" in py
    assert "else:" in py


def test_transpile_while():
    src = "let x: int = 0\nwhile x < 3\nprint(x)\nx = x + 1\nend\n"
    py = transpile(src).python_code
    assert "while x < 3:" in py
    assert "x = x + 1" in py


def test_else_without_if_raises_syntax_error():
    src = 'else\nprint("error")\nend\n'
    with pytest.raises(DragonSyntaxError):
        transpile(src)


def test_transpile_input_string_type():
    src = 'let name: string = input("Your name: ")\nprint(name)\n'
    py = transpile(src).python_code
    assert 'name: str = input("Your name: ")' in py
    assert "print(name)" in py


def test_type_error_on_mismatched_typed_let():
    src = 'let active: bool = 10\n'
    with pytest.raises(DragonTypeError):
        transpile(src)


def test_type_error_on_reassignment():
    src = 'let age: int = 20\nage = "twenty"\n'
    with pytest.raises(DragonTypeError):
        transpile(src)


def test_type_error_on_if_non_bool_condition():
    src = 'let x: int = 1\nif x\nprint("x")\nend\n'
    with pytest.raises(DragonTypeError):
        transpile(src)


def test_type_error_on_unknown_variable_use():
    src = "print(name)\n"
    with pytest.raises(DragonTypeError):
        transpile(src)


def test_bool_literal_lowercase_is_supported():
    src = 'let active: bool = true\nif active\nprint("ok")\nend\n'
    py = transpile(src).python_code
    assert "active: bool = True" in py


def test_type_error_on_conflicting_function_return_types():
    src = "func foo(a: bool)\nif a\nreturn 1\nelse\nreturn false\nend\nend\n"
    with pytest.raises(DragonTypeError):
        transpile(src)


def test_bytecode_vm_runs_loop_and_prints(capsys):
    src = (
        "let x: int = 0\n"
        "while x < 3\n"
        "print(x)\n"
        "x = x + 1\n"
        "end\n"
    )
    program = compile_to_bytecode(src)
    run_bytecode(program)
    out = capsys.readouterr().out
    assert out == "0\n1\n2\n"


def test_bytecode_vm_runs_function_call(capsys):
    src = (
        "func add(a: int, b: int)\n"
        "return a + b\n"
        "end\n"
        "let r: int = add(2, 3)\n"
        "print(r)\n"
    )
    program = compile_to_bytecode(src)
    run_bytecode(program)
    out = capsys.readouterr().out
    assert out == "5\n"


def test_bytecode_serialization_roundtrip(capsys):
    src = 'let name: string = "Dragon"\nprint(name)\n'
    original = compile_to_bytecode(src)
    blob = serialize_bytecode(original)
    loaded = deserialize_bytecode(blob)
    run_bytecode(loaded)
    out = capsys.readouterr().out
    assert out == "Dragon\n"


def test_compile_and_runbc_commands(tmp_path, capsys):
    source = tmp_path / "program.dragon"
    source.write_text('print("ok")\n', encoding="utf-8")
    out_file = tmp_path / "program.dbc"

    compile_exit = cmd_compile(type("Args", (), {"file": str(source), "output": str(out_file)}))
    assert compile_exit == 0
    assert out_file.exists()

    run_exit = cmd_runbc(type("Args", (), {"file": str(out_file)}))
    assert run_exit == 0
    out = capsys.readouterr().out
    assert "ok\n" in out


def test_runbc_invalid_payload_returns_error(tmp_path, capsys):
    bad = tmp_path / "invalid.dbc"
    bad.write_text("not-json", encoding="utf-8")

    exit_code = cmd_runbc(type("Args", (), {"file": str(bad)}))
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "not valid JSON" in err


def test_build_cli_package(tmp_path):
    source = tmp_path / "program.dragon"
    source.write_text('print("ok")\n', encoding="utf-8")
    out_dir = tmp_path / "dist" / "mycli"

    exit_code = cmd_build(
        type(
            "Args",
            (),
            {
                "file": str(source),
                "output": str(out_dir),
                "name": "mycli",
                "app_type": "cli",
            },
        )
    )

    assert exit_code == 0
    assert (out_dir / "mycli.dbc").exists()
    assert (out_dir / "dragon-app.json").exists()
    assert (out_dir / "run.sh").exists()
    assert (out_dir / "run.bat").exists()
    assert not (out_dir / "mycli.desktop").exists()


def test_build_desktop_package(tmp_path):
    source = tmp_path / "program.dragon"
    source.write_text('print("ok")\n', encoding="utf-8")
    out_dir = tmp_path / "dist" / "mydesk"

    exit_code = cmd_build(
        type(
            "Args",
            (),
            {
                "file": str(source),
                "output": str(out_dir),
                "name": "mydesk",
                "app_type": "desktop",
            },
        )
    )

    assert exit_code == 0
    assert (out_dir / "mydesk.dbc").exists()
    assert (out_dir / "mydesk.desktop").exists()


def test_std_module_native_functions(capsys):
    src = (
        "import std\n"
        'let text: string = "Dragon"\n'
        "let n: int = length(text)\n"
        "print(n)\n"
        "print(uppercase(text))\n"
    )
    program = compile_to_bytecode(src)
    run_bytecode(program)
    out = capsys.readouterr().out
    assert out == "6\nDRAGON\n"


def test_transpile_with_std_import_injects_helpers():
    src = 'import std\nlet x: int = length("abc")\nprint(x)\n'
    py = transpile(src).python_code
    assert "def length(text: str):" in py
    assert 'x: int = length("abc")' in py


def test_import_local_module_by_cli_run(tmp_path, capsys):
    mod = tmp_path / "utils.dragon"
    mod.write_text(
        "func double(x: int)\n"
        "return x + x\n"
        "end\n",
        encoding="utf-8",
    )
    main = tmp_path / "main.dragon"
    main.write_text(
        "import utils\n"
        "let v: int = double(21)\n"
        "print(v)\n",
        encoding="utf-8",
    )
    exit_code = cmd_run(type("Args", (), {"file": str(main)}))
    assert exit_code == 0
    out = capsys.readouterr().out
    assert out == "42\n"


def test_import_module_namespace_calls(tmp_path, capsys):
    mod = tmp_path / "math.dragon"
    mod.write_text(
        "func add(a: int, b: int)\n"
        "return a + b\n"
        "end\n",
        encoding="utf-8",
    )
    main = tmp_path / "main.dragon"
    main.write_text(
        "import math\n"
        "let v: int = math.add(20, 22)\n"
        "print(v)\n",
        encoding="utf-8",
    )

    exit_code = cmd_run(type("Args", (), {"file": str(main)}))
    assert exit_code == 0
    out = capsys.readouterr().out
    assert out == "42\n"


def test_import_package_module_resolution(tmp_path, capsys):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    mod = pkg / "math.dragon"
    mod.write_text(
        "func add(a: int, b: int)\n"
        "return a + b\n"
        "end\n",
        encoding="utf-8",
    )
    main = tmp_path / "main.dragon"
    main.write_text(
        "import pkg.math\n"
        "let v: int = pkg.math.add(40, 2)\n"
        "print(v)\n",
        encoding="utf-8",
    )

    exit_code = cmd_run(type("Args", (), {"file": str(main)}))
    assert exit_code == 0
    out = capsys.readouterr().out
    assert out == "42\n"
