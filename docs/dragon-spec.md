# Dragon Language Specification (v0.1)

## 1. Objetivo
A Dragon é uma linguagem simples para acelerar prototipação de apps e, no futuro, ser uma das linguagens principais do DragonOS.

## 2. Extensão de arquivo
Arquivos Dragon usam a extensão:

```text
.dragon
```

## 3. Regras léxicas
- Espaços e tabs no início da linha são ignorados no v0.1.
- Comentários iniciam com `#`.
- Linhas vazias são ignoradas.

## 4. Sintaxe (v0.1)

### 4.1 Variáveis
```dragon
let nome = "Dragon"
let x = 10
```

### 4.2 Saída
```dragon
print("Olá")
print(nome)
```

### 4.3 Funções
```dragon
func soma(a, b)
    return a + b
end
```

### 4.4 Chamada de função
```dragon
let resultado = soma(2, 3)
print(resultado)
```

## 5. Semântica (v0.1)
- `let` cria variável no escopo atual.
- `func` define função; bloco termina com `end`.
- `return` encerra execução da função e devolve valor.
- Expressões são avaliadas pelo backend Python (MVP).

## 6. Limitações do MVP
- Sem classes, módulos, loops ou condicionais.
- Sem tipagem estática.
- Backend depende de Python.

## 7. Roadmap curto
- v0.2: `if/else`, `while`.
- v0.3: tipos básicos e erros melhores.
- v0.4: compilação para bytecode próprio.
