FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# OS 依存ライブラリ（Pillow用）＋汎用フォント
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libjpeg62-turbo \
    zlib1g \
    libtiff6 \
    libfreetype6 \
    libwebp7 \
    libopenjp2-7 \
    fonts-dejavu \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依存インストール（rootのまま）
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# アプリ本体
COPY . .

# static フォールバック
RUN mkdir -p /app/static && \
    if [ -f /app/index.html ] && [ ! -f /app/static/index.html ]; then \
        cp /app/index.html /app/static/; \
    fi

# 非rootユーザーは "あとから" 切り替える（権限を付与）
RUN useradd --create-home --shell /bin/bash app && \
    chown -R app:app /app
USER app

# Cloud Run 用
ENV PORT=8080
EXPOSE 8080

# HealthcheckはDockerとしては任意（Cloud Runは独自判定）
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8080/api/health || exit 1

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
