# Dockerfile para Finanças IA - Telegram Bot
# Suporta modo polling (desenvolvimento) e webhook (produção)

FROM python:3.11-slim

# Metadata
LABEL maintainer="financas-ia"
LABEL description="Assistente Financeiro Pessoal com IA e Telegram Bot"

# Variáveis de ambiente
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Diretório de trabalho
WORKDIR /app

# Instalar dependências do sistema
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements e instalar dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código da aplicação
COPY . .

# Criar diretórios para dados persistentes
RUN mkdir -p /app/data

# Variável de ambiente para escolher modo de execução
# BOT_MODE: "polling" (padrão) ou "webhook"
ENV BOT_MODE=polling

# Expor porta para webhook (apenas usado em modo webhook)
EXPOSE 8000

# Script de entrypoint
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
