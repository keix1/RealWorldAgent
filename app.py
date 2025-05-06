import cv2
import numpy as np
import base64
import requests
from fastapi import FastAPI, WebSocket, Request, WebSocketDisconnect
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
REASON_DIR = "static/reasons"
RATE_DIR = "static/rates"
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

def save_base64_image(base64_data: str, request_host: str = None) -> str:
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
        
        # 絶対URLを生成（リクエストのホストを使用）
        host_url = request_host if request_host else APP_HOST
        image_url = f"{host_url}/static/images/{filename}"
        logger.info(f"画像を保存しました: {image_url}")
        return image_url
    except Exception as e:
        logger.error(f"画像の保存中にエラーが発生しました: {str(e)}")
        raise

@app.get("/api/images")
async def get_images(request: Request):
    """既存の画像一覧を取得するエンドポイント"""
    try:
        if not os.path.exists(IMAGE_DIR):
            return {"images": []}
        
        # リクエストからホストURLを取得
        host_url = f"{request.url.scheme}://{request.url.netloc}"
        
        images = []
        for filename in os.listdir(IMAGE_DIR):
            if filename.endswith(('.jpg', '.jpeg', '.png')):
                image_url = f"{host_url}/static/images/{filename}"
                # 画像の作成日時を取得（ファイル名から抽出）
                date_str = filename.split('_')[0]
                try:
                    date = datetime.strptime(date_str, "%Y%m%d").strftime("%Y年%m月%d日")
                except:
                    date = "不明"
                
                # 同名のテキストファイルから評価情報を読み出す
                timestamp = filename.replace(".jpg", "")
                
                # 評価値を読み込む
                rate = "1"
                rate_path = os.path.join(RATE_DIR, f"{timestamp}.txt")
                if os.path.exists(rate_path):
                    with open(rate_path, "r", encoding="utf-8") as f:
                        rate = f.read().strip()
                
                # 評価理由を読み込む
                reason = "理由なし"
                reason_path = os.path.join(REASON_DIR, f"{timestamp}.txt")
                if os.path.exists(reason_path):
                    with open(reason_path, "r", encoding="utf-8") as f:
                        reason = f.read().strip()
                
                images.append({
                    "url": image_url,
                    "date": date,
                    "filename": filename,
                    "rate": int(rate),  # 数値として返す
                    "reason": reason
                })
        
        # 新しい画像順にソート
        images.sort(key=lambda x: x["filename"], reverse=True)
        return {"images": images}
    except Exception as e:
        logger.error(f"画像一覧の取得中にエラーが発生しました: {str(e)}")
        return {"images": [], "error": str(e)}

@app.get("/", response_class=HTMLResponse)
async def get_home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket接続が確立されました")
    
    while True:
        try:
            # クライアントからのメッセージを受信
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if "image" in message:
                # Base64データを取得
                base64_data = message["image"]
                
                # APIにリクエストを送信
                prompt = """この写真を以下の基準で5段階評価してください：
1. 笑顔の自然さ（1-5点）
2. 構図の良さ（1-5点）
3. プロフィール写真としての適切さ（1-5点）

各項目について具体的な理由を述べてください。
最終的な総合評価（1-5点）と、その理由も含めて教えてください。

評価結果は以下の形式で返してください：
{
  "good_picture": true/false,
  "rate": 1-5,
  "reason": "具体的な評価理由"
}"""

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
                
                # ストリーミングで応答を出力
                response_text = ""
                async for chunk in chat.astream([message]):
                    response_text += chunk.content
                    try:
                        await websocket.send_json({
                            "type": "stream",
                            "content": chunk.content
                        })
                    except Exception as e:
                        logger.error(f"ストリーミング送信中にエラー: {str(e)}")
                        break
                
                # 応答をJSONとして解析
                try:
                    # 応答テキストからJSON部分を抽出
                    json_start = response_text.find('{')
                    json_end = response_text.rfind('}') + 1
                    if json_start >= 0 and json_end > json_start:
                        json_str = response_text[json_start:json_end]
                        response_json = json.loads(json_str)
                        
                        # 評価結果の検証
                        if not isinstance(response_json, dict):
                            logger.error("APIからの応答が不正な形式です")
                            raise ValueError("APIからの応答が不正な形式です")
                        
                        good_picture = response_json.get("good_picture", False)
                        rate = response_json.get("rate", 1)
                        reason = response_json.get("reason", "理由なし")
                        
                        # 評価値の検証
                        if not isinstance(good_picture, bool):
                            logger.error(f"good_pictureの値が不正です: {good_picture}")
                            raise ValueError(f"good_pictureの値が不正です: {good_picture}")
                        
                        if not isinstance(rate, int) or rate < 1 or rate > 5:
                            logger.error(f"rateの値が不正です: {rate}")
                            raise ValueError(f"rateの値が不正です: {rate}")
                        
                        if not isinstance(reason, str):
                            logger.error(f"reasonの値が不正です: {reason}")
                            raise ValueError(f"reasonの値が不正です: {reason}")
                        
                        if good_picture:
                            # 良い写真の場合のみ保存
                            # メッセージからホストURLを取得
                            # WebSocketメッセージはdict型であることを確認
                            if isinstance(message, dict):
                                host_url = message.get("host", APP_HOST)
                            else:
                                host_url = APP_HOST
                            
                            # ファイル名の形式: YYYYMMDD_HHMMSS.jpg
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            filename = f"{timestamp}.jpg"
                            
                            # 画像を保存
                            image_path = os.path.join(IMAGE_DIR, filename)
                            with open(image_path, "wb") as f:
                                f.write(base64.b64decode(base64_data))
                            
                            # 理由をテキストファイルとして保存
                            reason_filename = os.path.join(REASON_DIR, f"{timestamp}.txt")
                            os.makedirs(os.path.dirname(reason_filename), exist_ok=True)
                            with open(reason_filename, "w", encoding="utf-8") as f:
                                f.write(reason)
                            
                            # 評価値をテキストファイルとして保存
                            rate_filename = os.path.join(RATE_DIR, f"{timestamp}.txt")
                            os.makedirs(os.path.dirname(rate_filename), exist_ok=True)
                            with open(rate_filename, "w", encoding="utf-8") as f:
                                f.write(str(rate))
                            
                            # 画像のURLを生成
                            image_url = f"{host_url}/static/images/{filename}"
                            
                            # 評価結果を送信
                            await websocket.send_json({
                                "type": "evaluation",
                                "content": {
                                    "good_picture": good_picture,
                                    "rate": int(rate),  # 数値として送信
                                    "reason": reason,
                                    "image_url": image_url
                                }
                            })
                        
                    else:
                        logger.error("応答にJSONが見つかりません")
                        await websocket.send_json({
                            "type": "error",
                            "content": "評価結果の解析に失敗しました"
                        })
                        await websocket.send_json({
                            "type": "error",
                            "content": "評価結果の解析に失敗しました"
                        })
                except json.JSONDecodeError as e:
                    logger.error(f"API応答のJSON解析に失敗しました: {str(e)}")
                    await websocket.send_json({
                        "type": "error",
                        "content": "評価結果の解析に失敗しました"
                    })
                
                # ストリーミング完了
                await websocket.send_json({"type": "done"})
                
        except WebSocketDisconnect:
            logger.info("WebSocket接続が切断されました")
            break
        except Exception as e:
            logger.error(f"WebSocket処理中にエラーが発生しました: {str(e)}")
            try:
                await websocket.send_json({
                    "type": "error",
                    "content": "処理中にエラーが発生しました"
                })
            except:
                break

if __name__ == "__main__":
    # 画像保存ディレクトリと理由保存ディレクトリの作成
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(REASON_DIR, exist_ok=True)
    
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
