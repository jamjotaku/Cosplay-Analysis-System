import sys
import asyncio
import json
import re
import os
import torch
import random
import cv2
import numpy as np
from datetime import datetime
from PIL import Image
from playwright.async_api import async_playwright
from transformers import CLIPProcessor, CLIPModel

# --- 設定 ---
AUTH_FILE = 'auth.json'
SAVE_DIR = 'static/images'
DB_FILE = 'analysis_db.json'
AI_MODEL_ID = "openai/clip-vit-base-patch32"

os.makedirs(SAVE_DIR, exist_ok=True)

# 構図定義
COMPOSITION_DEFINITIONS = {
    "Face Close-up": ["close-up of a face", "face shot", "portrait focusing on face"],
    "Bust-up": ["upper body portrait", "bust-up shot", "waist up photo"],
    "Full Body": ["full body shot", "whole body showing shoes", "standing pose"],
    "Object/Scenery": ["no humans", "scenery only", "objects only"]
}

# --- 🤖 AIモデル初期化 ---
print("🤖 Loading AI Model for Composition Analysis...")
device = "cuda" if torch.cuda.is_available() else "cpu"
model = CLIPModel.from_pretrained(AI_MODEL_ID).to(device)
processor = CLIPProcessor.from_pretrained(AI_MODEL_ID)

def extract_tweet_id(url):
    """ URLからID(数字)を確実に抜き出す [cite: 2026-02-12] """
    match = re.search(r'status/(\d+)', url)
    return match.group(1) if match else None

def extract_number(text):
    """ 1.2K などの単位を正確に変換する [cite: 2026-02-11] """
    if not text: return 0
    clean = text.replace(',', '').strip()
    upper = clean.upper()
    mul = 1
    if re.search(r'\dK', upper): mul = 1000
    elif re.search(r'\dM', upper): mul = 1000000
    match = re.search(r'(\d+(?:\.\d+)?)', clean)
    return int(float(match.group(1)) * mul) if match else 0

def analyze_skin_ratio(img_path):
    """ 肌色ピクセル率を計算する """
    try:
        img = cv2.imread(img_path)
        if img is None: return 0.0
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        lower_skin = np.array([0, 20, 70], dtype=np.uint8)
        upper_skin = np.array([20, 255, 255], dtype=np.uint8)
        mask = cv2.inRange(hsv, lower_skin, upper_skin)
        return round((cv2.countNonZero(mask) / (img.shape[0] * img.shape[1])) * 100, 2)
    except: return 0.0

def get_tweet_time(tweet_id):
    """ Tweet IDから投稿日時を逆算 (Snowflake) """
    try:
        t_ms = (int(tweet_id) >> 22) + 1288834974657
        return datetime.fromtimestamp(t_ms / 1000.0).isoformat()
    except: return None

def predict_composition(pil_img):
    """ 構図判定 (CLIP) """
    labels, prompts_list = [], []
    for label, prompts in COMPOSITION_DEFINITIONS.items():
        for p in prompts:
            labels.append(label); prompts_list.append(f"a photo of {p}")
    inputs = processor(text=prompts_list, images=pil_img, return_tensors="pt", padding=True).to(device)
    with torch.no_grad():
        outputs = model(**inputs)
    logits = outputs.logits_per_image.softmax(dim=1)[0]
    scores = {key: [] for key in COMPOSITION_DEFINITIONS.keys()}
    for i, score in enumerate(logits):
        scores[labels[i]].append(score.item())
    avg_scores = {k: sum(v)/len(v) for k, v in scores.items()}
    best = max(avg_scores, key=avg_scores.get)
    return best, round(avg_scores[best] * 100, 1)

async def run_analysis(raw_url):
    tweet_id = extract_tweet_id(raw_url)
    if not tweet_id: return

    tweet_url = f"https://x.com/i/status/{tweet_id}"
    
    # 既存チェック (テキスト未取得なら再解析)
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                db = json.load(f)
                entry = next((e for e in db if e.get('tweet_id') == tweet_id), None)
                if entry and 'tweet_text' in entry and 'skin_ratio' in entry['images'][0]:
                    return
        except: pass

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state=AUTH_FILE if os.path.exists(AUTH_FILE) else None,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            print(f"📡 Analyzing: {tweet_url}")
            await page.goto(tweet_url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(7)

            # ツイート本文取得 [cite: 2026-02-12]
            tweet_text_el = await page.query_selector('[data-testid="tweetText"]')
            tweet_text = await tweet_text_el.inner_text() if tweet_text_el else ""

            # メトリクス取得
            metrics = {'likes': 0, 'reposts': 0, 'bookmarks': 0, 'views': 0}
            targets = [('likes', ['like', 'unlike']), ('reposts', ['retweet', 'unretweet']), ('bookmarks', ['bookmark', 'removeBookmark'])]
            for key, ids in targets:
                for tid in ids:
                    btn = await page.query_selector(f'[data-testid="{tid}"]')
                    if btn:
                        val = extract_number(await btn.get_attribute("aria-label"))
                        metrics[key] = val
                        if val > 0: break
            
            v_link = await page.query_selector('a[href*="/analytics"]')
            if v_link: metrics['views'] = extract_number(await v_link.get_attribute("aria-label") or await v_link.inner_text())

            # 画像 & 肌色分析
            image_results = []
            img_el = await page.query_selector('[data-testid="tweetPhoto"] img')
            if img_el:
                src = await img_el.get_attribute('src')
                if 'media' in src:
                    high_res = src.split('?')[0] + "?format=jpg&name=orig"
                    img_path = os.path.join(SAVE_DIR, f"{tweet_id}.jpg")
                    img_page = await context.new_page()
                    try:
                        resp = await img_page.goto(high_res)
                        if resp:
                            with open(img_path, "wb") as f: f.write(await resp.body())
                            comp, conf = predict_composition(Image.open(img_path))
                            s_ratio = analyze_skin_ratio(img_path)
                            image_results.append({
                                "path": img_path, "composition": comp, "skin_ratio": s_ratio
                            })
                    finally: await img_page.close()

            if not image_results: return

            final_result = {
                "tweet_id": tweet_id, "url": tweet_url, "tweet_text": tweet_text,
                "created_at": get_tweet_time(tweet_id), "timestamp": datetime.now().isoformat(),
                "metrics": metrics, "images": image_results,
                "engagement_rate": round((metrics['likes']/metrics['views']*100), 2) if metrics['views'] > 0 else 0,
                "save_rate": round((metrics['bookmarks']/metrics['likes']*100), 2) if metrics['likes'] > 0 else 0
            }

            db = load_data_from_file()
            db = [e for e in db if e.get('tweet_id') != tweet_id]
            db.append(final_result)
            with open(DB_FILE, 'w', encoding='utf-8') as f: json.dump(db, f, ensure_ascii=False, indent=2)
            print(f"✅ Complete: {tweet_id} | Likes: {metrics['likes']}")

        except Exception as e: print(f"❌ Error: {e}")
        finally: await browser.close()

def load_data_from_file():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            try: return json.load(f)
            except: return []
    return []

if __name__ == "__main__":
    if len(sys.argv) > 1: asyncio.run(run_analysis(sys.argv[1]))