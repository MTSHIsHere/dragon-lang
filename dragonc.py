#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass


class DragonSyntaxError(Exception):
    pass


class DragonTypeError(Exception):
    pass


@dataclass
class CompileResult:
    python_code: str


FUNC_RE = re.compile(r"^func\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*?)\)\s*$")
LET_TYPED_RE = re.compile(r"^let\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(int|string|bool)\s*=\s*(.+)$")
LET_RE = re.compile(r"^let\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$")
IF_RE = re.compile(r"^if\s+(.+)$")
WHILE_RE = re.compile(r"^while\s+(.+)$")
ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$")
TYPE_NAMES = {"int", "string", "bool"}


@dataclass
class ScopeFrame:
    kind: str
    vars: dict[str, str]


@dataclass
class FuncInfo:
    params: list[tuple[str, str]]
    return_type: str | None = None


def _sanitize_line(line: str) -> str:
    return line.strip()


def _normalize_expr(expr: str) -> str:
    return re.sub(r"\b(true|false)\b", lambda m: "True" if m.group(1) == "true" else "False", expr)


def _dragon_type_to_python(type_name: str) -> str:
    if type_name == "string":
        return "str"
    return type_name


def _python_type_to_dragon(type_name: str) -> str:
    if type_name == "str":
        return "string"
    return type_name


def _parse_func_args(args: str, idx: int) -> list[tuple[str, str]]:
    raw_args = args.strip()
    if not raw_args:
        return []

    parsed: list[tuple[str, str]] = []
    seen_names: set[str] = set()

    for raw_arg in raw_args.split(","):
        piece = raw_arg.strip()
        if not piece:
            raise DragonSyntaxError(f"Linha {idx}: argumento vazio em declaração de função")

        name_and_type = piece.split(":", maxsplit=1)
        if len(name_and_type) != 2:
            raise DragonSyntaxError(
                f"Linha {idx}: parâmetros devem ser tipados (ex: a: int)"
            )

        name = name_and_type[0].strip()
        type_name = name_and_type[1].strip()

        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
            raise DragonSyntaxError(f"Linha {idx}: nome de parâmetro inválido: {name}")

        if type_name not in TYPE_NAMES:
            raise DragonSyntaxError(
                f"Linha {idx}: tipo inválido '{type_name}'. Tipos suportados: int, string, bool"
            )

        if name in seen_names:
            raise DragonSyntaxError(f"Linha {idx}: parâmetro duplicado: {name}")

        seen_names.add(name)
        parsed.append((name, type_name))

    return parsed


def _resolve_var_type(name: str, scopes: list[ScopeFrame]) -> str | None:
    for frame in reversed(scopes):
        if name in frame.vars:
            return frame.vars[name]
    return None


def _resolve_func(name: str, functions: dict[str, FuncInfo]) -> FuncInfo | None:
    return functions.get(name)


def _infer_expr_type(
    expr: str,
    *,
    idx: int,
    scopes: list[ScopeFrame],
    functions: dict[str, FuncInfo],
) -> str:
    expr = _normalize_expr(expr)
    try:
        node = ast.parse(expr, mode="eval").body
    except SyntaxError as exc:
        raise DragonSyntaxError(f"Linha {idx}: expressão inválida: {expr}") from exc

    def infer(n: ast.AST) -> str:
        if isinstance(n, ast.Constant):
            if isinstance(n.value, bool):
                return "bool"
            if isinstance(n.value, int):
                return "int"
            if isinstance(n.value, str):
                return "string"
            raise DragonTypeError(
                f"Linha {idx}: literal não suportado. Use apenas int, string ou bool"
            )

        if isinstance(n, ast.Name):
            var_type = _resolve_var_type(n.id, scopes)
            if var_type is None:
                raise DragonTypeError(f"Linha {idx}: variável '{n.id}' não declarada")
            return var_type

        if isinstance(n, ast.BinOp):
            left_t = infer(n.left)
            right_t = infer(n.right)

            if isinstance(n.op, ast.Add):
                if left_t == right_t == "int":
                    return "int"
                if left_t == right_t == "string":
                    return "string"
                raise DragonTypeError(
                    f"Linha {idx}: operador '+' aceita apenas int+int ou string+string"
                )

            if isinstance(n.op, (ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod)):
                if left_t == right_t == "int":
                    return "int"
                raise DragonTypeError(
                    f"Linha {idx}: operador aritmético requer operandos int"
                )

            if isinstance(n.op, ast.Div):
                if left_t == right_t == "int":
                    return "int"
                raise DragonTypeError(
                    f"Linha {idx}: operador '/' requer operandos int"
                )

            raise DragonTypeError(f"Linha {idx}: operador não suportado")

        if isinstance(n, ast.UnaryOp):
            operand_t = infer(n.operand)
            if isinstance(n.op, ast.Not):
                if operand_t != "bool":
                    raise DragonTypeError(f"Linha {idx}: operador 'not' requer bool")
                return "bool"
            if isinstance(n.op, ast.USub):
                if operand_t != "int":
                    raise DragonTypeError(f"Linha {idx}: operador '-' unário requer int")
                return "int"
            raise DragonTypeError(f"Linha {idx}: operador unário não suportado")

        if isinstance(n, ast.BoolOp):
            for value in n.values:
                if infer(value) != "bool":
                    raise DragonTypeError(
                        f"Linha {idx}: operadores lógicos requerem valores bool"
                    )
            return "bool"

        if isinstance(n, ast.Compare):
            left_t = infer(n.left)
            for comp in n.comparators:
                right_t = infer(comp)
                if left_t != right_t:
                    raise DragonTypeError(
                        f"Linha {idx}: comparação entre tipos incompatíveis ({left_t} e {right_t})"
                    )
                left_t = right_t
            return "bool"

        if isinstance(n, ast.Call):
            if not isinstance(n.func, ast.Name):
                raise DragonTypeError(f"Linha {idx}: chamada de função inválida")

            func_name = n.func.id
            if func_name == "input":
                if len(n.args) != 1 or n.keywords:
                    raise DragonTypeError(
                        f"Linha {idx}: input() aceita exatamente um argumento"
                    )
                if infer(n.args[0]) != "string":
                    raise DragonTypeError(
                        f"Linha {idx}: argumento de input() deve ser string"
                    )
                return "string"

            if func_name == "print":
                raise DragonTypeError(
                    f"Linha {idx}: print() só pode ser usado como instrução"
                )

            func_info = _resolve_func(func_name, functions)
            if func_info is None:
                raise DragonTypeError(f"Linha {idx}: função '{func_name}' não declarada")

            if len(n.args) != len(func_info.params) or n.keywords:
                raise DragonTypeError(
                    f"Linha {idx}: função '{func_name}' espera {len(func_info.params)} argumento(s)"
                )

            for arg_node, (param_name, param_type) in zip(n.args, func_info.params):
                arg_type = infer(arg_node)
                if arg_type != param_type:
                    raise DragonTypeError(
                        f"Linha {idx}: argumento '{param_name}' espera {param_type}, recebeu {arg_type}"
                    )

            return func_info.return_type or "unknown"

        raise DragonTypeError(f"Linha {idx}: expressão não suportada")

    return infer(node)


def transpile(source: str) -> CompileResult:
    lines = source.splitlines()
    out: list[str] = []
    indent = 0
    block_stack: list[str] = []
    scopes: list[ScopeFrame] = [ScopeFrame(kind="global", vars={})]
    functions: dict[str, FuncInfo] = {}
    func_name_stack: list[str] = []

    for idx, raw in enumerate(lines, start=1):
        line = _sanitize_line(raw)

        if not line or line.startswith("#"):
            continue

        if line == "end":
            if not block_stack:
                raise DragonSyntaxError(f"Linha {idx}: 'end' sem bloco aberto")
            ended = block_stack.pop()
            indent -= 1
            if ended in {"func", "if", "else", "while"}:
                scopes.pop()
            if ended == "func":
                func_name_stack.pop()
            continue

        func_match = FUNC_RE.match(line)
        if func_match:
            name = func_match.group(1)
            args = func_match.group(2).strip()
            params = _parse_func_args(args, idx)
            if name in functions:
                raise DragonSyntaxError(f"Linha {idx}: função '{name}' já declarada")
            functions[name] = FuncInfo(params=params)
            py_args = ", ".join(
                f"{param}: {_dragon_type_to_python(param_type)}"
                for param, param_type in params
            )
            out.append("    " * indent + f"def {name}({py_args}):")
            indent += 1
            block_stack.append("func")
            func_name_stack.append(name)
            func_scope = {param: param_type for param, param_type in params}
            scopes.append(ScopeFrame(kind="func", vars=func_scope))
            continue

        if_match = IF_RE.match(line)
        if if_match:
            condition = if_match.group(1).strip()
            condition_py = _normalize_expr(condition)
            cond_type = _infer_expr_type(
                condition,
                idx=idx,
                scopes=scopes,
                functions=functions,
            )
            if cond_type != "bool":
                raise DragonTypeError(f"Linha {idx}: condição de if deve ser bool")
            out.append("    " * indent + f"if {condition_py}:")
            indent += 1
            block_stack.append("if")
            scopes.append(ScopeFrame(kind="if", vars={}))
            continue

        if line == "else":
            if not block_stack or block_stack[-1] != "if":
                raise DragonSyntaxError(f"Linha {idx}: 'else' sem 'if' correspondente")
            scopes.pop()
            indent -= 1
            out.append("    " * indent + "else:")
            indent += 1
            block_stack[-1] = "else"
            scopes.append(ScopeFrame(kind="else", vars={}))
            continue

        while_match = WHILE_RE.match(line)
        if while_match:
            condition = while_match.group(1).strip()
            condition_py = _normalize_expr(condition)
            cond_type = _infer_expr_type(
                condition,
                idx=idx,
                scopes=scopes,
                functions=functions,
            )
            if cond_type != "bool":
                raise DragonTypeError(f"Linha {idx}: condição de while deve ser bool")
            out.append("    " * indent + f"while {condition_py}:")
            indent += 1
            block_stack.append("while")
            scopes.append(ScopeFrame(kind="while", vars={}))
            continue

        let_typed_match = LET_TYPED_RE.match(line)
        if let_typed_match:
            name = let_typed_match.group(1)
            declared_type = let_typed_match.group(2)
            expr = let_typed_match.group(3)
            expr_type = _infer_expr_type(expr, idx=idx, scopes=scopes, functions=functions)
            if expr_type != declared_type and expr_type != "unknown":
                raise DragonTypeError(
                    f"Linha {idx}: variável '{name}' é {declared_type}, mas recebeu {expr_type}"
                )
            scopes[-1].vars[name] = declared_type
            py_type = _dragon_type_to_python(declared_type)
            out.append("    " * indent + f"{name}: {py_type} = {_normalize_expr(expr)}")
            continue

        let_match = LET_RE.match(line)
        if let_match:
            name = let_match.group(1)
            expr = let_match.group(2)
            expr_type = _infer_expr_type(expr, idx=idx, scopes=scopes, functions=functions)
            scopes[-1].vars[name] = expr_type
            out.append("    " * indent + f"{name} = {_normalize_expr(expr)}")
            continue

        assign_match = ASSIGN_RE.match(line)
        if assign_match:
            name = assign_match.group(1)
            expr = assign_match.group(2)
            var_type = _resolve_var_type(name, scopes)
            if var_type is None:
                raise DragonTypeError(f"Linha {idx}: variável '{name}' não declarada")
            expr_type = _infer_expr_type(expr, idx=idx, scopes=scopes, functions=functions)
            if expr_type != var_type and expr_type != "unknown":
                raise DragonTypeError(
                    f"Linha {idx}: variável '{name}' é {var_type}, mas recebeu {expr_type}"
                )
            out.append("    " * indent + f"{name} = {_normalize_expr(expr)}")
            continue

        if line.startswith("return "):
            expr = line[len("return ") :].strip()
            expr_type = _infer_expr_type(expr, idx=idx, scopes=scopes, functions=functions)
            if not func_name_stack:
                raise DragonSyntaxError(f"Linha {idx}: 'return' fora de função")
            current_func_name = func_name_stack[-1]
            current_func = functions[current_func_name]
            if current_func.return_type is None:
                current_func.return_type = expr_type
            elif expr_type != current_func.return_type:
                raise DragonTypeError(
                    f"Linha {idx}: função '{current_func_name}' retorna tipos conflitantes "
                    f"({current_func.return_type} e {expr_type})"
                )
            out.append("    " * indent + f"return {_normalize_expr(expr)}")
            continue

        if line.startswith("print(") and line.endswith(")"):
            expr = line[len("print(") : -1].strip()
            if expr:
                _infer_expr_type(expr, idx=idx, scopes=scopes, functions=functions)
            out.append("    " * indent + f"print({_normalize_expr(expr)})")
            continue

        if line.startswith("input(") and line.endswith(")"):
            _infer_expr_type(line, idx=idx, scopes=scopes, functions=functions)
            out.append("    " * indent + _normalize_expr(line))
            continue

        # fallback para expressão/chamada simples
        _infer_expr_type(line, idx=idx, scopes=scopes, functions=functions)
        out.append("    " * indent + _normalize_expr(line))

    if indent != 0:
        raise DragonSyntaxError("Bloco não fechado com 'end'")

    python_code = "\n".join(out) + "\n"
    return CompileResult(python_code=python_code)


def read_file(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def write_file(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def cmd_transpile(args: argparse.Namespace) -> int:
    src = pathlib.Path(args.file)
    if src.suffix != ".dragon":
        print("Erro: arquivo deve ter extensão .dragon", file=sys.stderr)
        return 2

    source_code = read_file(src)
    try:
        result = transpile(source_code)
    except (DragonSyntaxError, DragonTypeError) as exc:
        print(f"Erro Dragon: {exc}", file=sys.stderr)
        return 1

    output = pathlib.Path(args.output) if args.output else src.with_suffix(".py")
    write_file(output, result.python_code)
    print(f"Transpilado com sucesso: {output}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    src = pathlib.Path(args.file)
    if src.suffix != ".dragon":
        print("Erro: arquivo deve ter extensão .dragon", file=sys.stderr)
        return 2

    source_code = read_file(src)
    try:
        result = transpile(source_code)
    except (DragonSyntaxError, DragonTypeError) as exc:
        print(f"Erro Dragon: {exc}", file=sys.stderr)
        return 1

    build_file = pathlib.Path("build") / (src.stem + ".py")
    write_file(build_file, result.python_code)

    proc = subprocess.run([sys.executable, str(build_file)], check=False)
    return proc.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dragon language compiler (MVP)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_transpile = sub.add_parser("transpile", help="Transpila arquivo .dragon para Python")
    p_transpile.add_argument("file", help="Arquivo fonte .dragon")
    p_transpile.add_argument("-o", "--output", help="Arquivo de saída .py")
    p_transpile.set_defaults(func=cmd_transpile)

    p_run = sub.add_parser("run", help="Executa programa .dragon")
    p_run.add_argument("file", help="Arquivo fonte .dragon")
    p_run.set_defaults(func=cmd_run)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
