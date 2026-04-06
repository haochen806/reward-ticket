FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    firefox-esr \
    libgtk-3-0 \
    libdbus-glib-1-2 \
    libxt6 \
    libx11-xcb1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    python -m camoufox fetch

COPY src/ src/
COPY config.yaml.example .

VOLUME /app/data

CMD ["python", "-m", "src.main", "/app/data/config.yaml"]
