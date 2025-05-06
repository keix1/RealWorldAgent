import cv2
import numpy as np
import base64
import requests
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
import os
from typing import Optional
import logging
import json
import asyncio
import uuid
from datetime import datetime
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from fastapi.middleware.cors import CORSMiddleware
import ssl
import httpx
import websockets

# ロギングの設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# CORSの設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静的ファイルとテンプレートの設定
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

IMAGE_DIR = "static/images"
APP_HOST = os.getenv("APP_HOST", "https://localhost:8443")  # HTTPSを使用

# SSL設定
SSL_CERT_PATH = os.getenv("SSL_CERT_PATH", "certs/cert.pem")
SSL_KEY_PATH = os.getenv("SSL_KEY_PATH", "certs/key.pem")

# OpenAI互換APIの設定
API_BASE = os.getenv("API_BASE", "http://localhost:11434/v1")
API_KEY = os.getenv("API_KEY", "sk-not-needed")  # ダミーAPIキー
API_URL = f"{API_BASE}/chat/completions"  # エンドポイントを追加

# LangChainの設定
chat = ChatOpenAI(
    model="gemma3:4b",
    openai_api_base=API_BASE,
    openai_api_key=API_KEY,
    streaming=True,
)

# SSLコンテキストの設定
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# HTTPクライアントの設定
http_client = httpx.AsyncClient(
    verify=False,
    timeout=120.0,  # タイムアウトを120秒に延長
    base_url=API_BASE,
    limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
    transport=httpx.HTTPTransport(retries=3)
)

async def check_api_connection():
    """APIサーバーへの接続を確認する"""
    try:
        async with httpx.AsyncClient(verify=False, timeout=5.0) as client:
            response = await client.get(f"{API_BASE}/models")
            if response.status_code == 200:
                logger.info("APIサーバーに接続できました")
                return True
            else:
                logger.error(f"APIサーバーへの接続に失敗しました: {response.status_code}")
                return False
    except Exception as e:
        logger.error(f"APIサーバーへの接続確認中にエラーが発生しました: {str(e)}")
        return False

@app.on_event("startup")
async def startup_event():
    """アプリケーション起動時の処理"""
    if not await check_api_connection():
        logger.error("APIサーバーに接続できません。APIサーバーが起動しているか確認してください。")

def save_base64_image(base64_data: str) -> str:
    """Base64エンコードされた画像データをデコードして保存し、URLを返す"""
    try:
        # Base64データからヘッダーを除去
        if "," in base64_data:
            base64_data = base64_data.split(",")[1]
        
        # Base64データをデコード
        image_data = base64.b64decode(base64_data)
        
        # 画像を保存
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{uuid.uuid4().hex[:8]}.jpg"
        filepath = os.path.join(IMAGE_DIR, filename)
        
        with open(filepath, "wb") as f:
            f.write(image_data)
        
        # 絶対URLを生成
        image_url = f"{APP_HOST}/static/images/{filename}"
        logger.info(f"画像を保存しました: {image_url}")
        return image_url
    except Exception as e:
        logger.error(f"画像の保存中にエラーが発生しました: {str(e)}")
        raise

@app.get("/", response_class=HTMLResponse)
async def get_home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket接続が確立されました")
    
    while True:
        # クライアントからのメッセージを受信
        data = await websocket.receive_text()
        message = json.loads(data)
        
        if "image" in message:
            # Base64データを取得
            base64_data = message["image"]
            
            # APIにリクエストを送信
            prompt = f"""リアクションしてください"""

            # メッセージ送信
            message = HumanMessage(
                content=[
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_data}"},
                    },
                ],
            )

            logger.info("APIにリクエストを送信します")
            logger.info(f"プロンプト: {prompt}")
            
                # ストリーミングで応答を出力
            async for chunk in chat.astream([message]):
                await websocket.send_text(chunk.content)
                await websocket.send_json({
                    "type": "stream",
                    "content": chunk.content
                })
                            # ストリーミング完了
            await websocket.send_json({"type": "done"})

if __name__ == "__main__":
    # 画像保存ディレクトリの作成
    os.makedirs(IMAGE_DIR, exist_ok=True)
    
    # SSL証明書の存在確認
    ssl_keyfile = SSL_KEY_PATH if os.path.exists(SSL_KEY_PATH) else None
    ssl_certfile = SSL_CERT_PATH if os.path.exists(SSL_CERT_PATH) else None
    
    # HTTPSで起動
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8443,
        ssl_keyfile=ssl_keyfile,
        ssl_certfile=ssl_certfile,
        reload=True
    ) 