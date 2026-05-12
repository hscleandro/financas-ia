# PROJECT_MEMORY.md — Controle Financeiro com Agentes de IA

> Arquivo de memória persistente do projeto. Atualizado ao longo do desenvolvimento.
> Use este arquivo para retomar o contexto em novas sessões.
>
> **Última atualização:** 2026-05-12
> **Status atual:** MVP 2 em andamento — guardrails de segurança (DA-014)

---

## Visão Geral do Projeto

Sistema pessoal de controle financeiro e investimentos baseado em Agentes de IA.
O usuário registra gastos em linguagem natural e consulta seu histórico financeiro via chat.

**Origem:** Projeto de conclusão do curso DSA 4.0 (Data Science Academy) — módulo de Agentes de IA.
**Destino real:** Sistema de uso diário + portfólio público. Não é só exercício acadêmico.

---

## Objetivos

### Objetivo primário
Controle financeiro pessoal via linguagem natural, com registro inteligente e consultas analíticas.

### Objetivo secundário
Aprendizado prático de: LangGraph, MCP (Model Context Protocol), RAG, observabilidade com LangSmith,
multi-agentes, guardrails e arquitetura de sistemas de IA.

### Exemplos de interação esperada
```
Usuário: "Gastei 55 reais no almoço"
Agente:  "Registrei: R$ 55,00 · Alimentação · dinheiro · hoje ✓"

Usuário: "Quanto gastei com alimentação esse mês?"
Agente:  "Você gastou R$ 320,50 com Alimentação em maio (7 lançamentos)."

Usuário: "Qual categoria teve maior gasto?"
Agente:  "Transporte liderou com R$ 480,00, seguido de Alimentação com R$ 320,50."
```

---

## Stack Tecnológica

| Componente | Tecnologia | Versão instalada | Motivo da escolha |
|---|---|---|---|
| Linguagem | Python | 3.12 | Ecossistema de IA, já usado no curso |
| LLM | OpenAI GPT | gpt-4o-mini (default) | Custo/benefício para uso diário |
| Orquestrador | LangGraph | 1.2.0 | Curso, flexibilidade, robusto |
| Protocolo agente | MCP (FastMCP) | 3.2.4 | Padrão do curso, separação clara servidor/cliente |
| Adaptador MCP | langchain-mcp-adapters | 0.2.2 | Bridge LangGraph ↔ MCP |
| Validação | Pydantic v2 | 2.13.4 | Tipagem forte, ótima DX |
| Banco de dados | SQLite | built-in | Simples, arquivo local, zero infra |
| Configuração | pydantic-settings | 2.14.1 | Centraliza env vars com tipagem |
| Observabilidade | LangSmith | 0.8.3 | Auto-instrumentação LangGraph |
| Env vars | python-dotenv | 1.2.2 | Padrão do curso |

**Nota:** Versões planejadas no design (LangGraph 0.4.7, FastMCP 1.9.1) foram substituídas pelas mais recentes disponíveis. API compatível — único ajuste necessário foi `await client.get_tools()` (virou coroutine em langchain-mcp-adapters 0.2.2).

### Variáveis de ambiente necessárias (`.env`)
```env
# LLM
OPENAI_API_KEY=sk-...

# Observabilidade
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_...
LANGCHAIN_PROJECT=financas-ia-mvp1

# Opcional — sobrescreve defaults do config.py
# OPENAI_MODEL=gpt-4o-mini
# DB_PATH=./financas.db
# MAX_EXPENSE_AMOUNT=100000
```

---

## Arquitetura Atual (MVP 1)

### Padrão arquitetural
```
┌─────────────────────────────────────────────────────────┐
│                      main.py (CLI)                      │
└────────────────────────┬────────────────────────────────┘
                         │ ainvoke()
┌────────────────────────▼────────────────────────────────┐
│                  agent/graph.py                         │
│              LangGraph StateGraph                       │
│                                                         │
│  START → [agent_node] ⇄ [tool_node] → END              │
│              │                │                         │
│           LLM call       executa MCP                    │
│         (OpenAI)           tools                        │
└────────────────────────┬────────────────────────────────┘
                         │ stdio subprocess
┌────────────────────────▼────────────────────────────────┐
│               mcp_server/server.py                      │
│                 FastMCP (stdio)                         │
│                                                         │
│  record_expense | query_expenses | get_summary          │
│  list_categories                                        │
└────────────────────────┬────────────────────────────────┘
                         │ sqlite3
┌────────────────────────▼────────────────────────────────┐
│                   financas.db (SQLite)                  │
│        tabelas: expenses, categories                    │
└─────────────────────────────────────────────────────────┘
```

### Camadas e responsabilidades

| Camada | Arquivo | Responsabilidade |
|---|---|---|
| Entrada | `main.py` | Loop CLI, thread_id de sessão |
| Orquestração | `agent/graph.py` | StateGraph, MemorySaver, bind_tools |
| Inteligência | `agent/prompts.py` | System prompt, instruções de extração |
| Validação lógica | `agent/guardrails.py` | Regras de negócio pré-tool |
| Protocolo | `mcp_server/server.py` | Tools MCP, validação Pydantic, hash |
| Dados | `database/setup.py` | Schema SQLite, seed de categorias |
| Modelos | `models/schemas.py` | Pydantic schemas compartilhados |
| Config | `config.py` | Settings centralizadas |

**Regra de ouro:** O MCP Server é um banco de dados inteligente (sem lógica de negócio complexa). O LangGraph é o cérebro (toda lógica vive aqui). Não inverter essa relação.

---

## Estrutura de Diretórios

```
financas-ia/
│
├── .env                        # Chaves de API (não versionar)
├── .gitignore
├── requirements.txt
├── PROJECT_MEMORY.md           # Este arquivo
│
├── config.py                   # Settings centralizadas (pydantic-settings)
│
├── database/
│   ├── __init__.py
│   └── setup.py                # Cria banco, tabelas, seed categorias
│
├── models/
│   ├── __init__.py
│   └── schemas.py              # Pydantic: ExpenseCreate, ExpenseRecord, Summary
│
├── mcp_server/
│   ├── __init__.py
│   └── server.py               # FastMCP (stdio) — 4 tools
│
├── agent/
│   ├── __init__.py
│   ├── prompts.py              # System prompt
│   ├── guardrails.py           # Validações de negócio
│   └── graph.py                # LangGraph StateGraph
│
└── main.py                     # Entry point CLI
```

---

## Banco de Dados

### Schema (SQLite)

```sql
-- Categorias fixas (seed imutável via agente)
CREATE TABLE categories (
    id          INTEGER   PRIMARY KEY AUTOINCREMENT,
    name        TEXT      NOT NULL UNIQUE,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Gastos (append-only — sem UPDATE/DELETE via agente)
CREATE TABLE expenses (
    id           INTEGER   PRIMARY KEY AUTOINCREMENT,
    amount       REAL      NOT NULL CHECK(amount > 0 AND amount < 100000),
    description  TEXT      NOT NULL,
    category     TEXT      NOT NULL REFERENCES categories(name),
    method       TEXT      NOT NULL DEFAULT 'dinheiro'
                           CHECK(method IN ('dinheiro','crédito','débito','pix','transferência')),
    expense_date DATE      NOT NULL DEFAULT CURRENT_DATE,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    hash         TEXT      NOT NULL UNIQUE
);
```

### Categorias (seed)
```
Alimentação | Transporte | Moradia | Saúde | Lazer
Educação | Vestuário | Tecnologia | Serviços | Outros
```

### Decisões de design
- `category` é `TEXT REFERENCES` (não INTEGER FK) → queries sem JOIN, mais legível
- `hash UNIQUE` → banco rejeita duplicata automaticamente, zero lógica extra
- Sem tabela `users` no MVP 1 (single-user por design)
- Sem tabela `income` no MVP 1 (scope control)
- Sem migrations no MVP 1 — só `CREATE TABLE IF NOT EXISTS`
  - Alembic entra no MVP 2+ quando o schema precisar evoluir

---

## Tools MCP

### `record_expense`
- **Operação:** INSERT com deduplicação via hash
- **Input:** amount, description, category, method, expense_date
- **Lógica interna:**
  - Pydantic valida todos os campos
  - Computa `hash = sha256(f"{amount:.2f}|{description_normalizada}|{date}")`
  - Hash da descrição: lowercase + strip + remove acentos + colapsa espaços
  - INSERT → retorna expense criado ou erro de duplicata
- **Output:** JSON com expense ou `{"error": "...", "tipo": "duplicata|invalido"}`

### `query_expenses`
- **Operação:** SELECT com filtros opcionais
- **Input:** start_date?, end_date?, category?, method?
- **Output:** lista de expenses

### `get_summary`
- **Operação:** SELECT + GROUP BY
- **Input:** start_date, end_date, group_by ('category'|'method'|'day'|'month')
- **Output:** dict com totais por dimensão + total geral

### `list_categories`
- **Operação:** SELECT all categories
- **Input:** nenhum
- **Output:** lista de strings com os nomes

### `find_expense_candidates` *(a implementar)*
- **Operação:** SELECT com lógica de "data mais recente"
- **Input:** keyword, expense_date? (YYYY-MM-DD, opcional)
- **Lógica interna:**
  - Com `expense_date`: `WHERE description LIKE '%keyword%' AND expense_date = ?`
  - Sem `expense_date`: primeiro `MAX(expense_date)` para o keyword, depois filtra por essa data
  - Normaliza keyword: lowercase + remove acentos
- **Output:** `{keyword, date_searched, total_found, records[]}`

### `delete_expense` *(a implementar)*
- **Operação:** Soft delete — `UPDATE SET deleted_at = NOW()`
- **Input:** expense_id (int), confirmed (bool)
- **Lógica:** rejeita se `confirmed=False`; valida existência; registra em `audit_log`
- **Output:** `{deleted, expense_id, record}` ou `{error, tipo}`

### `update_expense` *(a implementar)*
- **Operação:** UPDATE parcial com recálculo de hash
- **Input:** expense_id, confirmed, + campos opcionais (amount, description, category, method, expense_date)
- **Lógica:** rejeita se `confirmed=False`; recalcula hash se amount/description/date mudar; registra before/after em `audit_log`
- **Output:** `{updated, expense_id, old, new}` ou `{error, tipo}`

### O que deliberadamente NÃO existe no servidor MCP
- `delete_by_category`, `delete_by_period`, `delete_all` — exclusão em massa impossível por design
- `bulk_import` — MVP 2+
- Lógica de classificação — pertence ao agente
- Leitura direta do `audit_log` — não exposto como tool

---

## Fluxo LangGraph

### Grafo
```
START → agent_node ─[tool_call seguro]──→ tool_node → agent_node → ...
                  ↘[bulk delete detectado]→ guardrail_node → END
                  ↘[resposta final]────────→ END
```

### Estado
```python
class AgentState(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]
```

### Nós
- **`agent_node`:** invoca LLM com system_prompt + histórico de mensagens
- **`tool_node`:** executa tools MCP via `ToolNode(tools=tools)`
- **`guardrail_node`:** intercepta bulk delete; injeta stubs + mensagem de segurança

### Arestas
- `START → agent_node` (sempre)
- `agent_node → guardrail_node` (se >1 delete_expense na mesma resposta)
- `agent_node → tool_node` (se tool_calls presente e seguro)
- `agent_node → END` (se LLM gerou resposta final)
- `tool_node → agent_node` (sempre — retorna resultado para o LLM decidir próximo passo)
- `guardrail_node → END` (após emitir mensagem de segurança)

### Memória
- `MemorySaver()` in-memory
- `thread_id` gerado por sessão em `main.py` (ex: UUID ou timestamp)
- Contexto persiste durante a sessão, não entre sessões
- **Limitação MVP 1:** memória se perde ao reiniciar o programa

### MCP Transport
- **`stdio`** — servidor é subprocesso do cliente
- Configuração: `{"command": "python", "args": ["mcp_server/server.py"], "transport": "stdio"}`
- Zero setup extra — sem `uvicorn`, sem porta, sem segundo terminal

---

## Guardrails

### Arquitetura de defesa em profundidade (4 camadas)

```
Usuário
  │
  ▼
[Layer 1 — System Prompt]  ← instrução comportamental (mais fraco — LLM pode ignorar)
  │
  ▼
[Layer 2 — LangGraph guardrail_node]  ← intercepta tool_calls antes do tool_node (forte)
  │
  ▼
[Layer 3 — MCP Server]  ← validação técnica independente (última linha ativa)
  │
  ▼
[Layer 4 — SQLite soft delete + audit_log]  ← recuperação (defesa passiva)
```

### Layer 1 — System Prompt (instrução comportamental)
```
✓ Proibição explícita de exclusões em massa (com exemplos de frases bloqueadas)
✓ Proteção contra prompt injection (lista de padrões a recusar)
✓ HITL conversacional: 4 passos obrigatórios para delete/update
✓ Regra confirmed=True: só válida se confirmação estiver na mensagem ATUAL
✓ Para valores > R$ 1.000: mostrar resumo extraído e perguntar "Confirmar?"
```

### Layer 2 — LangGraph guardrail_node (interceptação arquitetural)
```
✓ Detecta múltiplos delete_expense em um único turno (parallel tool calls)
✓ Bloqueia ANTES de executar qualquer deleção
✓ Injeta ToolMessage stubs (mantém chain de mensagens consistente para turnos futuros)
✓ Retorna mensagem de segurança padrão ao usuário
✓ Rota: agent_node → guardrail_node → END (bypassa tool_node completamente)
```

### Layer 3 — MCP Server (validação técnica)
```
✓ delete_expense aceita APENAS expense_id: int (não aceita filtros, listas ou ranges)
✓ confirmed=False → rejeita imediatamente (sem toque no banco)
✓ Verifica existência do registro antes de operar
✓ Valida amount, expense_date, category, method independentemente do agente
✓ hash UNIQUE: banco rejeita duplicata (IntegrityError tratado)
```

### Layer 4 — SQLite soft delete + audit_log (recuperação)
```
✓ deleted_at TIMESTAMP NULL: dado nunca destruído fisicamente
✓ audit_log: snapshot before/after para toda mutação
✓ Recuperação manual possível via UPDATE SET deleted_at = NULL
✓ audit_log nunca exposto como MCP tool
```

### O que NÃO existe nos guardrails do MVP 2 ainda
- Human-in-the-Loop real com `interrupt()` → próxima etapa do MVP 2
  - Motivo: requer checkpointer externo (SqliteSaver), não MemorySaver
- Rate limiting → MVP 3+
- Teste automatizado de guardrails → DT-007 (próxima prioridade)

---

## Fluxo MCP (stdio)

```
main.py
  └─▶ MultiServerMCPClient({"financas": {"command": "python", ...}})
        └─▶ async with client.session("financas") as session:
              └─▶ tools = await load_mcp_tools(session)
                    └─▶ LangGraph bind_tools(tools)
                          └─▶ ToolNode executa tool
                                └─▶ MCP client serializa chamada → subprocess stdin
                                      └─▶ server.py recebe, executa, retorna via stdout
```

O `MultiServerMCPClient` gerencia o ciclo de vida do subprocesso. O servidor é iniciado automaticamente quando `client.session()` é aberto e encerrado quando o contexto fecha.

---

## Agentes

### MVP 1 — Agente Único ReAct
- **Nome:** Assistente Financeiro Pessoal
- **Modelo:** gpt-4o-mini (configurável via `OPENAI_MODEL`)
- **Tipo:** ReAct (Reasoning + Acting) via LangGraph
- **Tools disponíveis:** 4 tools MCP (record, query, summary, categories)
- **Memória:** MemorySaver in-memory (por sessão)
- **Prompt:** ver seção Convenções do Projeto

### Agentes futuros (MVP 2+)
- Agente Extrator de Entidades (especialista em parsing de linguagem natural)
- Agente Analista Financeiro (especialista em consultas e insights)
- Roteador (direciona para o agente correto)

---

## Estratégia de Observabilidade

### MVP 1 — LangSmith auto-tracing
Nenhum código de instrumentação necessário. Ativado via env vars.

**O que é capturado automaticamente:**
- Cada invocação do grafo (input/output completo)
- Execução de cada nó (agent_node, tool_node) com latência
- Chamadas LLM com tokens consumidos (prompt + completion)
- Tool calls com parâmetros e resultados
- Erros e exceções com stack trace

**Projeto LangSmith:** `financas-ia-mvp1`
**Como acessar:** https://smith.langchain.com → projeto `financas-ia-mvp1`

### Logging local
- `logging` padrão Python
- Nível INFO para operações normais
- Nível WARNING para tentativas de duplicata
- Nível ERROR para falhas de validação

### MVP 2+ — métricas customizadas
- Taxa de classificação incorreta (usuário corrige categoria)
- Distribuição de gastos por categoria ao longo do tempo
- Latência média de registro vs. consulta

---

## Estratégia de Memória

### MVP 1
- **Memória de conversa:** `MemorySaver` in-memory do LangGraph
- **Thread:** um por sessão CLI (gerado em `main.py`)
- **Contexto:** o histórico completo de mensagens da sessão é enviado ao LLM em cada turno
- **Limitação:** memória é perdida ao encerrar `main.py`

### Problema: crescimento de contexto
O `MemorySaver` acumula todas as mensagens da sessão. Em sessões longas, o contexto cresce e aumenta custo. No MVP 1, aceitamos essa limitação. Soluções para MVPs futuros:
- Summarização periódica da conversa
- Memória de longo prazo com SQLite (já existe o banco!)
- LangGraph `SqliteSaver` para persistência entre sessões

### MVP 2+ — memória persistente
- Trocar `MemorySaver` por `SqliteSaver` (LangGraph built-in)
- Usar o mesmo `financas.db` ou um arquivo separado de checkpoints

---

## Decisões Arquiteturais

### DA-001: Agente único no MVP 1
- **Decisão:** Um único agente ReAct faz tudo (extração + classificação + persistência + consulta)
- **Alternativa rejeitada:** Multi-agente com Extrator + Registrador
- **Motivo:** Overengineering para MVP. Aprender LangGraph com um grafo bem estruturado já ensina todos os conceitos essenciais
- **Revisão:** MVP 2 quando precisar de roteamento por intent

### DA-002: MCP stdio no MVP 1
- **Decisão:** Transport `stdio` (servidor como subprocesso)
- **Alternativa rejeitada:** `streamable-http` (requer uvicorn separado)
- **Motivo:** Zero setup, zero debugging de porta/conexão. Curso já mostrou streamable-http — agora aprender o fluxo, não a infra
- **Revisão:** MVP 3+ quando precisar de servidor compartilhado ou API REST

### DA-003: category como TEXT REFERENCES
- **Decisão:** Coluna `category TEXT REFERENCES categories(name)`, não FK com INTEGER
- **Alternativa rejeitada:** `category_id INTEGER FOREIGN KEY`
- **Motivo:** Queries de análise ficam legíveis sem JOIN. Integridade garantida pelo Pydantic antes do INSERT. Em SQLite, FK enforcement precisa de `PRAGMA foreign_keys=ON` a cada conexão — risco de bug silencioso
- **Trade-off:** Redundância mínima de dado (nome repetido nas linhas) — aceitável para volume de controle pessoal

### DA-004: Hash interno ao servidor MCP
- **Decisão:** Hash SHA256 computado dentro de `record_expense` no servidor
- **Alternativa rejeitada:** Agente envia o hash pronto
- **Motivo:** Agente não deve conhecer detalhes de implementação de deduplicação. Normalização da descrição fica centralizada em um lugar só

### DA-005: Sem HITL real no MVP 1
- **Decisão:** Confirmação de valores altos implementada via system prompt (instrução comportamental), não via `interrupt()` do LangGraph
- **Alternativa rejeitada:** `interrupt()` + `Command(resume=...)` do LangGraph
- **Motivo:** HITL real requer checkpointer externo persistente. `MemorySaver` in-memory não sobrevive a reinicializações — implementação incompleta criaria falsa sensação de segurança
- **Revisão:** MVP 2 com `SqliteSaver` como checkpointer

### DA-006: Sem migrations no MVP 1
- **Decisão:** `CREATE TABLE IF NOT EXISTS` direto no `setup.py`
- **Alternativa rejeitada:** Alembic desde o início
- **Motivo:** Alembic adiciona complexidade que não se justifica com um schema estável no MVP 1
- **Revisão:** Quando o schema precisar evoluir pela primeira vez (provável no MVP 2-3)

### DA-007: config.py com pydantic-settings
- **Decisão:** Centralizar toda configuração em `config.py` usando `pydantic-settings`
- **Alternativa rejeitada:** `os.getenv()` espalhado
- **Motivo:** Tipagem, validação de env vars na inicialização, facilita testes, facilita evolução
- **Não é overengineering:** é o mínimo para um projeto que vai para produção pessoal

### DA-008: Soft delete + audit log para operações destrutivas
- **Decisão:** Exclusões usam `deleted_at TIMESTAMP NULL` (soft delete). Toda mutação grava snapshot em `audit_log`.
- **Alternativa rejeitada:** `DELETE FROM` físico; ausência de auditoria
- **Motivo:** Dados financeiros nunca devem ser destruídos silenciosamente. Soft delete permite recuperação manual; audit log garante rastreabilidade. Custo: ~1 coluna + 1 tabela.
- **Impacto no schema:** coluna `deleted_at` na tabela `expenses` + tabela `audit_log`. Migração via `ALTER TABLE IF NOT EXISTS` para bancos existentes.
- **Regra:** todas as queries de leitura filtram `WHERE deleted_at IS NULL`. `audit_log` nunca é exposto como MCP tool.

### DA-009: confirmed=True como gate obrigatório em tools destrutivas
- **Decisão:** `delete_expense(expense_id, confirmed)` e `update_expense(expense_id, confirmed, ...)` rejeitam imediatamente se `confirmed=False` (default).
- **Alternativa rejeitada:** HITL real com `interrupt()` do LangGraph (requer SqliteSaver — MVP 2+)
- **Motivo:** O parâmetro `confirmed` é o gate técnico que protege contra execução acidental mesmo que o system prompt seja ignorado ou sofra prompt injection. É a última linha de defesa antes do banco.
- **Regra no system prompt:** o agente só passa `confirmed=True` se a mensagem ATUAL do usuário contiver confirmação explícita ("sim", "confirmo", "yes", "pode").
- **Revisão:** substituir por `interrupt()` real no MVP 2 quando migrar para `SqliteSaver`.

### DA-010: find_expense_candidates como tool dedicada para busca pré-destrutiva
- **Decisão:** Nova tool `find_expense_candidates(keyword, expense_date?)` usada obrigatoriamente antes de qualquer delete ou update.
- **Alternativa rejeitada:** usar `query_expenses` genérico; colocar lógica de "mais recente" no nó LangGraph
- **Motivo:** Separar a busca da execução cria um ponto de verificação natural antes de qualquer mutação. A lógica de "retornar apenas a data mais recente" é determinística e pertence ao servidor (requer SQL), não ao LLM.
- **Comportamento:**
  - Com `expense_date`: filtra por data exata informada
  - Sem `expense_date`: executa `MAX(expense_date)` para o keyword e filtra por essa data
  - Retorna `{keyword, date_searched, total_found, records}` — rastreável no LangSmith

### DA-012: Alembic como gerenciador de migrations (MVP 2)
- **Decisão:** Adotar Alembic para gerenciar toda evolução de schema a partir do MVP 2.
- **Alternativa rejeitada:** continuar com `ALTER TABLE` manual em `setup.py`
- **Motivo:** O schema já evoluiu duas vezes (added `deleted_at`, `audit_log`). O hack `ALTER TABLE IF NOT EXISTS` em `setup.py` não escala — Alembic é a solução certa agora.
- **Modelo de convivência:**
  - `setup_database()` permanece no `server.py` como safety net para o subprocesso MCP
  - `main.py` chama `run_migrations()` (Alembic `upgrade head`) no startup — autoridade final sobre o schema
  - Migrations usam `op.execute()` com SQL raw (sem SQLAlchemy ORM) — compatível com sqlite3 existente
  - `0001_initial_schema` captura o estado atual como baseline; DBs existentes recebem `alembic stamp 0001`
- **Regra futura:** qualquer mudança de schema passa por migration Alembic — nunca mais `ALTER TABLE` em `setup.py`

### DA-014: Guardrails de segurança para exclusão em massa (incidente 2026-05-12)
- **Incidente:** Ao receber o comando "apaga todos os gastos do mês", o LLM gerou múltiplos `delete_expense` em um único `tool_calls` (parallel tool calling do OpenAI), zerando o banco. O único guardrail existente era o system prompt, que o LLM ignorou.
- **Root cause:** Três falhas de design combinadas:
  1. `gpt-4o-mini` suporta parallel tool calls — o LLM pode chamar a mesma tool N vezes em uma única resposta
  2. `should_call_tools` passava toda a lista de tool_calls para `tool_node` sem inspecionar conteúdo
  3. O system prompt era a única defesa, mas LLMs podem anulá-la sob instrução direta do usuário
- **Decisão:** Defesa em profundidade com 4 camadas (ver seção Guardrails)
- **Camada nova:** `guardrail_node` no LangGraph — detecta múltiplos `delete_expense` em um turno antes de executar qualquer um; injeta ToolMessage stubs para manter a chain de mensagens consistente; retorna a mensagem de segurança padrão; rota direto para END
- **System prompt:** Adicionadas seção "PROIBIÇÃO ABSOLUTA — Exclusões em massa" (com exemplos de frases bloqueadas) e seção "Proteção contra prompt injection" (padrões de ataque conhecidos)
- **Princípio fixado:** A assinatura `delete_expense(expense_id: int, confirmed: bool)` já impede bulk delete por chamada única. O `guardrail_node` cobre o caso de múltiplas chamadas paralelas. O system prompt cobre o caso de loop sequencial entre turnos.
- **O que ainda NÃO está coberto:** loop sequencial (um delete por turno) — depende do system prompt + comportamento do LLM. Solução completa: HITL real com `interrupt()` no MVP 2.
- **Testes necessários (DT-007):**
  - `test_guardrail_blocks_parallel_delete` — cria estado com AIMessage tendo 2+ delete_expense → confirma que guardrail_node é ativado
  - `test_single_delete_passes_guardrail` — confirma que 1 delete_expense passa normalmente
  - `test_bulk_delete_prompt_refusal` — testa frases proibidas no system prompt (via mock do LLM)
  - `test_delete_without_confirmed_blocked` — confirma que MCP server rejeita confirmed=False

### DA-013: Escopo do MVP 2 (análise crítica)
- **Inclui:** SqliteSaver + trimming, interrupt() HITL, pytest, Alembic, retry OpenAI
- **Exclui deliberadamente:** multi-agente, structlog, output guardrails, service layer, cache, feature flags
- **Multi-agente rejeitado para MVP 2:** agente único já funciona bem; roteador triplicaria calls ao LLM; complexidade artificial sem ganho real
- **structlog rejeitado:** LangSmith cobre ~90% da observabilidade necessária; adicionar structlog seria duplicação
- **Critério de conclusão MVP 2:**
  - Sessão anterior disponível ao reiniciar (`python main.py`)
  - delete/update usam `interrupt()` real
  - `pytest tests/` passa com ≥80% cobertura do MCP server
  - Schema evoluível via `alembic upgrade head`
  - Chamadas OpenAI com retry automático

### DA-011: Separação de responsabilidades — interpretação vs execução
- **Decisão:** Interpretação temporal fica no LLM; lógica SQL fica no servidor MCP.
- **Regra:**
  - LLM converte linguagem natural → `YYYY-MM-DD` quando há data específica ("ontem", "02/03")
  - LLM **não** converte ranges vagos ("semana passada", "mês passado") — trata como ausente, servidor usa lógica do mais recente
  - Servidor executa `MAX(expense_date)` quando `expense_date` é omitida
- **Motivo:** LLM é bom em semântica; servidor é confiável para lógica de dados. Misturar os dois cria comportamento não-determinístico e difícil de testar.
- **Proteção contra ambiguidade:** `find_expense_candidates` sempre retorna `total_found`; se 0, o agente oferece alternativa sem tentar deletar. Se >1, lista e pede escolha por ID.

---

## Roadmap de MVPs

### MVP 1 — Base (atual) ✓ COMPLETO
**Foco:** Registro, consulta, exclusão e edição via CLI
- Agente único ReAct
- MCP stdio com 7 tools (record, query, summary, categories, find_candidates, delete, update)
- SQLite com 3 tabelas (expenses + categories + audit_log)
- Soft delete + audit log
- Guardrails: Pydantic + DB constraints + confirmed=True gate
- HITL conversacional (confirmação via chat)
- Observabilidade LangSmith
- CLI simples com loop de mensagens

### MVP 2 — Robustez
**Foco:** Qualidade e confiabilidade
- HITL real com `interrupt()` + `SqliteSaver`
- Memória persistente entre sessões
- Multi-agente: Extrator + Analista + Roteador
- Testes automatizados (pytest)
- Logging estruturado (structlog)
- Guardrails de output (validar que resposta faz sentido)

### MVP 3 — Importação e Histórico
**Foco:** Popular com dados reais
- Tool `bulk_import` para importar CSVs do banco/cartão
- RAG para busca semântica em descrições
- Agentic RAG com LangGraph
- Categorização assistida por embeddings

### MVP 4 — Análise e Alertas
**Foco:** Inteligência financeira
- Orçamento mensal por categoria
- Alertas de estouro de budget
- Comparativo mês a mês
- Insights automáticos ("Você gastou 40% mais em Lazer este mês")
- Registro de investimentos

### MVP 5 — Integrações
**Foco:** Canais de entrada
- WhatsApp / Telegram (via webhook)
- Registro por áudio (Whisper API)
- Leitura de comprovantes (visão computacional)

### MVP 6 — API e Interface
**Foco:** Produto completo
- FastAPI como backend
- Dashboard com gráficos (Streamlit ou frontend simples)
- Múltiplos usuários
- Exportação de relatórios PDF/Excel

---

## Funcionalidades Futuras

- [ ] Importação de extratos bancários (CSV/OFX)
- [ ] Integração WhatsApp/Telegram
- [ ] Registro por áudio (Whisper)
- [ ] Leitura de comprovantes por imagem
- [ ] Dashboard com gráficos via linguagem natural
- [ ] Orçamento mensal por categoria + alertas
- [ ] Registro de investimentos (renda fixa, variável)
- [ ] Memória financeira do usuário (padrões, médias históricas)
- [ ] Relatório mensal automático
- [ ] Exportação CSV/PDF
- [ ] API REST (FastAPI)
- [ ] Frontend web
- [ ] Múltiplos usuários
- [ ] Sincronização com bancos via Open Finance

---

## Dívidas Técnicas

| ID | Descrição | Impacto | Quando resolver |
|---|---|---|---|
| DT-001 | `MemorySaver` in-memory perde contexto ao reiniciar | Baixo (MVP 1 é sessão única) | MVP 2 |
| DT-002 | Sem migrations de banco (só `IF NOT EXISTS`) | Médio (bloqueante se schema mudar) | MVP 2-3 |
| DT-003 | Sem testes automatizados | Alto (qualidade) | MVP 2 |
| DT-004 | HITL via prompt, não via `interrupt()` real | Médio (segurança) | MVP 2 |
| DT-005 | Thread safety do SQLite (conexão única) | Baixo (single-user) | MVP 4+ |
| DT-006 | Sem retry para falhas de chamada à OpenAI | Baixo (uso pessoal) | MVP 3 |
| DT-007 | Sem testes automatizados para guardrails de segurança | Alto (regressão crítica) | MVP 2 — próxima prioridade |

---

## Próximos Passos

### Imediato — MVP 1
1. [x] Criar `config.py`
2. [x] Criar `database/setup.py`
3. [x] Criar `models/schemas.py`
4. [x] Criar `mcp_server/server.py`
5. [x] Criar `agent/prompts.py`
6. [x] Criar `agent/guardrails.py`
7. [x] Criar `agent/graph.py`
8. [x] Criar `main.py`
9. [x] Adicionar OPENAI_API_KEY no `.env`
10. [x] Testar fluxo end-to-end — registro e consulta funcionando
11. [ ] Validar traces no LangSmith (ver nota abaixo)

**Nota LangSmith:** `LANGCHAIN_TRACING_V2` deve estar sem aspas no `.env` (ex: `LANGCHAIN_TRACING_V2=true`, não `="true"`).
O LangChain lê essa variável diretamente do ambiente, não via `config.py`.

### Decisão resolvida
- [x] **Fluxo de registro:** Opção A — direto (registra imediatamente, confirma só para valores > R$ 1.000)

### Ambiente
- Conda env: `financas-ia` (Python 3.12)
- Ativar: `conda activate financas-ia`
- Rodar: `python main.py` (a partir do diretório `financas-ia/`)

---

## Convenções do Projeto

### Código
- Python 3.12, type hints em tudo
- Pydantic v2 para toda validação de dados
- `async/await` no LangGraph (padrão do framework)
- Nomes em português para variáveis de domínio, inglês para infraestrutura
- Sem comentários óbvios — código auto-documentado
- Um comentário curto apenas quando o "porquê" não é óbvio

### Banco de dados
- Tabelas: prefixo sem convenção especial (evitar `tb_` — escolha do projeto novo)
- Datas sempre em `DATE` (YYYY-MM-DD), timestamps em `TIMESTAMP`
- Nunca deletar dados financeiros via agente — append-only

### Git
- Commits por MVP / feature concluída
- `.env` nunca versionado
- `financas.db` nunca versionado (dados pessoais)

### Nomenclatura de arquivos
- `snake_case` para tudo
- Sem prefixo `dsa_` (esse era do curso — projeto novo tem identidade própria)

---

## Aprendizados Importantes

### Sobre MCP
- O servidor MCP é uma camada de dados, não de lógica de negócio
- O agente (LangGraph) é o cérebro — regras de negócio ficam aqui
- `stdio` é ideal para desenvolvimento — zero infra extra
- `streamable-http` é para quando precisar de servidor compartilhado

### Sobre LangGraph
- `MemorySaver` é in-memory — perde estado ao reiniciar o processo
- Para persistência real entre sessões: `SqliteSaver` ou `PostgresSaver`
- HITL com `interrupt()` requer checkpointer externo (não MemorySaver)
- `StateGraph` com estado simples (`messages`) é suficiente para MVP

### Sobre Guardrails
- Dois layers são suficientes: Pydantic no servidor + prompt no agente
- `UNIQUE constraint` do SQLite é o guardrail mais confiável para duplicatas
- Não expor tools destrutivas é mais seguro do que guardrail que tenta bloqueá-las

### Sobre LLM
- `gpt-4o-mini` é adequado para extração de entidades e classificação simples
- Temperature 0 para tarefas de extração (determinístico)
- Lista fixa de categorias no prompt elimina inconsistência de classificação

---

*Este arquivo é mantido manualmente ao longo do desenvolvimento.*
*Atualize as seções "Próximos Passos", "Dívidas Técnicas" e "Decisões Arquiteturais" a cada etapa concluída.*
