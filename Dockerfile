FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Pillow が利用する OS 依存ライブラリ（ランタイム）＋フォント
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

# 非rootユーザー作成（COPY前に作って chown コピーで権限最適化）
RUN useradd --create-home --shell /bin/bash app
USER app
WORKDIR /app

# 依存インストール
COPY --chown=app:app requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# アプリ本体
COPY --chown=app:app . .

# static ディレクトリと index.html のフォールバック
RUN mkdir -p /app/static && \
    if [ -f /app/index.html ] && [ ! -f /app/static/index.html ]; then \
        cp /app/index.html /app/static/; \
    fi

ENV PORT=8080
EXPOSE ${PORT}

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:${PORT}/api/health || exit 1

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
