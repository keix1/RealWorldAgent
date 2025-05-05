FROM python:3.10-slim

# システムパッケージのインストール（最小限）
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 作業ディレクトリの設定
WORKDIR /app

# 必要なPythonパッケージのインストール
COPY requirements.app.txt .
RUN pip3 install --no-cache-dir -r requirements.app.txt

# アプリケーションコードのコピー
COPY . .

# 画像保存ディレクトリの作成と権限設定
RUN mkdir -p static/images && \
    chmod -R 777 static/images

# ポートの公開
EXPOSE 8443

# アプリケーションの起動
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8443", "--ssl-keyfile", "/app/certs/key.pem", "--ssl-certfile", "/app/certs/cert.pem"] 