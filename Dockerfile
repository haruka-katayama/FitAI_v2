# 1) 軽量なPythonベース
FROM python:3.11-slim

# 2) 依存インストールに必要なパッケージ
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && rm -rf /var/lib/apt/lists/*

# 3) 作業ディレクトリ
WORKDIR /app

# 4) 依存を先に入れてキャッシュ活用
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5) アプリ本体
COPY . .

# 6) Cloud Run が割り当てるポートで起動（$PORT必須）
#    StreamlitのCORS/XSRFをCloud Run向けに抑制
ENV PORT=8080 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ENABLECORS=false \
    STREAMLIT_SERVER_ENABLEXsrfProtection=false

EXPOSE 8080
CMD ["bash", "-lc", "streamlit run streamlit_app.py --server.port $PORT --server.address 0.0.0.0"]