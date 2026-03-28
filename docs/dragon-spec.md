# Dragon Language Specification (v0.2)

## 1. Objetivo
A Dragon é uma linguagem simples para acelerar prototipação de apps e, no futuro, ser uma das linguagens principais do DragonOS.

## 2. Extensão de arquivo
Arquivos Dragon usam a extensão:

```text
.dragon
```

## 3. Regras léxicas
- Espaços e tabs no início da linha são ignorados no v0.2.
- Comentários iniciam com `#`.
- Linhas vazias são ignoradas.

## 4. Sintaxe (v0.2)

### 4.1 Tipos básicos
Tipos suportados no MVP:
- `int`
- `string`
- `bool`

### 4.2 Variáveis
Declaração explícita com tipo:

```dragon
let nome: string = "Dragon"
let x: int = 10
let ativo: bool = true
```

Também é permitido inferir o tipo na declaração sem anotação:

```dragon
let total = 42
```

Reatribuição usa `=` sem `let`:

```dragon
total = total + 1
```

### 4.3 Saída
```dragon
print("Olá")
print(nome)
```

### 4.4 Entrada (input)
```dragon
let nome: string = input("Seu nome: ")
print(nome)
```

### 4.5 Funções
Parâmetros de função devem ser tipados:

```dragon
func soma(a: int, b: int)
    return a + b
end
```

### 4.6 Chamada de função
```dragon
let resultado: int = soma(2, 3)
print(resultado)
```

### 4.7 Condicionais
```dragon
if x > 10
    print("maior")
else
    print("menor ou igual")
end
```

### 4.8 Laços
```dragon
let i: int = 0
while i < 3
    print(i)
    i = i + 1
end
```

## 5. Semântica (v0.2)
- `let` cria variável no escopo atual.
- `input(...)` lê dados do terminal e retorna `string`.
- `func` define função; bloco termina com `end`.
- `if`/`else` permite desvio condicional.
- `while` permite repetição baseada em condição.
- `return` encerra execução da função e devolve valor.
- Expressões são compiladas para bytecode Dragon e executadas na VM Dragon.
- O compilador realiza checagem estática:
  - condição de `if/while` deve ser `bool`;
  - não permite reatribuir variável com tipo diferente;
  - não permite usar variável não declarada;
  - valida tipos de argumentos em chamadas de função.

## 6. Limitações do MVP
- Sem classes e módulos.
- Sem anotação explícita de tipo de retorno em `func`.
- Bytecode ainda não é serializado para arquivo próprio (`.dbc`).

## 7. Roadmap curto
- v0.3: melhorar inferência e tipos de retorno de função.
- v0.4: serialização de bytecode e toolchain (`dragon build`).
