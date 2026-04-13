FROM python:3.12-slim

# Install Camoufox dependencies (Firefox-based, works on ARM64)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    firefox-esr \
    libgtk-3-0 \
    libdbus-glib-1-2 \
    libxt6 \
    libx11-xcb1 \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

# Virtual framebuffer for headless on Pi (no display)
ENV DISPLAY=:99

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    python -m camoufox fetch

COPY src/ src/
COPY config.yaml.example .

VOLUME /app/data

# Start Xvfb + monitor
CMD ["sh", "-c", "Xvfb :99 -screen 0 1920x1080x24 &>/dev/null & python -m src.main /app/data/config.yaml"]
