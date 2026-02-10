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
# Webアプリで表示するために static フォルダに保存します
SAVE_DIR = 'static/images'
DB_FILE = 'analysis_db.json'
AI_MODEL_ID = "openai/clip-vit-base-patch32"

# フォルダ準備
os.makedirs(SAVE_DIR, exist_ok=True)

# --- AI判定ラベル定義 ---

# 1. 構図 (Composition)
COMPOSITION_LABELS = [
    "a close-up photo of a face",       # 顔アップ
    "a bust-up portrait of a person",   # バストアップ
    "a full-body photo of a person",    # 全身
    "a photo of scenery or objects"     # 風景・物
]
LABEL_MAP_COMP = {
    0: "Face Close-up",
    1: "Bust-up",
    2: "Full Body",
    3: "Object/Scenery"
}

# 2. シチュエーション (Situation) ★追加機能
SITUATION_LABELS = [
    "a photo taken in a professional photo studio with lighting", # スタジオ
    "a photo taken at an outdoor cosplay event or street",        # 屋外・イベント
    "a mirror selfie taken with a smartphone",                    # 自撮り
    "a photo taken in a bedroom or home environment"              # 家・部屋
]
LABEL_MAP_SIT = {
    0: "Studio",
    1: "Outdoor/Event",
    2: "Selfie",
    3: "Home/Room"
}

# --- AIモデルの初期化 (グローバル) ---
print("🤖 Loading AI Model...")
device = "cuda" if torch.cuda.is_available() else "cpu"
model = CLIPModel.from_pretrained(AI_MODEL_ID).to(device)
processor = CLIPProcessor.from_pretrained(AI_MODEL_ID)

def extract_number(text):
    """ 数値抽出ロジック（Bookmarksの'k'誤爆防止版） """
    if not text: return 0
    clean = text.replace(',', '').strip()
    mul = 1
    
    upper_text = clean.upper()
    if 'K' in upper_text:
        # "BOOKMARK" や "WORK" など単語の一部としてのKを除外
        if 'BOOKMARK' not in upper_text and 'LIKES' not in upper_text:
            mul = 1000
    elif 'M' in upper_text:
        if 'IMAGE' not in upper_text:
            mul = 1000000

    match = re.search(r'(\d+(?:\.\d+)?)', clean)
    return int(float(match.group(1)) * mul) if match else 0

async def run_analysis(tweet_url):
    tweet_id = tweet_url.split('/')[-1].split('?')[0]
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # 解析精度向上のため英語ロケールでアクセス
        context = await browser.new_context(
            storage_state=AUTH_FILE if os.path.exists(AUTH_FILE) else None,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="en-US"
        )
        page = await context.new_page()

        try:
            print(f"📡 Fetching data from X: {tweet_url}")
            await page.goto(tweet_url, wait_until="domcontentloaded")
            await asyncio.sleep(4)

            # --- 1. メトリクス取得 ---
            data = {'likes': 0, 'reposts': 0, 'bookmarks': 0, 'views': 0}
            
            # ボタンから数値取得
            targets = [
                ('likes', ['like', 'unlike']),
                ('reposts', ['retweet', 'unretweet']),
                ('bookmarks', ['bookmark', 'removeBookmark'])
            ]
            for key, ids in targets:
                for tid in ids:
                    btn = await page.query_selector(f'[data-testid="{tid}"]')
                    if btn:
                        label = await btn.get_attribute("aria-label")
                        val = extract_number(label)
                        if val > 0:
                            data[key] = val
                            break
            
            # Views取得
            view_link = await page.query_selector('a[href*="/analytics"]')
            if view_link:
                label = await view_link.get_attribute("aria-label") or await view_link.inner_text()
                data['views'] = extract_number(label)

            # --- 2. 画像ダウンロード & ダブルAI解析 ---
            image_results = []
            photo_container = await page.query_selector('[data-testid="tweetPhoto"]')
            
            if photo_container:
                images = await photo_container.query_selector_all('img')
                processed_urls = set()
                
                for i, img in enumerate(images):
                    src = await img.get_attribute('src')
                    if src and 'pbs.twimg.com/media' in src:
                        # 高画質URL生成
                        base_url = src.split('?')[0]
                        fmt = 'png' if 'format=png' in src else 'jpg'
                        high_res = f"{base_url}?format={fmt}&name=orig"
                        
                        if high_res in processed_urls: continue
                        processed_urls.add(high_res)

                        img_path = os.path.join(SAVE_DIR, f"{tweet_id}_{len(image_results)+1}.jpg")
                        
                        # 画像保存
                        img_page = await context.new_page()
                        try:
                            resp = await img_page.goto(high_res)
                            if resp:
                                body = await resp.body()
                                with open(img_path, "wb") as f: f.write(body)
                                
                                # === AI解析スタート ===
                                try:
                                    pil_img = Image.open(img_path)
                                    
                                    # 解析A: 構図 (Composition)
                                    inputs_comp = processor(text=COMPOSITION_LABELS, images=pil_img, return_tensors="pt", padding=True).to(device)
                                    with torch.no_grad():
                                        outputs_comp = model(**inputs_comp)
                                    probs_comp = outputs_comp.logits_per_image.softmax(dim=1).tolist()[0]
                                    top_comp_idx = probs_comp.index(max(probs_comp))
                                    
                                    # 解析B: シチュエーション (Situation) ★ここが追加
                                    inputs_sit = processor(text=SITUATION_LABELS, images=pil_img, return_tensors="pt", padding=True).to(device)
                                    with torch.no_grad():
                                        outputs_sit = model(**inputs_sit)
                                    probs_sit = outputs_sit.logits_per_image.softmax(dim=1).tolist()[0]
                                    top_sit_idx = probs_sit.index(max(probs_sit))

                                    image_results.append({
                                        "path": img_path,
                                        "url": high_res,
                                        "composition": LABEL_MAP_COMP[top_comp_idx], # 構図結果
                                        "situation": LABEL_MAP_SIT[top_sit_idx],     # シチュエーション結果
                                        "confidence": round(max(probs_comp) * 100, 1)
                                    })
                                except Exception as ai_e:
                                    print(f"⚠️ AI Analysis Failed: {ai_e}")
                        finally:
                            await img_page.close()

            # --- 3. データの統合 ---
            final_result = {
                "tweet_id": tweet_id,
                "url": tweet_url,
                "timestamp": datetime.now().isoformat(),
                "metrics": data,
                "images": image_results,
                "engagement_rate": round((data['likes']/data['views']*100), 2) if data['views'] > 0 else 0,
                "save_rate": round((data['bookmarks']/data['likes']*100), 2) if data['likes'] > 0 else 0
            }

            # 4. JSON DB更新
            db = []
            if os.path.exists(DB_FILE):
                try:
                    with open(DB_FILE, 'r', encoding='utf-8') as f: db = json.load(f)
                except: db = []
            
            # 重複削除して追加
            db = [entry for entry in db if entry['tweet_id'] != tweet_id]
            db.append(final_result)
            
            with open(DB_FILE, 'w', encoding='utf-8') as f:
                json.dump(db, f, ensure_ascii=False, indent=2)

            print(f"\n✅ Analysis Complete!")
            print(f"📊 Save Rate: {final_result['save_rate']}%")
            if image_results:
                print(f"🖼️ AI Tags: {image_results[0]['composition']} / {image_results[0]['situation']}")

        except Exception as e:
            print(f"❌ Critical Error: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        asyncio.run(run_analysis(sys.argv[1]))
    else:
        # テスト用
        asyncio.run(run_analysis("https://x.com/snow_sayu_/status/1867910835085148236"))