FROM python:3.12-slim

WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copiar ficheros del proyecto
COPY pyproject.toml .
COPY src/ src/
COPY config.yaml .

# Instalar HunterBot
RUN pip install --no-cache-dir -e .

# Comando por defecto: ejecutar búsquedas periódicas
CMD ["python", "-m", "hunterbot.scheduler"]
