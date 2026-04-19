# Imagem oficial do Playwright Python — já vem com Chromium + libs
FROM mcr.microsoft.com/playwright/python:v1.48.0-noble

# Instalar ffmpeg para post-processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

# yt-dlp mais recente (atualiza sempre no build)
RUN pip install --no-cache-dir --break-system-packages --upgrade yt-dlp

# Copiar código
COPY bot.py engine.py shopee_extractor.py ./

# Variáveis de ambiente
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PORT=10000

# Porta do health check
EXPOSE 10000

# Comando
CMD ["python", "bot.py"]
