#!/usr/bin/env python3
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass


class DragonSyntaxError(Exception):
    pass


@dataclass
class CompileResult:
    python_code: str


FUNC_RE = re.compile(r"^func\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*?)\)\s*$")
LET_RE = re.compile(r"^let\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$")
IF_RE = re.compile(r"^if\s+(.+)$")
WHILE_RE = re.compile(r"^while\s+(.+)$")


def _sanitize_line(line: str) -> str:
    return line.strip()


def transpile(source: str) -> CompileResult:
    lines = source.splitlines()
    out: list[str] = []
    indent = 0
    block_stack: list[str] = []

    for idx, raw in enumerate(lines, start=1):
        line = _sanitize_line(raw)

        if not line or line.startswith("#"):
            continue

        if line == "end":
            if not block_stack:
                raise DragonSyntaxError(f"Linha {idx}: 'end' sem bloco aberto")
            block_stack.pop()
            indent -= 1
            continue

        func_match = FUNC_RE.match(line)
        if func_match:
            name = func_match.group(1)
            args = func_match.group(2).strip()
            out.append("    " * indent + f"def {name}({args}):")
            indent += 1
            block_stack.append("func")
            continue

        if_match = IF_RE.match(line)
        if if_match:
            condition = if_match.group(1).strip()
            out.append("    " * indent + f"if {condition}:")
            indent += 1
            block_stack.append("if")
            continue

        if line == "else":
            if not block_stack or block_stack[-1] != "if":
                raise DragonSyntaxError(f"Linha {idx}: 'else' sem 'if' correspondente")
            indent -= 1
            out.append("    " * indent + "else:")
            indent += 1
            block_stack[-1] = "else"
            continue

        while_match = WHILE_RE.match(line)
        if while_match:
            condition = while_match.group(1).strip()
            out.append("    " * indent + f"while {condition}:")
            indent += 1
            block_stack.append("while")
            continue

        let_match = LET_RE.match(line)
        if let_match:
            name = let_match.group(1)
            expr = let_match.group(2)
            out.append("    " * indent + f"{name} = {expr}")
            continue

        if line.startswith("return "):
            out.append("    " * indent + line)
            continue

        if line.startswith("print(") and line.endswith(")"):
            out.append("    " * indent + line)
            continue

        # fallback para expressão/chamada simples
        out.append("    " * indent + line)

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
    except DragonSyntaxError as exc:
        print(f"Erro de sintaxe Dragon: {exc}", file=sys.stderr)
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
    except DragonSyntaxError as exc:
        print(f"Erro de sintaxe Dragon: {exc}", file=sys.stderr)
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
