import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

# Garante que o diretório raiz do projeto está no path para importar config.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings

# Objeto de configuração do Alembic — lê alembic.ini
alembic_config = context.config

# Sobrescreve sqlalchemy.url com o valor real de config.py
# Isso garante que DB_PATH do .env é respeitado em todos os ambientes
alembic_config.set_main_option("sqlalchemy.url", f"sqlite:///{settings.db_path}")

# Configura logging conforme definido no alembic.ini
if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

# Sem metadata de ORM — usamos SQL raw nas migrations
target_metadata = None


def run_migrations_offline() -> None:
    """Gera SQL sem conectar ao banco (usado para gerar scripts)."""
    url = alembic_config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Aplica migrations diretamente no banco."""
    engine = create_engine(
        alembic_config.get_main_option("sqlalchemy.url"),
        poolclass=pool.NullPool,
    )
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
