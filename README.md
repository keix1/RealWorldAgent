# リアルタイムカメラ映像分析チャットボット

このプロジェクトは、OpenCVを使用してカメラ映像を取得し、OllamaでホスティングされたGemma3:4b-it-qatモデルを使用してリアルタイムで映像を分析するチャットボットです。

## 必要条件

- Docker
- Docker Compose
- カメラデバイス（/dev/video0）

## セットアップ

### 1. Ollamaの起動（初回のみ）

```bash
# Ollamaコンテナを起動
docker compose -f docker-compose.ollama.yml up -d

# モデルのダウンロード（初回のみ）
docker exec -it $(docker ps --format "{{.Names}}" | grep ollama) ollama pull gemma3:4b-it-qat
```

### 2. アプリケーションの起動

```bash
# アプリケーションを起動
docker compose up --build
```

## 使用方法

1. アプリケーションが起動したら、WebSocketクライアントを使用して`ws://localhost:8000/ws`に接続します。
2. 接続後、カメラ映像がリアルタイムで取得され、LLMによる分析結果が返されます。

## 注意事項

- カメラデバイスが正しく認識されていることを確認してください。
- 十分なGPUメモリが必要です（Gemma3:4b-it-qatモデルの実行に必要）。
- 初回起動時は、Gemma3:4b-it-qatモデルのダウンロードに時間がかかる場合があります。

## コンテナ管理

### Ollamaコンテナの管理

```bash
# Ollamaコンテナの起動
docker compose -f docker-compose.ollama.yml up -d

# Ollamaコンテナの停止
docker compose -f docker-compose.ollama.yml down

# Ollamaコンテナのログ確認
docker compose -f docker-compose.ollama.yml logs -f
```

### アプリケーションコンテナの管理

```bash
# アプリケーションの起動
docker compose up -d

# アプリケーションの停止
docker compose down

# アプリケーションのログ確認
docker compose logs -f
``` 