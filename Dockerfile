# Imagem oficial do Playwright Python — versão travada igual ao requirements.txt
FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

# Instalar ffmpeg para post-processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

# Garantir que o Chromium do Playwright está instalado no caminho correto
RUN playwright install chromium

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
