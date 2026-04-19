# Imagem oficial do Playwright Python — versão travada igual ao requirements.txt
FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

# Cache buster — altere este valor para forçar rebuild do Render
ARG CACHE_BUST=2026-04-19-honest-v1

# Instalar ffmpeg para detecção de marca d'água, corte de endcard e compressão
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

# Garantir que Chromium está no caminho correto (playwright 1.58 == imagem 1.58)
RUN playwright install chromium

# yt-dlp mais recente
RUN pip install --no-cache-dir --break-system-packages --upgrade yt-dlp

# Copiar código do bot
COPY bot.py engine.py shopee_extractor.py ./

# Copiar cookies autenticados da Shopee (exportados pelo usuário)
# IMPORTANTE: este arquivo precisa estar no repositório GitHub junto com o código
COPY shopee_cookies.txt /app/shopee_cookies.txt

# Variáveis de ambiente
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PORT=10000
ENV SHOPEE_COOKIES_PATH=/app/shopee_cookies.txt

EXPOSE 10000
CMD ["python", "bot.py"]
