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
IMPORT_RE = re.compile(r"^import\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*$")


@dataclass
class ScopeFrame:
    kind: str
    vars: dict[str, str]


@dataclass
class FuncInfo:
    params: list[tuple[str, str]]
    return_type: str | None = None


@dataclass
class NativeFunction:
    info: FuncInfo
    impl: callable


STD_NATIVE_FUNCTIONS: dict[str, NativeFunction] = {
    "length": NativeFunction(
        info=FuncInfo(params=[("text", "string")], return_type="int"),
        impl=lambda text: len(str(text)),
    ),
    "uppercase": NativeFunction(
        info=FuncInfo(params=[("text", "string")], return_type="string"),
        impl=lambda text: str(text).upper(),
    ),
    "lowercase": NativeFunction(
        info=FuncInfo(params=[("text", "string")], return_type="string"),
        impl=lambda text: str(text).lower(),
    ),
    "to_int": NativeFunction(
        info=FuncInfo(params=[("text", "string")], return_type="int"),
        impl=lambda text: int(str(text)),
    ),
    "to_string": NativeFunction(
        info=FuncInfo(params=[("value", "int")], return_type="string"),
        impl=lambda value: str(int(value)),
    ),
}


STD_PYTHON_STUB = """def length(text: str):
    return len(text)

def uppercase(text: str):
    return text.upper()

def lowercase(text: str):
    return text.lower()

def to_int(text: str):
    return int(text)

def to_string(value: int):
    return str(value)
"""


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
            raise DragonSyntaxError(f"Line {idx}: empty argument in function declaration")

        name_and_type = piece.split(":", maxsplit=1)
        if len(name_and_type) != 2:
            raise DragonSyntaxError(
                f"Line {idx}: parameters must include types (example: a: int)"
            )

        name = name_and_type[0].strip()
        type_name = name_and_type[1].strip()

        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
            raise DragonSyntaxError(f"Line {idx}: invalid parameter name: {name}")

        if type_name not in TYPE_NAMES:
            raise DragonSyntaxError(
                f"Line {idx}: invalid type '{type_name}'. Supported types: int, string, bool"
            )

        if name in seen_names:
            raise DragonSyntaxError(f"Line {idx}: duplicate parameter: {name}")

        seen_names.add(name)
        parsed.append((name, type_name))

    return parsed




def _qualify_function_name(name: str, namespace: str | None) -> str:
    return f"{namespace}.{name}" if namespace else name


def _dragon_func_to_python_name(name: str) -> str:
    return name.replace(".", "__")


def _extract_dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _extract_dotted_name(node.value)
        if base is None:
            return None
        return f"{base}.{node.attr}"
    return None


def _resolve_func_name(name: str, functions: dict[str, FuncInfo], namespace: str | None) -> str | None:
    if name in functions:
        return name
    if "." not in name and namespace:
        qualified = f"{namespace}.{name}"
        if qualified in functions:
            return qualified
    if "." not in name:
        suffix = f".{name}"
        matches = [fn_name for fn_name in functions if fn_name.endswith(suffix)]
        if len(matches) == 1:
            return matches[0]
    return None


def _expr_to_python(
    expr: str,
    *,
    idx: int,
    functions: dict[str, FuncInfo],
    namespace: str | None,
) -> str:
    expr = _normalize_expr(expr)
    rewritten_any = False
    try:
        node = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise DragonSyntaxError(f"Line {idx}: invalid expression: {expr}") from exc

    class _CallNameRewriter(ast.NodeTransformer):
        def visit_Call(self, call: ast.Call) -> ast.AST:
            nonlocal rewritten_any
            self.generic_visit(call)
            raw_name = _extract_dotted_name(call.func)
            if raw_name in {None, "input"}:
                return call
            resolved = _resolve_func_name(raw_name, functions, namespace)
            if resolved is None:
                return call
            if resolved == raw_name and "." not in raw_name:
                return call
            call.func = ast.Name(id=_dragon_func_to_python_name(resolved), ctx=ast.Load())
            rewritten_any = True
            return call

    rewritten = _CallNameRewriter().visit(node)
    ast.fix_missing_locations(rewritten)
    if not rewritten_any:
        return expr
    return ast.unparse(rewritten.body)

def _resolve_var_type(name: str, scopes: list[ScopeFrame]) -> str | None:
    for frame in reversed(scopes):
        if name in frame.vars:
            return frame.vars[name]
    return None


def _resolve_func(name: str, functions: dict[str, FuncInfo], namespace: str | None) -> FuncInfo | None:
    resolved = _resolve_func_name(name, functions, namespace)
    if resolved is None:
        return None
    return functions.get(resolved)


def _collect_function_signatures(source: str, *, namespace: str | None = None) -> dict[str, FuncInfo]:
    signatures: dict[str, FuncInfo] = {}
    for idx, raw in enumerate(source.splitlines(), start=1):
        line = _sanitize_line(raw)
        if not line or line.startswith("#"):
            continue
        func_match = FUNC_RE.match(line)
        if not func_match:
            continue
        name = func_match.group(1)
        params = _parse_func_args(func_match.group(2).strip(), idx)
        signatures[_qualify_function_name(name, namespace)] = FuncInfo(params=params)
    return signatures


def _infer_expr_type(
    expr: str,
    *,
    idx: int,
    scopes: list[ScopeFrame],
    functions: dict[str, FuncInfo],
    namespace: str | None = None,
) -> str:
    expr = _normalize_expr(expr)
    try:
        node = ast.parse(expr, mode="eval").body
    except SyntaxError as exc:
        raise DragonSyntaxError(f"Line {idx}: invalid expression: {expr}") from exc

    def infer(n: ast.AST) -> str:
        if isinstance(n, ast.Constant):
            if isinstance(n.value, bool):
                return "bool"
            if isinstance(n.value, int):
                return "int"
            if isinstance(n.value, str):
                return "string"
            raise DragonTypeError(
                f"Line {idx}: unsupported literal. Use only int, string, or bool"
            )

        if isinstance(n, ast.Name):
            var_type = _resolve_var_type(n.id, scopes)
            if var_type is None:
                raise DragonTypeError(f"Line {idx}: variable '{n.id}' not declared")
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
                    f"Line {idx}: '+' operator only supports int+int or string+string"
                )

            if isinstance(n.op, (ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod)):
                if left_t == right_t == "int":
                    return "int"
                raise DragonTypeError(
                    f"Line {idx}: arithmetic operator requires int operands"
                )

            if isinstance(n.op, ast.Div):
                if left_t == right_t == "int":
                    return "int"
                raise DragonTypeError(
                    f"Line {idx}: '/' operator requires int operands"
                )

            raise DragonTypeError(f"Line {idx}: unsupported operator")

        if isinstance(n, ast.UnaryOp):
            operand_t = infer(n.operand)
            if isinstance(n.op, ast.Not):
                if operand_t != "bool":
                    raise DragonTypeError(f"Line {idx}: 'not' operator requires bool")
                return "bool"
            if isinstance(n.op, ast.USub):
                if operand_t != "int":
                    raise DragonTypeError(f"Line {idx}: unary '-' operator requires int")
                return "int"
            raise DragonTypeError(f"Line {idx}: unsupported unary operator")

        if isinstance(n, ast.BoolOp):
            for value in n.values:
                if infer(value) != "bool":
                    raise DragonTypeError(
                        f"Line {idx}: logical operators require bool values"
                    )
            return "bool"

        if isinstance(n, ast.Compare):
            left_t = infer(n.left)
            for comp in n.comparators:
                right_t = infer(comp)
                if left_t != right_t:
                    raise DragonTypeError(
                        f"Line {idx}: comparison between incompatible types ({left_t} and {right_t})"
                    )
                left_t = right_t
            return "bool"

        if isinstance(n, ast.Call):
            func_name = _extract_dotted_name(n.func)
            if func_name is None:
                raise DragonTypeError(f"Line {idx}: invalid function call")
            if func_name == "input":
                if len(n.args) != 1 or n.keywords:
                    raise DragonTypeError(
                        f"Line {idx}: input() accepts exactly one argument"
                    )
                if infer(n.args[0]) != "string":
                    raise DragonTypeError(
                        f"Line {idx}: input() argument must be string"
                    )
                return "string"

            if func_name == "print":
                raise DragonTypeError(
                    f"Line {idx}: print() can only be used as a statement"
                )

            func_info = _resolve_func(func_name, functions, namespace)
            if func_info is None:
                raise DragonTypeError(f"Line {idx}: function '{func_name}' not declared")

            if len(n.args) != len(func_info.params) or n.keywords:
                raise DragonTypeError(
                    f"Line {idx}: function '{func_name}' expects {len(func_info.params)} argument(s)"
                )

            for arg_node, (param_name, param_type) in zip(n.args, func_info.params):
                arg_type = infer(arg_node)
                if arg_type != param_type:
                    raise DragonTypeError(
                        f"Line {idx}: argument '{param_name}' expects {param_type}, got {arg_type}"
                    )

            return func_info.return_type or "unknown"

        raise DragonTypeError(f"Line {idx}: unsupported expression")

    return infer(node)


def transpile(
    source: str,
    *,
    module_loader: callable | None = None,
    loaded_modules: set[str] | None = None,
    namespace: str | None = None,
) -> CompileResult:
    lines = source.splitlines()
    out: list[str] = []
    indent = 0
    block_stack: list[str] = []
    scopes: list[ScopeFrame] = [ScopeFrame(kind="global", vars={})]
    functions: dict[str, FuncInfo] = {}
    func_name_stack: list[str] = []
    loaded_modules = loaded_modules if loaded_modules is not None else set()
    std_loaded = False

    for idx, raw in enumerate(lines, start=1):
        line = _sanitize_line(raw)

        if not line or line.startswith("#"):
            continue

        if line == "end":
            if not block_stack:
                raise DragonSyntaxError(f"Line {idx}: 'end' without an open block")
            ended = block_stack.pop()
            indent -= 1
            if ended in {"func", "if", "else", "while"}:
                scopes.pop()
            if ended == "func":
                func_name_stack.pop()
            continue

        import_match = IMPORT_RE.match(line)
        if import_match:
            if indent != 0:
                raise DragonSyntaxError(f"Line {idx}: import is only allowed at global scope")
            module_name = import_match.group(1)
            if module_name == "std":
                if not std_loaded:
                    out.append(STD_PYTHON_STUB.rstrip())
                    std_loaded = True
                for native_name, native_fn in STD_NATIVE_FUNCTIONS.items():
                    functions[native_name] = native_fn.info
                continue

            if module_name in loaded_modules:
                continue
            if module_loader is None:
                raise DragonSyntaxError(
                    f"Line {idx}: module '{module_name}' not found (no module loader)"
                )
            loaded_modules.add(module_name)
            module_source = module_loader(module_name)
            module_result = transpile(
                module_source,
                module_loader=module_loader,
                loaded_modules=loaded_modules,
                namespace=module_name,
            )
            out.append(module_result.python_code.rstrip())
            functions.update(_collect_function_signatures(module_source, namespace=module_name))
            continue

        func_match = FUNC_RE.match(line)
        if func_match:
            name = func_match.group(1)
            declared_name = _qualify_function_name(name, namespace)
            args = func_match.group(2).strip()
            params = _parse_func_args(args, idx)
            if declared_name in functions:
                raise DragonSyntaxError(f"Line {idx}: function '{name}' already declared")
            functions[declared_name] = FuncInfo(params=params)
            py_args = ", ".join(
                f"{param}: {_dragon_type_to_python(param_type)}"
                for param, param_type in params
            )
            out.append("    " * indent + f"def {_dragon_func_to_python_name(declared_name)}({py_args}):")
            indent += 1
            block_stack.append("func")
            func_name_stack.append(declared_name)
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
                namespace=namespace,
            )
            if cond_type != "bool":
                raise DragonTypeError(f"Line {idx}: if condition must be bool")
            out.append("    " * indent + f"if {condition_py}:")
            indent += 1
            block_stack.append("if")
            scopes.append(ScopeFrame(kind="if", vars={}))
            continue

        if line == "else":
            if not block_stack or block_stack[-1] != "if":
                raise DragonSyntaxError(f"Line {idx}: 'else' without matching 'if'")
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
                namespace=namespace,
            )
            if cond_type != "bool":
                raise DragonTypeError(f"Line {idx}: while condition must be bool")
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
            expr_type = _infer_expr_type(expr, idx=idx, scopes=scopes, functions=functions, namespace=namespace)
            if expr_type != declared_type and expr_type != "unknown":
                raise DragonTypeError(
                    f"Line {idx}: variable '{name}' is {declared_type}, but got {expr_type}"
                )
            scopes[-1].vars[name] = declared_type
            py_type = _dragon_type_to_python(declared_type)
            out.append("    " * indent + f"{name}: {py_type} = {_expr_to_python(expr, idx=idx, functions=functions, namespace=namespace)}")
            continue

        let_match = LET_RE.match(line)
        if let_match:
            name = let_match.group(1)
            expr = let_match.group(2)
            expr_type = _infer_expr_type(expr, idx=idx, scopes=scopes, functions=functions, namespace=namespace)
            scopes[-1].vars[name] = expr_type
            out.append("    " * indent + f"{name} = {_expr_to_python(expr, idx=idx, functions=functions, namespace=namespace)}")
            continue

        assign_match = ASSIGN_RE.match(line)
        if assign_match:
            name = assign_match.group(1)
            expr = assign_match.group(2)
            var_type = _resolve_var_type(name, scopes)
            if var_type is None:
                raise DragonTypeError(f"Line {idx}: variable '{name}' not declared")
            expr_type = _infer_expr_type(expr, idx=idx, scopes=scopes, functions=functions, namespace=namespace)
            if expr_type != var_type and expr_type != "unknown":
                raise DragonTypeError(
                    f"Line {idx}: variable '{name}' is {var_type}, but got {expr_type}"
                )
            out.append("    " * indent + f"{name} = {_expr_to_python(expr, idx=idx, functions=functions, namespace=namespace)}")
            continue

        if line.startswith("return "):
            expr = line[len("return ") :].strip()
            expr_type = _infer_expr_type(expr, idx=idx, scopes=scopes, functions=functions, namespace=namespace)
            if not func_name_stack:
                raise DragonSyntaxError(f"Line {idx}: 'return' outside function")
            current_func_name = func_name_stack[-1]
            current_func = functions[current_func_name]
            if current_func.return_type is None:
                current_func.return_type = expr_type
            elif expr_type != current_func.return_type:
                raise DragonTypeError(
                    f"Line {idx}: function '{current_func_name}' returns conflicting types "
                    f"({current_func.return_type} and {expr_type})"
                )
            out.append("    " * indent + f"return {_expr_to_python(expr, idx=idx, functions=functions, namespace=namespace)}")
            continue

        if line.startswith("print(") and line.endswith(")"):
            expr = line[len("print(") : -1].strip()
            if expr:
                _infer_expr_type(expr, idx=idx, scopes=scopes, functions=functions, namespace=namespace)
            out.append("    " * indent + f"print({_expr_to_python(expr, idx=idx, functions=functions, namespace=namespace)})")
            continue

        if line.startswith("input(") and line.endswith(")"):
            _infer_expr_type(line, idx=idx, scopes=scopes, functions=functions, namespace=namespace)
            out.append("    " * indent + _expr_to_python(line, idx=idx, functions=functions, namespace=namespace))
            continue

        # fallback for simple expression/function call
        _infer_expr_type(line, idx=idx, scopes=scopes, functions=functions, namespace=namespace)
        out.append("    " * indent + _expr_to_python(line, idx=idx, functions=functions, namespace=namespace))

    if indent != 0:
        raise DragonSyntaxError("Block not closed with 'end'")

    python_code = "\n".join(out) + "\n"
    return CompileResult(python_code=python_code)


def _compile_expr_to_bytecode(
    expr: str,
    idx: int,
    out: list[Instruction],
    *,
    functions: dict[str, FuncInfo],
    namespace: str | None,
) -> None:
    expr = _normalize_expr(expr)
    try:
        node = ast.parse(expr, mode="eval").body
    except SyntaxError as exc:
        raise DragonSyntaxError(f"Line {idx}: invalid expression: {expr}") from exc

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
            raise DragonTypeError(f"Line {idx}: unsupported unary operator")
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
            raise DragonTypeError(f"Line {idx}: unsupported operator")
        if isinstance(n, ast.BoolOp):
            if not n.values:
                raise DragonTypeError(f"Line {idx}: invalid boolean expression")
            visit(n.values[0])
            for nxt in n.values[1:]:
                visit(nxt)
                if isinstance(n.op, ast.And):
                    emit("BOOL_AND")
                elif isinstance(n.op, ast.Or):
                    emit("BOOL_OR")
                else:
                    raise DragonTypeError(f"Line {idx}: unsupported logical operator")
            return
        if isinstance(n, ast.Compare):
            if len(n.ops) != 1 or len(n.comparators) != 1:
                raise DragonTypeError(
                    f"Line {idx}: chained comparison is not yet supported in the VM"
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
                raise DragonTypeError(f"Line {idx}: unsupported comparison operator")
            emit("COMPARE", op_map[cmp_type])
            return
        if isinstance(n, ast.Call):
            func_name = _extract_dotted_name(n.func)
            if func_name is None:
                raise DragonTypeError(f"Line {idx}: invalid function call")
            for arg in n.args:
                visit(arg)
            if func_name == "input":
                emit("INPUT")
                return
            resolved = _resolve_func_name(func_name, functions, namespace)
            emit("CALL", ((resolved or func_name), len(n.args)))
            return
        raise DragonTypeError(f"Line {idx}: unsupported expression")

    visit(node)


def compile_to_bytecode(
    source: str,
    *,
    module_loader: callable | None = None,
    loaded_modules: set[str] | None = None,
    namespace: str | None = None,
) -> BytecodeProgram:
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
    loaded_modules = loaded_modules if loaded_modules is not None else set()

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

            import_match = IMPORT_RE.match(line)
            if import_match:
                if scopes[-1].kind != "global":
                    raise DragonSyntaxError(
                        f"Line {idx}: import is only allowed at global scope"
                    )
                module_name = import_match.group(1)
                if module_name == "std":
                    for native_name, native_fn in STD_NATIVE_FUNCTIONS.items():
                        functions[native_name] = native_fn.info
                    pos += 1
                    continue
                if module_name in loaded_modules:
                    pos += 1
                    continue
                if module_loader is None:
                    raise DragonSyntaxError(
                        f"Line {idx}: module '{module_name}' not found (no module loader)"
                    )
                loaded_modules.add(module_name)
                module_source = module_loader(module_name)
                module_program = compile_to_bytecode(
                    module_source,
                    module_loader=module_loader,
                    loaded_modules=loaded_modules,
                    namespace=module_name,
                )
                for fn_name, fn in module_program.functions.items():
                    bytecode_functions[fn_name] = fn
                    functions[fn_name] = FuncInfo(params=fn.params, return_type=fn.return_type)
                pos += 1
                continue

            func_match = FUNC_RE.match(line)
            if func_match:
                name = func_match.group(1)
                declared_name = _qualify_function_name(name, namespace)
                args = func_match.group(2).strip()
                params = _parse_func_args(args, idx)
                if declared_name in functions:
                    raise DragonSyntaxError(f"Line {idx}: function '{name}' already declared")
                functions[declared_name] = FuncInfo(params=params)
                pos += 1
                body_code: list[Instruction] = []
                func_scope = ScopeFrame(kind="func", vars={param: typ for param, typ in params})
                inner_pos = compile_block(
                    pos=pos,
                    out=body_code,
                    scopes=scopes + [func_scope],
                    func_name_stack=func_name_stack + [declared_name],
                    stop_tokens={"end"},
                )
                if inner_pos >= len(sanitized) or sanitized[inner_pos][1] != "end":
                    raise DragonSyntaxError(
                        f"Line {idx}: function '{name}' not closed with 'end'"
                    )
                body_code.append(Instruction(op="PUSH_CONST", arg=None, line=idx))
                body_code.append(Instruction(op="RETURN", line=idx))
                bytecode_functions[declared_name] = BytecodeFunction(
                    name=declared_name,
                    params=params,
                    return_type=functions[declared_name].return_type,
                    code=body_code,
                )
                pos = inner_pos + 1
                continue

            if_match = IF_RE.match(line)
            if if_match:
                condition = if_match.group(1).strip()
                cond_type = _infer_expr_type(condition, idx=idx, scopes=scopes, functions=functions, namespace=namespace)
                if cond_type != "bool":
                    raise DragonTypeError(f"Line {idx}: if condition must be bool")
                _compile_expr_to_bytecode(condition, idx, out, functions=functions, namespace=namespace)
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
                    raise DragonSyntaxError(f"Line {idx}: if without 'end'")

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
                        raise DragonSyntaxError(f"Line {idx}: else without 'end'")
                    out[jump_end_idx].arg = len(out)
                    pos += 1
                else:
                    out[jump_if_false_idx].arg = len(out)
                    pos += 1
                continue

            while_match = WHILE_RE.match(line)
            if while_match:
                condition = while_match.group(1).strip()
                cond_type = _infer_expr_type(condition, idx=idx, scopes=scopes, functions=functions, namespace=namespace)
                if cond_type != "bool":
                    raise DragonTypeError(f"Line {idx}: while condition must be bool")
                loop_start = len(out)
                _compile_expr_to_bytecode(condition, idx, out, functions=functions, namespace=namespace)
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
                    raise DragonSyntaxError(f"Line {idx}: while without 'end'")
                out.append(Instruction(op="JUMP", arg=loop_start, line=idx))
                out[jump_out_idx].arg = len(out)
                pos += 1
                continue

            let_typed_match = LET_TYPED_RE.match(line)
            if let_typed_match:
                name = let_typed_match.group(1)
                declared_type = let_typed_match.group(2)
                expr = let_typed_match.group(3)
                expr_type = _infer_expr_type(expr, idx=idx, scopes=scopes, functions=functions, namespace=namespace)
                if expr_type != declared_type and expr_type != "unknown":
                    raise DragonTypeError(
                        f"Line {idx}: variable '{name}' is {declared_type}, but got {expr_type}"
                    )
                scopes[-1].vars[name] = declared_type
                _compile_expr_to_bytecode(expr, idx, out, functions=functions, namespace=namespace)
                out.append(Instruction(op="STORE_VAR", arg=name, line=idx))
                pos += 1
                continue

            let_match = LET_RE.match(line)
            if let_match:
                name = let_match.group(1)
                expr = let_match.group(2)
                expr_type = _infer_expr_type(expr, idx=idx, scopes=scopes, functions=functions, namespace=namespace)
                scopes[-1].vars[name] = expr_type
                _compile_expr_to_bytecode(expr, idx, out, functions=functions, namespace=namespace)
                out.append(Instruction(op="STORE_VAR", arg=name, line=idx))
                pos += 1
                continue

            assign_match = ASSIGN_RE.match(line)
            if assign_match:
                name = assign_match.group(1)
                expr = assign_match.group(2)
                var_type = _resolve_var_type(name, scopes)
                if var_type is None:
                    raise DragonTypeError(f"Line {idx}: variable '{name}' not declared")
                expr_type = _infer_expr_type(expr, idx=idx, scopes=scopes, functions=functions, namespace=namespace)
                if expr_type != var_type and expr_type != "unknown":
                    raise DragonTypeError(
                        f"Line {idx}: variable '{name}' is {var_type}, but got {expr_type}"
                    )
                _compile_expr_to_bytecode(expr, idx, out, functions=functions, namespace=namespace)
                out.append(Instruction(op="STORE_VAR", arg=name, line=idx))
                pos += 1
                continue

            if line.startswith("return "):
                expr = line[len("return ") :].strip()
                if not func_name_stack:
                    raise DragonSyntaxError(f"Line {idx}: 'return' outside function")
                expr_type = _infer_expr_type(expr, idx=idx, scopes=scopes, functions=functions, namespace=namespace)
                current_func_name = func_name_stack[-1]
                current_func = functions[current_func_name]
                if current_func.return_type is None:
                    current_func.return_type = expr_type
                elif expr_type != current_func.return_type:
                    raise DragonTypeError(
                        f"Line {idx}: function '{current_func_name}' returns conflicting types "
                        f"({current_func.return_type} and {expr_type})"
                    )
                _compile_expr_to_bytecode(expr, idx, out, functions=functions, namespace=namespace)
                out.append(Instruction(op="RETURN", line=idx))
                pos += 1
                continue

            if line.startswith("print(") and line.endswith(")"):
                expr = line[len("print(") : -1].strip()
                if expr:
                    _infer_expr_type(expr, idx=idx, scopes=scopes, functions=functions, namespace=namespace)
                    _compile_expr_to_bytecode(expr, idx, out, functions=functions, namespace=namespace)
                else:
                    out.append(Instruction(op="PUSH_CONST", arg="", line=idx))
                out.append(Instruction(op="PRINT", line=idx))
                pos += 1
                continue

            _infer_expr_type(line, idx=idx, scopes=scopes, functions=functions, namespace=namespace)
            _compile_expr_to_bytecode(line, idx, out, functions=functions, namespace=namespace)
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
        raise DragonSyntaxError(f"Line {idx}: block not closed with 'end'")
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
            raise RuntimeError("Stack underflow in Dragon VM")
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
                raise DragonTypeError(f"Line {inst.line}: variable '{name}' not declared")
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
            if func_name in STD_NATIVE_FUNCTIONS:
                native = STD_NATIVE_FUNCTIONS[func_name]
                stack.append(native.impl(*args))
                continue
            if func_name not in program.functions:
                raise DragonTypeError(
                    f"Line {inst.line}: function '{func_name}' not declared"
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
                raise RuntimeError(f"Invalid comparator: {inst.arg}")
        elif inst.op == "HALT":
            break
        else:
            raise RuntimeError(f"Invalid opcode: {inst.op}")


def _instruction_to_dict(inst: Instruction) -> dict[str, object]:
    return {"op": inst.op, "arg": inst.arg, "line": inst.line}


def _instruction_from_dict(raw: dict[str, object]) -> Instruction:
    op = raw.get("op")
    line = raw.get("line")
    if not isinstance(op, str) or not isinstance(line, int):
        raise DragonSyntaxError("Invalid bytecode: malformed instruction")

    arg = raw.get("arg")
    if op == "CALL" and arg is not None:
        if not (isinstance(arg, list) and len(arg) == 2):
            raise DragonSyntaxError("Invalid bytecode: malformed CALL argument")
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
        raise DragonSyntaxError("Invalid bytecode: .dbc file is not valid JSON") from exc

    if not isinstance(raw, dict):
        raise DragonSyntaxError("Invalid bytecode: file root must be a JSON object")
    if raw.get("format") != "dragon-bytecode":
        raise DragonSyntaxError("Invalid bytecode: unknown format header")
    if raw.get("version") != BYTECODE_FORMAT_VERSION:
        raise DragonSyntaxError("Invalid bytecode: unsupported format version")

    main_raw = raw.get("main")
    funcs_raw = raw.get("functions")
    if not isinstance(main_raw, list) or not isinstance(funcs_raw, dict):
        raise DragonSyntaxError("Invalid bytecode: missing 'main' or 'functions' sections")

    main = [_instruction_from_dict(inst) for inst in main_raw]
    functions: dict[str, BytecodeFunction] = {}
    for name, fn_raw in funcs_raw.items():
        if not isinstance(name, str) or not isinstance(fn_raw, dict):
            raise DragonSyntaxError("Invalid bytecode: malformed function")
        params_raw = fn_raw.get("params")
        code_raw = fn_raw.get("code")
        return_type = fn_raw.get("return_type")
        if not isinstance(params_raw, list) or not isinstance(code_raw, list):
            raise DragonSyntaxError("Invalid bytecode: function with invalid params/code")
        params: list[tuple[str, str]] = []
        for param in params_raw:
            if (
                not isinstance(param, list)
                or len(param) != 2
                or not isinstance(param[0], str)
                or not isinstance(param[1], str)
            ):
                raise DragonSyntaxError("Invalid bytecode: malformed function parameter")
            params.append((param[0], param[1]))
        if return_type is not None and not isinstance(return_type, str):
            raise DragonSyntaxError("Invalid bytecode: malformed return_type")
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


def _make_module_loader(base_dir: pathlib.Path) -> callable:
    def _load(module_name: str) -> str:
        module_path = (base_dir / pathlib.Path(*module_name.split(".")).with_suffix(".dragon")).resolve()
        if not module_path.exists():
            raise DragonSyntaxError(f"Module '{module_name}' not found in {base_dir}")
        return read_file(module_path)

    return _load


def cmd_transpile(args: argparse.Namespace) -> int:
    src = pathlib.Path(args.file)
    if src.suffix != ".dragon":
        print("Error: file must have .dragon extension", file=sys.stderr)
        return 2

    source_code = read_file(src)
    module_loader = _make_module_loader(src.parent.resolve())
    try:
        result = transpile(source_code, module_loader=module_loader)
    except (DragonSyntaxError, DragonTypeError) as exc:
        print(f"Dragon Error: {exc}", file=sys.stderr)
        return 1

    output = pathlib.Path(args.output) if args.output else src.with_suffix(".py")
    write_file(output, result.python_code)
    print(f"Successfully transpiled: {output}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    src = pathlib.Path(args.file)
    if src.suffix != ".dragon":
        print("Error: file must have .dragon extension", file=sys.stderr)
        return 2

    source_code = read_file(src)
    module_loader = _make_module_loader(src.parent.resolve())
    try:
        program = compile_to_bytecode(source_code, module_loader=module_loader)
    except (DragonSyntaxError, DragonTypeError) as exc:
        print(f"Dragon Error: {exc}", file=sys.stderr)
        return 1

    run_bytecode(program)
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    src = pathlib.Path(args.file)
    if src.suffix != ".dragon":
        print("Error: file must have .dragon extension", file=sys.stderr)
        return 2

    source_code = read_file(src)
    module_loader = _make_module_loader(src.parent.resolve())
    try:
        program = compile_to_bytecode(source_code, module_loader=module_loader)
    except (DragonSyntaxError, DragonTypeError) as exc:
        print(f"Dragon Error: {exc}", file=sys.stderr)
        return 1

    output = pathlib.Path(args.output) if args.output else src.with_suffix(".dbc")
    write_bytecode_file(output, program)
    print(f"Install package created successfully: {output}")
    return 0


def cmd_runbc(args: argparse.Namespace) -> int:
    src = pathlib.Path(args.file)
    if src.suffix != ".dbc":
        print("Error: file must have .dbc extension", file=sys.stderr)
        return 2

    try:
        program = read_bytecode_file(src)
    except (OSError, DragonSyntaxError) as exc:
        print(f"Dragon Error: {exc}", file=sys.stderr)
        return 1

    run_bytecode(program)
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    src = pathlib.Path(args.file)
    if src.suffix != ".dragon":
        print("Error: file must have .dragon extension", file=sys.stderr)
        return 2

    source_code = read_file(src)
    module_loader = _make_module_loader(src.parent.resolve())
    try:
        program = compile_to_bytecode(source_code, module_loader=module_loader)
    except (DragonSyntaxError, DragonTypeError) as exc:
        print(f"Dragon Error: {exc}", file=sys.stderr)
        return 1

    app_name = args.name or src.stem
    app_type = args.app_type
    output_dir = pathlib.Path(args.output) if args.output else pathlib.Path("build") / app_name
    output_dir.mkdir(parents=True, exist_ok=True)

    bytecode_path = output_dir / f"{app_name}.dbc"
    write_bytecode_file(bytecode_path, program)

    metadata = {
        "name": app_name,
        "entrypoint": bytecode_path.name,
        "app_type": app_type,
        "source": src.name,
        "bytecode_format_version": BYTECODE_FORMAT_VERSION,
    }
    write_file(output_dir / "dragon-app.json", json.dumps(metadata, indent=2) + "\n")

    launcher_sh = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
        f'python3 "$SCRIPT_DIR/../dragonc.py" runbc "$SCRIPT_DIR/{bytecode_path.name}" "$@"\n'
    )
    write_file(output_dir / "run.sh", launcher_sh)
    (output_dir / "run.sh").chmod(0o755)

    launcher_bat = (
        "@echo off\r\n"
        "set SCRIPT_DIR=%~dp0\r\n"
        f'python "%SCRIPT_DIR%..\\dragonc.py" runbc "%SCRIPT_DIR%{bytecode_path.name}" %*\r\n'
    )
    write_file(output_dir / "run.bat", launcher_bat)

    if app_type == "desktop":
        desktop_entry = (
            "[Desktop Entry]\n"
            "Version=1.0\n"
            "Type=Application\n"
            f"Name={app_name}\n"
            f'Exec=sh -c "{output_dir / "run.sh"}"\n'
            "Terminal=true\n"
            "Categories=Utility;\n"
        )
        write_file(output_dir / f"{app_name}.desktop", desktop_entry)

    print(f"Build completed: {output_dir}")
    print(f"- bytecode: {bytecode_path}")
    print(f"- metadata: {output_dir / 'dragon-app.json'}")
    print(f"- launcher: {output_dir / 'run.sh'}")
    print(f"- launcher: {output_dir / 'run.bat'}")
    if app_type == "desktop":
        print(f"- desktop entry: {output_dir / f'{app_name}.desktop'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dragon language compiler/VM (MVP)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_transpile = sub.add_parser("transpile", help="Transpile .dragon file to Python")
    p_transpile.add_argument("file", help=".dragon source file")
    p_transpile.add_argument("-o", "--output", help=".py output file")
    p_transpile.set_defaults(func=cmd_transpile)

    p_run = sub.add_parser("run", help="Run .dragon program")
    p_run.add_argument("file", help=".dragon source file")
    p_run.set_defaults(func=cmd_run)

    p_install = sub.add_parser("install", help="Create installable .dbc package")
    p_install.add_argument("file", help=".dragon source file")
    p_install.add_argument("-o", "--output", help=".dbc output file")
    p_install.set_defaults(func=cmd_install)

    p_compile = sub.add_parser("compile", help="(legacy alias) Create installable .dbc package")
    p_compile.add_argument("file", help=".dragon source file")
    p_compile.add_argument("-o", "--output", help=".dbc output file")
    p_compile.set_defaults(func=cmd_install)

    p_runbc = sub.add_parser("runbc", help="Run .dbc bytecode")
    p_runbc.add_argument("file", help=".dbc bytecode file")
    p_runbc.set_defaults(func=cmd_runbc)

    p_build = sub.add_parser("build", help="Build desktop/CLI distributable package")
    p_build.add_argument("file", help=".dragon source file")
    p_build.add_argument("-o", "--output", help="build output directory")
    p_build.add_argument("-n", "--name", help="application name (default: source filename)")
    p_build.add_argument(
        "--app-type",
        choices=("cli", "desktop"),
        default="cli",
        help="target application type",
    )
    p_build.set_defaults(func=cmd_build)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
