#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sys
from dataclasses import dataclass


class DragonSyntaxError(Exception):
    pass


class DragonTypeError(Exception):
    pass


@dataclass
class CompileResult:
    python_code: str


@dataclass
class Instruction:
    op: str
    arg: object | None = None
    line: int = 0


@dataclass
class BytecodeFunction:
    name: str
    params: list[tuple[str, str]]
    return_type: str | None
    code: list[Instruction]


@dataclass
class BytecodeProgram:
    main: list[Instruction]
    functions: dict[str, BytecodeFunction]

BYTECODE_FORMAT_VERSION = 1


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


def _compile_expr_to_bytecode(expr: str, idx: int, out: list[Instruction]) -> None:
    expr = _normalize_expr(expr)
    try:
        node = ast.parse(expr, mode="eval").body
    except SyntaxError as exc:
        raise DragonSyntaxError(f"Linha {idx}: expressão inválida: {expr}") from exc

    def emit(op: str, arg: object | None = None) -> None:
        out.append(Instruction(op=op, arg=arg, line=idx))

    def visit(n: ast.AST) -> None:
        if isinstance(n, ast.Constant):
            emit("PUSH_CONST", n.value)
            return
        if isinstance(n, ast.Name):
            emit("LOAD_VAR", n.id)
            return
        if isinstance(n, ast.UnaryOp):
            visit(n.operand)
            if isinstance(n.op, ast.Not):
                emit("UNARY_NOT")
                return
            if isinstance(n.op, ast.USub):
                emit("UNARY_NEG")
                return
            raise DragonTypeError(f"Linha {idx}: operador unário não suportado")
        if isinstance(n, ast.BinOp):
            visit(n.left)
            visit(n.right)
            if isinstance(n.op, ast.Add):
                emit("BINARY_ADD")
                return
            if isinstance(n.op, ast.Sub):
                emit("BINARY_SUB")
                return
            if isinstance(n.op, ast.Mult):
                emit("BINARY_MUL")
                return
            if isinstance(n.op, ast.Div):
                emit("BINARY_DIV")
                return
            if isinstance(n.op, ast.FloorDiv):
                emit("BINARY_FLOORDIV")
                return
            if isinstance(n.op, ast.Mod):
                emit("BINARY_MOD")
                return
            raise DragonTypeError(f"Linha {idx}: operador não suportado")
        if isinstance(n, ast.BoolOp):
            if not n.values:
                raise DragonTypeError(f"Linha {idx}: expressão booleana inválida")
            visit(n.values[0])
            for nxt in n.values[1:]:
                visit(nxt)
                if isinstance(n.op, ast.And):
                    emit("BOOL_AND")
                elif isinstance(n.op, ast.Or):
                    emit("BOOL_OR")
                else:
                    raise DragonTypeError(f"Linha {idx}: operador lógico não suportado")
            return
        if isinstance(n, ast.Compare):
            if len(n.ops) != 1 or len(n.comparators) != 1:
                raise DragonTypeError(
                    f"Linha {idx}: comparação encadeada ainda não suportada na VM"
                )
            visit(n.left)
            visit(n.comparators[0])
            op_map = {
                ast.Eq: "==",
                ast.NotEq: "!=",
                ast.Lt: "<",
                ast.LtE: "<=",
                ast.Gt: ">",
                ast.GtE: ">=",
            }
            cmp_type = type(n.ops[0])
            if cmp_type not in op_map:
                raise DragonTypeError(f"Linha {idx}: operador de comparação não suportado")
            emit("COMPARE", op_map[cmp_type])
            return
        if isinstance(n, ast.Call):
            if not isinstance(n.func, ast.Name):
                raise DragonTypeError(f"Linha {idx}: chamada de função inválida")
            func_name = n.func.id
            for arg in n.args:
                visit(arg)
            if func_name == "input":
                emit("INPUT")
                return
            emit("CALL", (func_name, len(n.args)))
            return
        raise DragonTypeError(f"Linha {idx}: expressão não suportada")

    visit(node)


def compile_to_bytecode(source: str) -> BytecodeProgram:
    lines = source.splitlines()
    sanitized: list[tuple[int, str]] = []
    for idx, raw in enumerate(lines, start=1):
        line = _sanitize_line(raw)
        if not line or line.startswith("#"):
            continue
        sanitized.append((idx, line))

    functions: dict[str, FuncInfo] = {}
    bytecode_functions: dict[str, BytecodeFunction] = {}
    global_scope = ScopeFrame(kind="global", vars={})

    def compile_block(
        *,
        pos: int,
        out: list[Instruction],
        scopes: list[ScopeFrame],
        func_name_stack: list[str],
        stop_tokens: set[str],
    ) -> int:
        while pos < len(sanitized):
            idx, line = sanitized[pos]
            if line in stop_tokens:
                return pos

            func_match = FUNC_RE.match(line)
            if func_match:
                name = func_match.group(1)
                args = func_match.group(2).strip()
                params = _parse_func_args(args, idx)
                if name in functions:
                    raise DragonSyntaxError(f"Linha {idx}: função '{name}' já declarada")
                functions[name] = FuncInfo(params=params)
                pos += 1
                body_code: list[Instruction] = []
                func_scope = ScopeFrame(kind="func", vars={param: typ for param, typ in params})
                inner_pos = compile_block(
                    pos=pos,
                    out=body_code,
                    scopes=scopes + [func_scope],
                    func_name_stack=func_name_stack + [name],
                    stop_tokens={"end"},
                )
                if inner_pos >= len(sanitized) or sanitized[inner_pos][1] != "end":
                    raise DragonSyntaxError(
                        f"Linha {idx}: função '{name}' não fechada com 'end'"
                    )
                body_code.append(Instruction(op="PUSH_CONST", arg=None, line=idx))
                body_code.append(Instruction(op="RETURN", line=idx))
                bytecode_functions[name] = BytecodeFunction(
                    name=name,
                    params=params,
                    return_type=functions[name].return_type,
                    code=body_code,
                )
                pos = inner_pos + 1
                continue

            if_match = IF_RE.match(line)
            if if_match:
                condition = if_match.group(1).strip()
                cond_type = _infer_expr_type(condition, idx=idx, scopes=scopes, functions=functions)
                if cond_type != "bool":
                    raise DragonTypeError(f"Linha {idx}: condição de if deve ser bool")
                _compile_expr_to_bytecode(condition, idx, out)
                jump_if_false_idx = len(out)
                out.append(Instruction(op="JUMP_IF_FALSE", arg=None, line=idx))

                pos = compile_block(
                    pos=pos + 1,
                    out=out,
                    scopes=scopes + [ScopeFrame(kind="if", vars={})],
                    func_name_stack=func_name_stack,
                    stop_tokens={"else", "end"},
                )
                if pos >= len(sanitized):
                    raise DragonSyntaxError(f"Linha {idx}: if sem 'end'")

                token = sanitized[pos][1]
                if token == "else":
                    jump_end_idx = len(out)
                    out.append(Instruction(op="JUMP", arg=None, line=idx))
                    out[jump_if_false_idx].arg = len(out)
                    pos = compile_block(
                        pos=pos + 1,
                        out=out,
                        scopes=scopes + [ScopeFrame(kind="else", vars={})],
                        func_name_stack=func_name_stack,
                        stop_tokens={"end"},
                    )
                    if pos >= len(sanitized) or sanitized[pos][1] != "end":
                        raise DragonSyntaxError(f"Linha {idx}: else sem 'end'")
                    out[jump_end_idx].arg = len(out)
                    pos += 1
                else:
                    out[jump_if_false_idx].arg = len(out)
                    pos += 1
                continue

            while_match = WHILE_RE.match(line)
            if while_match:
                condition = while_match.group(1).strip()
                cond_type = _infer_expr_type(condition, idx=idx, scopes=scopes, functions=functions)
                if cond_type != "bool":
                    raise DragonTypeError(f"Linha {idx}: condição de while deve ser bool")
                loop_start = len(out)
                _compile_expr_to_bytecode(condition, idx, out)
                jump_out_idx = len(out)
                out.append(Instruction(op="JUMP_IF_FALSE", arg=None, line=idx))

                pos = compile_block(
                    pos=pos + 1,
                    out=out,
                    scopes=scopes + [ScopeFrame(kind="while", vars={})],
                    func_name_stack=func_name_stack,
                    stop_tokens={"end"},
                )
                if pos >= len(sanitized) or sanitized[pos][1] != "end":
                    raise DragonSyntaxError(f"Linha {idx}: while sem 'end'")
                out.append(Instruction(op="JUMP", arg=loop_start, line=idx))
                out[jump_out_idx].arg = len(out)
                pos += 1
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
                _compile_expr_to_bytecode(expr, idx, out)
                out.append(Instruction(op="STORE_VAR", arg=name, line=idx))
                pos += 1
                continue

            let_match = LET_RE.match(line)
            if let_match:
                name = let_match.group(1)
                expr = let_match.group(2)
                expr_type = _infer_expr_type(expr, idx=idx, scopes=scopes, functions=functions)
                scopes[-1].vars[name] = expr_type
                _compile_expr_to_bytecode(expr, idx, out)
                out.append(Instruction(op="STORE_VAR", arg=name, line=idx))
                pos += 1
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
                _compile_expr_to_bytecode(expr, idx, out)
                out.append(Instruction(op="STORE_VAR", arg=name, line=idx))
                pos += 1
                continue

            if line.startswith("return "):
                expr = line[len("return ") :].strip()
                if not func_name_stack:
                    raise DragonSyntaxError(f"Linha {idx}: 'return' fora de função")
                expr_type = _infer_expr_type(expr, idx=idx, scopes=scopes, functions=functions)
                current_func_name = func_name_stack[-1]
                current_func = functions[current_func_name]
                if current_func.return_type is None:
                    current_func.return_type = expr_type
                elif expr_type != current_func.return_type:
                    raise DragonTypeError(
                        f"Linha {idx}: função '{current_func_name}' retorna tipos conflitantes "
                        f"({current_func.return_type} e {expr_type})"
                    )
                _compile_expr_to_bytecode(expr, idx, out)
                out.append(Instruction(op="RETURN", line=idx))
                pos += 1
                continue

            if line.startswith("print(") and line.endswith(")"):
                expr = line[len("print(") : -1].strip()
                if expr:
                    _infer_expr_type(expr, idx=idx, scopes=scopes, functions=functions)
                    _compile_expr_to_bytecode(expr, idx, out)
                else:
                    out.append(Instruction(op="PUSH_CONST", arg="", line=idx))
                out.append(Instruction(op="PRINT", line=idx))
                pos += 1
                continue

            _infer_expr_type(line, idx=idx, scopes=scopes, functions=functions)
            _compile_expr_to_bytecode(line, idx, out)
            out.append(Instruction(op="POP", line=idx))
            pos += 1

        return pos

    main_code: list[Instruction] = []
    end_pos = compile_block(
        pos=0,
        out=main_code,
        scopes=[global_scope],
        func_name_stack=[],
        stop_tokens=set(),
    )
    if end_pos != len(sanitized):
        idx, _ = sanitized[end_pos]
        raise DragonSyntaxError(f"Linha {idx}: bloco não fechado com 'end'")
    main_code.append(Instruction(op="HALT", line=0))
    return BytecodeProgram(main=main_code, functions=bytecode_functions)


@dataclass
class _Frame:
    code: list[Instruction]
    locals: dict[str, object]
    name: str
    ip: int = 0


def run_bytecode(program: BytecodeProgram) -> None:
    stack: list[object] = []
    globals_: dict[str, object] = {}
    frames: list[_Frame] = [_Frame(code=program.main, locals=globals_, name="<main>")]

    def pop() -> object:
        if not stack:
            raise RuntimeError("Stack underflow na VM Dragon")
        return stack.pop()

    while frames:
        frame = frames[-1]
        if frame.ip >= len(frame.code):
            frames.pop()
            if frames:
                stack.append(None)
            continue

        inst = frame.code[frame.ip]
        frame.ip += 1

        if inst.op == "PUSH_CONST":
            stack.append(inst.arg)
        elif inst.op == "LOAD_VAR":
            name = str(inst.arg)
            if name in frame.locals:
                stack.append(frame.locals[name])
            elif name in globals_:
                stack.append(globals_[name])
            else:
                raise DragonTypeError(f"Linha {inst.line}: variável '{name}' não declarada")
        elif inst.op == "STORE_VAR":
            frame.locals[str(inst.arg)] = pop()
        elif inst.op == "POP":
            pop()
        elif inst.op == "PRINT":
            print(pop())
        elif inst.op == "INPUT":
            prompt = pop()
            stack.append(input(str(prompt)))
        elif inst.op == "CALL":
            func_name, argc = inst.arg
            args = [pop() for _ in range(argc)][::-1]
            if func_name not in program.functions:
                raise DragonTypeError(
                    f"Linha {inst.line}: função '{func_name}' não declarada"
                )
            fn = program.functions[func_name]
            call_locals = {name: value for (name, _), value in zip(fn.params, args)}
            frames.append(_Frame(code=fn.code, locals=call_locals, name=func_name))
        elif inst.op == "RETURN":
            result = pop()
            frames.pop()
            if frames:
                stack.append(result)
        elif inst.op == "JUMP":
            frame.ip = int(inst.arg)
        elif inst.op == "JUMP_IF_FALSE":
            cond = pop()
            if not cond:
                frame.ip = int(inst.arg)
        elif inst.op == "UNARY_NOT":
            stack.append(not pop())
        elif inst.op == "UNARY_NEG":
            stack.append(-int(pop()))
        elif inst.op == "BINARY_ADD":
            b = pop()
            a = pop()
            stack.append(a + b)
        elif inst.op == "BINARY_SUB":
            b = pop()
            a = pop()
            stack.append(int(a) - int(b))
        elif inst.op == "BINARY_MUL":
            b = pop()
            a = pop()
            stack.append(int(a) * int(b))
        elif inst.op in {"BINARY_DIV", "BINARY_FLOORDIV"}:
            b = pop()
            a = pop()
            stack.append(int(a) // int(b))
        elif inst.op == "BINARY_MOD":
            b = pop()
            a = pop()
            stack.append(int(a) % int(b))
        elif inst.op == "BOOL_AND":
            b = bool(pop())
            a = bool(pop())
            stack.append(a and b)
        elif inst.op == "BOOL_OR":
            b = bool(pop())
            a = bool(pop())
            stack.append(a or b)
        elif inst.op == "COMPARE":
            b = pop()
            a = pop()
            if inst.arg == "==":
                stack.append(a == b)
            elif inst.arg == "!=":
                stack.append(a != b)
            elif inst.arg == "<":
                stack.append(a < b)
            elif inst.arg == "<=":
                stack.append(a <= b)
            elif inst.arg == ">":
                stack.append(a > b)
            elif inst.arg == ">=":
                stack.append(a >= b)
            else:
                raise RuntimeError(f"Comparador inválido: {inst.arg}")
        elif inst.op == "HALT":
            break
        else:
            raise RuntimeError(f"Opcode inválido: {inst.op}")


def _instruction_to_dict(inst: Instruction) -> dict[str, object]:
    return {"op": inst.op, "arg": inst.arg, "line": inst.line}


def _instruction_from_dict(raw: dict[str, object]) -> Instruction:
    op = raw.get("op")
    line = raw.get("line")
    if not isinstance(op, str) or not isinstance(line, int):
        raise DragonSyntaxError("Bytecode inválido: instrução malformada")

    arg = raw.get("arg")
    if op == "CALL" and arg is not None:
        if not (isinstance(arg, list) and len(arg) == 2):
            raise DragonSyntaxError("Bytecode inválido: argumento de CALL malformado")
        arg = (arg[0], arg[1])
    return Instruction(op=op, arg=arg, line=line)


def serialize_bytecode(program: BytecodeProgram) -> str:
    payload = {
        "format": "dragon-bytecode",
        "version": BYTECODE_FORMAT_VERSION,
        "main": [_instruction_to_dict(inst) for inst in program.main],
        "functions": {
            name: {
                "name": fn.name,
                "params": [[param_name, param_type] for param_name, param_type in fn.params],
                "return_type": fn.return_type,
                "code": [_instruction_to_dict(inst) for inst in fn.code],
            }
            for name, fn in program.functions.items()
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def deserialize_bytecode(content: str) -> BytecodeProgram:
    try:
        raw = json.loads(content)
    except json.JSONDecodeError as exc:
        raise DragonSyntaxError("Bytecode inválido: arquivo .dbc não é JSON válido") from exc

    if not isinstance(raw, dict):
        raise DragonSyntaxError("Bytecode inválido: raiz do arquivo deve ser objeto JSON")
    if raw.get("format") != "dragon-bytecode":
        raise DragonSyntaxError("Bytecode inválido: cabeçalho de formato desconhecido")
    if raw.get("version") != BYTECODE_FORMAT_VERSION:
        raise DragonSyntaxError("Bytecode inválido: versão de formato não suportada")

    main_raw = raw.get("main")
    funcs_raw = raw.get("functions")
    if not isinstance(main_raw, list) or not isinstance(funcs_raw, dict):
        raise DragonSyntaxError("Bytecode inválido: seções 'main' ou 'functions' ausentes")

    main = [_instruction_from_dict(inst) for inst in main_raw]
    functions: dict[str, BytecodeFunction] = {}
    for name, fn_raw in funcs_raw.items():
        if not isinstance(name, str) or not isinstance(fn_raw, dict):
            raise DragonSyntaxError("Bytecode inválido: função malformada")
        params_raw = fn_raw.get("params")
        code_raw = fn_raw.get("code")
        return_type = fn_raw.get("return_type")
        if not isinstance(params_raw, list) or not isinstance(code_raw, list):
            raise DragonSyntaxError("Bytecode inválido: função com params/code inválidos")
        params: list[tuple[str, str]] = []
        for param in params_raw:
            if (
                not isinstance(param, list)
                or len(param) != 2
                or not isinstance(param[0], str)
                or not isinstance(param[1], str)
            ):
                raise DragonSyntaxError("Bytecode inválido: parâmetro de função malformado")
            params.append((param[0], param[1]))
        if return_type is not None and not isinstance(return_type, str):
            raise DragonSyntaxError("Bytecode inválido: return_type malformado")
        code = [_instruction_from_dict(inst) for inst in code_raw]
        functions[name] = BytecodeFunction(
            name=name,
            params=params,
            return_type=return_type,
            code=code,
        )

    return BytecodeProgram(main=main, functions=functions)


def write_bytecode_file(path: pathlib.Path, program: BytecodeProgram) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_bytecode(program), encoding="utf-8")


def read_bytecode_file(path: pathlib.Path) -> BytecodeProgram:
    return deserialize_bytecode(path.read_text(encoding="utf-8"))


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
        program = compile_to_bytecode(source_code)
    except (DragonSyntaxError, DragonTypeError) as exc:
        print(f"Erro Dragon: {exc}", file=sys.stderr)
        return 1

    run_bytecode(program)
    return 0


def cmd_compile(args: argparse.Namespace) -> int:
    src = pathlib.Path(args.file)
    if src.suffix != ".dragon":
        print("Erro: arquivo deve ter extensão .dragon", file=sys.stderr)
        return 2

    source_code = read_file(src)
    try:
        program = compile_to_bytecode(source_code)
    except (DragonSyntaxError, DragonTypeError) as exc:
        print(f"Erro Dragon: {exc}", file=sys.stderr)
        return 1

    output = pathlib.Path(args.output) if args.output else src.with_suffix(".dbc")
    write_bytecode_file(output, program)
    print(f"Bytecode compilado com sucesso: {output}")
    return 0


def cmd_runbc(args: argparse.Namespace) -> int:
    src = pathlib.Path(args.file)
    if src.suffix != ".dbc":
        print("Erro: arquivo deve ter extensão .dbc", file=sys.stderr)
        return 2

    try:
        program = read_bytecode_file(src)
    except (OSError, DragonSyntaxError) as exc:
        print(f"Erro Dragon: {exc}", file=sys.stderr)
        return 1

    run_bytecode(program)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dragon language compiler/VM (MVP)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_transpile = sub.add_parser("transpile", help="Transpila arquivo .dragon para Python")
    p_transpile.add_argument("file", help="Arquivo fonte .dragon")
    p_transpile.add_argument("-o", "--output", help="Arquivo de saída .py")
    p_transpile.set_defaults(func=cmd_transpile)

    p_run = sub.add_parser("run", help="Executa programa .dragon")
    p_run.add_argument("file", help="Arquivo fonte .dragon")
    p_run.set_defaults(func=cmd_run)

    p_compile = sub.add_parser("compile", help="Compila .dragon para bytecode .dbc")
    p_compile.add_argument("file", help="Arquivo fonte .dragon")
    p_compile.add_argument("-o", "--output", help="Arquivo de saída .dbc")
    p_compile.set_defaults(func=cmd_compile)

    p_runbc = sub.add_parser("runbc", help="Executa bytecode .dbc")
    p_runbc.add_argument("file", help="Arquivo bytecode .dbc")
    p_runbc.set_defaults(func=cmd_runbc)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
