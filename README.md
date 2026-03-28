# Dragon Language (MVP)

Dragon é uma linguagem de programação inicial (MVP) com extensão `.dragon`.

Objetivo deste repositório:
- Definir uma base simples da linguagem Dragon.
- Permitir criar pequenos apps de terminal.
- Servir de base para evoluir para uma linguagem mais robusta para o futuro SO.

## O que já existe neste MVP

- Parser e transpiler de `.dragon` para Python.
- Execução de programas Dragon via CLI.
- Checagem estática de tipos básicos: `int`, `string`, `bool`.
- Sintaxe básica com:
  - `let` (variáveis)
  - `print(...)`
  - `input(...)`
  - funções com `func ... end`
  - condicionais com `if ... else ... end`
  - laços com `while ... end`
  - `return`
  - comentários com `#`

## Estrutura

- `docs/dragon-spec.md` → especificação inicial da linguagem.
- `dragonc.py` → compilador/transpilador principal.
- `examples/hello.dragon` → exemplo simples.
- `examples/math.dragon` → exemplo com função.
- `examples/control_flow.dragon` → exemplo com `if/else` e `while`.

## Como executar

Pré-requisito: Python 3.10+

```bash
python3 dragonc.py run examples/hello.dragon
python3 dragonc.py run examples/math.dragon
python3 dragonc.py run examples/input_and_func.dragon
```

Para transpilar sem rodar:

```bash
python3 dragonc.py transpile examples/math.dragon -o build/math.py
```

## Próximos passos recomendados

1. Criar bytecode e VM da Dragon (em vez de transpilar para Python).
2. Implementar módulos e biblioteca padrão.
3. Criar `dragon build` para apps desktop/CLI.
4. Definir caminho para kernel/userspace do futuro SO (DragonOS).
