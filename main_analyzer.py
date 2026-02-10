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

# フォルダ作成
os.makedirs(SAVE_DIR, exist_ok=True)

# --- 1. 構図 (Composition) ---
COMPOSITION_DEFINITIONS = {
    "Face Close-up": ["close-up of a face", "face shot", "portrait focusing on face"],
    "Bust-up": ["upper body portrait", "bust-up shot", "waist up photo"],
    "Full Body": ["full body shot", "whole body showing shoes", "standing pose"],
    "Object/Scenery": ["no humans", "scenery only", "objects only"]
}

# --- 🤖 AIモデル初期化 ---
print("🤖 Loading AI Model...")
device = "cuda" if torch.cuda.is_available() else "cpu"
model = CLIPModel.from_pretrained(AI_MODEL_ID).to(device)
processor = CLIPProcessor.from_pretrained(AI_MODEL_ID)

def extract_number(text):
    """ 数値抽出ロジック（M/K誤爆防止版） """
    if not text: return 0
    clean = text.replace(',', '').strip()
    upper = clean.upper()
    mul = 1
    if 'K' in upper:
        if 'BOOKMARK' not in upper and 'LIKES' not in upper: mul = 1000
    elif 'M' in upper:
        if 'BOOKMARK' not in upper and 'IMAGE' not in upper and 'COMMENT' not in upper: mul = 1000000
    match = re.search(r'(\d+(?:\.\d+)?)', clean)
    return int(float(match.group(1)) * mul) if match else 0

def analyze_skin_ratio(img_path):
    """ ★肌色ピクセル率を計算する (0.0 - 100.0) """
    try:
        img = cv2.imread(img_path)
        if img is None: return 0.0
        
        # HSV色空間に変換
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        
        # 肌色の範囲定義 (一般的な肌色)
        lower_skin = np.array([0, 20, 70], dtype=np.uint8)
        upper_skin = np.array([20, 255, 255], dtype=np.uint8)
        
        # 肌色マスクを作成
        mask = cv2.inRange(hsv, lower_skin, upper_skin)
        
        # 肌色ピクセル数をカウント
        skin_pixels = cv2.countNonZero(mask)
        total_pixels = img.shape[0] * img.shape[1]
        
        return round((skin_pixels / total_pixels) * 100, 2)
    except Exception as e:
        print(f"⚠️ Skin analysis failed: {e}")
        return 0.0

def analyze_color_and_brightness(img_path):
    """ 画像の主要色と明るさを解析する """
    try:
        img = Image.open(img_path).convert("RGB")
        gray_img = img.convert("L")
        brightness_val = gray_img.resize((1, 1)).getpixel((0, 0))
        brightness_tag = "Normal"
        if brightness_val > 170: brightness_tag = "Bright"
        elif brightness_val < 85: brightness_tag = "Dark"
        img_small = img.resize((150, 150))
        result = img_small.quantize(colors=5, method=2)
        dominant_color = result.getpalette()[:3]
        hex_color = '#{:02x}{:02x}{:02x}'.format(*dominant_color)
        return hex_color, brightness_tag
    except:
        return "#000000", "Unknown"

def predict_composition(pil_img):
    """ 構図判定 (CLIP) """
    labels = []
    flattened_prompts = []
    for label, prompts in COMPOSITION_DEFINITIONS.items():
        for p in prompts:
            labels.append(label)
            flattened_prompts.append(f"a photo of {p}")

    inputs = processor(text=flattened_prompts, images=pil_img, return_tensors="pt", padding=True).to(device)
    with torch.no_grad():
        outputs = model(**inputs)
    
    logits = outputs.logits_per_image.softmax(dim=1)[0]
    scores = {key: [] for key in COMPOSITION_DEFINITIONS.keys()}
    for i, score in enumerate(logits):
        scores[labels[i]].append(score.item())
    
    avg_scores = {k: sum(v)/len(v) for k, v in scores.items()}
    best = max(avg_scores, key=avg_scores.get)
    return best, round(avg_scores[best] * 100, 1)

def get_tweet_time(tweet_id):
    """ ★Tweet IDから投稿日時を逆算 (Snowflake) """
    try:
        # Twitter Epoch (1288834974657) を加算
        t_ms = (int(tweet_id) >> 22) + 1288834974657
        return datetime.fromtimestamp(t_ms / 1000.0).isoformat()
    except:
        return None

def normalize_url(url):
    """ URL正規化 """
    match = re.search(r'(https?://(?:x|twitter)\.com/[a-zA-Z0-9_]+/status/\d+)', url)
    if match:
        return match.group(1)
    return url.split('?')[0]

async def run_analysis(raw_url):
    tweet_url = normalize_url(raw_url)
    tweet_id = tweet_url.split('/')[-1]
    
    # --- スキップ機能 (肌色データがない場合も再処理) ---
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                db = json.load(f)
                entry = next((e for e in db if e.get('tweet_id') == tweet_id), None)
                
                # エントリが存在し、かつ画像があり、かつ肌色データ(skin_ratio)も持っている場合のみスキップ
                if entry:
                    # 画像がないデータ(失敗データ)は再取得させるためスキップしない
                    if not entry.get('images'): 
                        pass 
                    # 肌色データ取得済みの場合はスキップ
                    elif 'images' in entry and len(entry['images']) > 0 and 'skin_ratio' in entry['images'][0]:
                        print(f"⏩ Skip: {tweet_id} (Fully analyzed)")
                        return
        except: pass
    
    # BAN対策の待ち時間
    await asyncio.sleep(random.uniform(1, 3))

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state=AUTH_FILE if os.path.exists(AUTH_FILE) else None,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="en-US"
        )
        page = await context.new_page()

        try:
            print(f"📡 Analyzing: {tweet_url}")
            try:
                await page.goto(tweet_url, wait_until="networkidle", timeout=60000)
                await asyncio.sleep(5)
            except Exception as e:
                print(f"⚠️ Load Warning: {e}")

            # --- メトリクス取得 (完全版) ---
            data = {'likes': 0, 'reposts': 0, 'bookmarks': 0, 'views': 0}
            
            # 各ボタンのaria-labelから数値を取得
            targets = [
                ('likes', ['like', 'unlike']), 
                ('reposts', ['retweet', 'unretweet']), 
                ('bookmarks', ['bookmark', 'removeBookmark'])
            ]
            
            for key, ids in targets:
                for tid in ids:
                    btn = await page.query_selector(f'[data-testid="{tid}"]')
                    if btn:
                        aria_label = await btn.get_attribute("aria-label")
                        val = extract_number(aria_label)
                        if val > 0: 
                            data[key] = val
                            break
            
            # インプレッション数
            view_link = await page.query_selector('a[href*="/analytics"]')
            if view_link: 
                aria_label = await view_link.get_attribute("aria-label")
                inner_text = await view_link.inner_text()
                data['views'] = extract_number(aria_label or inner_text)

            # --- 画像処理 & 解析 ---
            image_results = []
            photo_container = await page.query_selector('[data-testid="tweetPhoto"]')
            
            if photo_container:
                images = await photo_container.query_selector_all('img')
                processed_urls = set()
                
                for i, img in enumerate(images):
                    src = await img.get_attribute('src')
                    if src and 'pbs.twimg.com/media' in src:
                        base_url = src.split('?')[0]
                        fmt = 'png' if 'format=png' in src else 'jpg'
                        high_res = f"{base_url}?format={fmt}&name=orig"
                        
                        if high_res in processed_urls: continue
                        processed_urls.add(high_res)

                        img_path = os.path.join(SAVE_DIR, f"{tweet_id}_{len(image_results)+1}.jpg")
                        
                        img_page = await context.new_page()
                        try:
                            resp = await img_page.goto(high_res)
                            if resp:
                                with open(img_path, "wb") as f: f.write(await resp.body())
                                
                                # === AI解析 ===
                                pil_img = Image.open(img_path)
                                
                                # 1. 構図
                                comp_cat, comp_conf = predict_composition(pil_img)
                                # 2. 色・明るさ
                                hex_color, brightness = analyze_color_and_brightness(img_path)
                                # 3. ★肌色率
                                skin_ratio = analyze_skin_ratio(img_path)

                                image_results.append({
                                    "path": img_path,
                                    "url": high_res,
                                    "composition": comp_cat,
                                    "confidence": comp_conf,
                                    "color": hex_color,
                                    "brightness": brightness,
                                    "skin_ratio": skin_ratio # ★追加
                                })
                        finally:
                            await img_page.close()

            # 失敗判定: 画像なし & いいね0 は保存しない
            if not image_results and data['likes'] == 0:
                print(f"⚠️ Analysis Failed (No Data) for {tweet_id}. Skipping Save.")
                return 

            # 保存データ構築
            final_result = {
                "tweet_id": tweet_id,
                "url": tweet_url,
                "timestamp": datetime.now().isoformat(),
                "created_at": get_tweet_time(tweet_id), # ★追加: 投稿日時
                "metrics": data,
                "images": image_results,
                "engagement_rate": round((data['likes']/data['views']*100), 2) if data['views'] > 0 else 0,
                "save_rate": round((data['bookmarks']/data['likes']*100), 2) if data['likes'] > 0 else 0
            }

            # DB保存
            db = []
            if os.path.exists(DB_FILE):
                try: 
                    with open(DB_FILE, 'r', encoding='utf-8') as f: 
                        db = json.load(f)
                except: db = []
            
            # 重複排除して追記
            db = [entry for entry in db if entry['tweet_id'] != tweet_id]
            db.append(final_result)
            
            with open(DB_FILE, 'w', encoding='utf-8') as f:
                json.dump(db, f, ensure_ascii=False, indent=2)

            print(f"\n✅ Complete: {tweet_id} | Skin: {image_results[0]['skin_ratio'] if image_results else 0}%")

        except Exception as e:
            print(f"❌ Error: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        asyncio.run(run_analysis(sys.argv[1]))
    else:
        # テスト用URL
        asyncio.run(run_analysis("https://x.com/snow_sayu_/status/1867910835085148236"))