# Estrutura do Projeto

Organização do código e documentação do financas-ia.

## 📁 Diretórios Principais

```
financas-ia/
├── agent/                      # Agente LangGraph
│   ├── graph.py               # Grafo de estados e nós
│   ├── prompts.py             # System prompt original
│   ├── prompts_telegram.py    # System prompt otimizado para Telegram
│   ├── tools.py               # LangChain tools
│   └── guardrails.py          # Validações de segurança
│
├── api/                       # API FastAPI (webhook produção)
│   └── webhook.py             # Endpoint para webhook do Telegram
│
├── bot/                       # Telegram Bot
│   ├── handlers.py            # Processamento de mensagens e callbacks
│   └── keyboards.py           # Teclados inline e formatação
│
├── database/                  # Camada de dados
│   ├── setup.py               # Setup inicial do banco
│   └── user_setup.py          # Gestão de usuários
│
├── migrations/                # Alembic migrations
│   └── versions/              # Histórico de mudanças no schema
│
├── mcp_server/                # MCP Server (MVP 1-2, legacy)
│   └── server.py              # Servidor MCP original
│
├── models/                    # Modelos de dados
│   └── schemas.py             # Pydantic schemas
│
├── services/                  # Service Layer
│   └── expense_service.py     # Lógica de negócio
│
├── tests/                     # Testes
│   ├── conftest.py            # Fixtures pytest
│   ├── test_service_layer.py
│   ├── test_tools_integration.py
│   ├── test_multitenant_isolation.py
│   ├── test_guardrails.py
│   ├── test_mcp_server.py
│   └── test_*.py
│
├── data/                      # Dados persistentes (volumes)
│   ├── financas.db            # Banco de dados principal
│   └── checkpoints.db         # Estados do LangGraph
│
└── docs/                      # Documentação
    ├── diagrams/              # Diagramas PlantUML
    ├── planning/              # Docs de planejamento (gitignored)
    ├── CHANGELOG_SPRINT5.md   # Changelog da Sprint 5
    ├── README_TELEGRAM.md     # Guia de integração Telegram
    └── UX_TELEGRAM_GUIDELINES.md  # Boas práticas de UX
```

## 📄 Arquivos na Raiz

### Entrypoints
- **main.py** - Entrypoint MCP Server (MVP 1-2)
- **main_telegram_polling.py** - Entrypoint bot Telegram (modo polling)
- **setup_telegram_user.py** - Script de setup de usuários

### Configuração
- **config.py** - Configurações via Pydantic Settings
- **requirements.txt** - Dependências Python
- **.env** - Variáveis de ambiente (gitignored)
- **.env.docker.example** - Template .env para Docker

### Docker
- **Dockerfile** - Imagem Docker
- **docker-compose.yml** - Orquestração
- **docker-entrypoint.sh** - Script de inicialização
- **.dockerignore** - Arquivos excluídos do build

### Ferramentas
- **bot_control.sh** - Script de controle do bot (start/stop/status)
- **alembic.ini** - Configuração Alembic para migrations

### Documentação
- **README.md** - Documentação principal do projeto

## 📝 Documentação (docs/)

### Guias de Uso
- **README_TELEGRAM.md** - Como configurar e usar o Telegram Bot
- **UX_TELEGRAM_GUIDELINES.md** - Boas práticas de UX mobile

### Histórico
- **CHANGELOG_SPRINT5.md** - Mudanças da Sprint 5

### Diagramas (docs/diagrams/)
- Diagramas PlantUML de arquitetura dos MVPs 1-2

### Planejamento (docs/planning/)
**Atenção:** Este diretório é ignorado pelo git (.gitignore)
- Documentos de arquitetura (ARQUITETURA_MVP*.md)
- Planos de execução (PLANO_EXECUCAO_MVP*.md)
- Memória do projeto (PROJECT_MEMORY.md)

## 🧪 Testes (tests/)

### Por Camada
- **test_service_layer.py** - Testa ExpenseService
- **test_tools_integration.py** - Testa tools do LangChain
- **test_multitenant_isolation.py** - Testa isolamento de dados

### Por Feature
- **test_guardrails.py** - Testa proteções de segurança
- **test_mcp_server.py** - Testa MCP Server (legacy)
- **test_query_expenses.py** - Testa consultas
- **test_da016_manual.py** - Testes manuais DA-016

### Configuração
- **conftest.py** - Fixtures compartilhadas do pytest

## 🗄️ Banco de Dados (data/)

**Atenção:** Este diretório é ignorado pelo git, exceto .gitkeep

### Arquivos SQLite
- **financas.db** - Banco principal com expenses, categories, etc.
- **checkpoints.db** - Estados do LangGraph para HITL
- ***.db-shm** - Shared memory (temporário)
- ***.db-wal** - Write-Ahead Log (temporário)

## 🔒 Arquivos Ignorados (.gitignore)

### Ambiente
- `.env`, `.env.example` - Variáveis de ambiente
- `venv/`, `.venv/` - Ambientes virtuais Python

### Banco de Dados
- `*.db`, `*.db-shm`, `*.db-wal` - SQLite
- `data/*` - Dados persistentes (exceto .gitkeep)

### Temporários
- `*.backup`, `*.bak`, `*.tmp` - Backups
- `*.log` - Logs
- `.coverage`, `htmlcov/`, `.pytest_cache/` - Cobertura de testes

### Build
- `__pycache__/`, `*.pyc`, `*.pyo` - Python compiled
- `*.egg-info/`, `dist/`, `build/` - Packaging

### Planejamento
- `docs/planning/` - Documentos de arquitetura e planejamento

### Sistema
- `.DS_Store`, `Thumbs.db` - Arquivos do OS
- `.idea/`, `.vscode/` - IDEs

## 🚀 Scripts Úteis

### Desenvolvimento
```bash
# Iniciar bot em modo polling
python main_telegram_polling.py

# Ou usar script de controle
./bot_control.sh start
./bot_control.sh status
./bot_control.sh logs -f
./bot_control.sh stop
```

### Setup
```bash
# Adicionar usuário à whitelist
python setup_telegram_user.py TELEGRAM_ID "Nome"

# Rodar migrations
alembic upgrade head
```

### Testes
```bash
# Todos os testes
pytest

# Com cobertura
pytest --cov=. --cov-report=html

# Teste específico
pytest tests/test_service_layer.py -v
```

### Docker
```bash
# Build e start
docker-compose up -d

# Logs
docker-compose logs -f

# Stop
docker-compose down
```

## 📚 Referências Internas

- [README.md](../README.md) - Guia principal
- [UX_TELEGRAM_GUIDELINES.md](UX_TELEGRAM_GUIDELINES.md) - Boas práticas UX
- [README_TELEGRAM.md](README_TELEGRAM.md) - Integração Telegram
- [CHANGELOG_SPRINT5.md](CHANGELOG_SPRINT5.md) - Mudanças Sprint 5

---

**Última atualização:** Sprint 5 - Estabilização (MVP 3)
