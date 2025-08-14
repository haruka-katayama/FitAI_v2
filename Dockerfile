# 軽量な公式Pythonイメージ
FROM python:3.11-slim

# 速度&ログ設定
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 必要なシステムパッケージをインストール
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 作業ディレクトリ設定
WORKDIR /app

# 依存関係ファイルをコピーしてインストール
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# アプリケーションコードをコピー
COPY . .

# staticディレクトリとindex.htmlがない場合の対応
RUN mkdir -p /app/static && \
    if [ -f /app/index.html ] && [ ! -f /app/static/index.html ]; then \
        cp /app/index.html /app/static/; \
    fi

# ポート設定（Cloud Runが$PORTを渡すのでそれを使用）
ENV PORT=8080
EXPOSE ${PORT}

# ヘルスチェック（改善版）
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/api/health || exit 1

# 非rootユーザーでの実行（セキュリティ向上）
RUN useradd --create-home --shell /bin/bash app && \
    chown -R app:app /app
USER app

# アプリケーション起動
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
