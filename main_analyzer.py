import sys
import asyncio
import json
import re
import os
import torch
from datetime import datetime
from PIL import Image
from playwright.async_api import async_playwright
from transformers import CLIPProcessor, CLIPModel

# --- 設定 ---
AUTH_FILE = 'auth.json'
SAVE_DIR = 'downloaded_images'
DB_FILE = 'analysis_db.json'
AI_MODEL_ID = "openai/clip-vit-base-patch32"

# 構図定義
COMPOSITION_LABELS = ["a close-up photo of a face", "a bust-up portrait of a person", "a full-body photo of a person", "a photo of scenery or objects"]
LABEL_MAP = {0: "Face Close-up", 1: "Bust-up", 2: "Full Body", 3: "Scenery/Others"}

# フォルダ準備
os.makedirs(SAVE_DIR, exist_ok=True)

# --- AIモデルの初期化 (グローバル) ---
print("🤖 Loading AI Model...")
device = "cuda" if torch.cuda.is_available() else "cpu"
model = CLIPModel.from_pretrained(AI_MODEL_ID).to(device)
processor = CLIPProcessor.from_pretrained(AI_MODEL_ID)

def extract_number(text):
    if not text: return 0
    clean = text.replace(',', '').strip()
    mul = 1
    if 'K' in clean.upper() and 'LIKES' not in clean.upper(): mul = 1000
    elif 'M' in clean.upper(): mul = 1000000
    match = re.search(r'(\d+(?:\.\d+)?)', clean)
    return int(float(match.group(1)) * mul) if match else 0

async def run_analysis(tweet_url):
    tweet_id = tweet_url.split('/')[-1].split('?')[0]
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state=AUTH_FILE if os.path.exists(AUTH_FILE) else None,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            print(f"📡 Fetching data from X...")
            await page.goto(tweet_url, wait_until="domcontentloaded")
            await asyncio.sleep(4)

            # 1. メトリクス取得
            data = {'likes': 0, 'reposts': 0, 'bookmarks': 0, 'views': 0}
            for key, tid in [('likes', 'like'), ('reposts', 'retweet'), ('bookmarks', 'bookmark')]:
                btn = await page.query_selector(f'[data-testid="{tid}"]') or await page.query_selector(f'[data-testid="un{tid}"]') or await page.query_selector(f'[data-testid="remove{tid}"]')
                if btn: data[key] = extract_number(await btn.get_attribute("aria-label"))
            
            view_link = await page.query_selector('a[href*="/analytics"]')
            if view_link: data['views'] = extract_number(await view_link.inner_text())

            # 2. 画像ダウンロード & AI解析
            image_results = []
            photo_container = await page.query_selector('[data-testid="tweetPhoto"]')
            if photo_container:
                images = await photo_container.query_selector_all('img')
                for i, img in enumerate(images):
                    src = await img.get_attribute('src')
                    if src and 'pbs.twimg.com/media' in src:
                        high_res = f"{src.split('?')[0]}?format=jpg&name=orig"
                        img_path = os.path.join(SAVE_DIR, f"{tweet_id}_{i+1}.jpg")
                        
                        # ダウンロード
                        img_page = await context.new_page()
                        resp = await img_page.goto(high_res)
                        if resp:
                            with open(img_path, "wb") as f: f.write(await resp.body())
                            
                            # AI解析
                            pil_img = Image.open(img_path)
                            inputs = processor(text=COMPOSITION_LABELS, images=pil_img, return_tensors="pt", padding=True).to(device)
                            with torch.no_grad():
                                outputs = model(**inputs)
                            scores = outputs.logits_per_image.softmax(dim=1).tolist()[0]
                            top_idx = scores.index(max(scores))
                            
                            image_results.append({
                                "path": img_path,
                                "url": high_res,
                                "composition": LABEL_MAP[top_idx],
                                "confidence": round(max(scores) * 100, 1)
                            })
                        await img_page.close()

            # 3. データの統合
            final_result = {
                "tweet_id": tweet_id,
                "url": tweet_url,
                "timestamp": datetime.now().isoformat(),
                "metrics": data,
                "images": image_results,
                "engagement_rate": round((data['likes']/data['views']*100), 2) if data['views'] > 0 else 0
            }

            # 4. JSON DBを更新
            db = []
            if os.path.exists(DB_FILE):
                with open(DB_FILE, 'r', encoding='utf-8') as f: db = json.load(f)
            
            # 重複チェック（同じIDがあれば更新）
            db = [entry for entry in db if entry['tweet_id'] != tweet_id]
            db.append(final_result)
            
            with open(DB_FILE, 'w', encoding='utf-8') as f:
                json.dump(db, f, ensure_ascii=False, indent=2)

            print(f"\n✅ Analysis Complete for {tweet_id}!")
            print(f"📊 Likes: {data['likes']} | Composition: {image_results[0]['composition'] if image_results else 'N/A'}")

        finally:
            await browser.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        asyncio.run(run_analysis(sys.argv[1]))
    else:
        print("Usage: python main_analyzer.py <TWEET_URL>")