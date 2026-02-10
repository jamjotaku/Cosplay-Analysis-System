import sys
import asyncio
import json
import re
import os
import torch
import colorsys
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
    """ 数値抽出ロジック（修正版：BOOKMARK内のMによる100万倍誤爆を防止） """
    if not text: return 0
    clean = text.replace(',', '').strip()
    upper = clean.upper()
    
    # そもそもBOOKMARKやLIKESといった単語が入っている場合は、
    # その単語の一部であるKやMに反応させないためのガードを入れる
    
    mul = 1
    
    # K (千) の判定
    if 'K' in upper:
        # BOOKMARK, LIKES, WORK などの単語内のKは無視
        if 'BOOKMARK' not in upper and 'LIKES' not in upper:
            mul = 1000
            
    # M (百万) の判定
    elif 'M' in upper:
        # BOOKMARK, IMAGE, COMMENT などの単語内のMは無視 ★ここを修正！
        if 'BOOKMARK' not in upper and 'IMAGE' not in upper and 'COMMENT' not in upper:
            mul = 1000000

    match = re.search(r'(\d+(?:\.\d+)?)', clean)
    return int(float(match.group(1)) * mul) if match else 0

def analyze_color_and_brightness(img_path):
    """ 画像の主要色と明るさを解析する """
    try:
        img = Image.open(img_path).convert("RGB")
        
        # 1. 輝度 (Brightness) の判定
        gray_img = img.convert("L")
        stat = gray_img.resize((1, 1)).getpixel((0, 0))
        brightness_val = stat
        
        brightness_tag = "Normal"
        if brightness_val > 170: brightness_tag = "Bright"
        elif brightness_val < 85: brightness_tag = "Dark"

        # 2. ドミナントカラー (Dominant Color) の抽出
        img_small = img.resize((150, 150))
        result = img_small.quantize(colors=5, method=2)
        dominant_color = result.getpalette()[:3] # RGB
        
        # HEX変換
        hex_color = '#{:02x}{:02x}{:02x}'.format(*dominant_color)
        
        return hex_color, brightness_tag
        
    except Exception as e:
        print(f"⚠️ Color Analysis Failed: {e}")
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

async def run_analysis(tweet_url):
    tweet_id = tweet_url.split('/')[-1].split('?')[0]
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
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

            # --- メトリクス取得 ---
            data = {'likes': 0, 'reposts': 0, 'bookmarks': 0, 'views': 0}
            targets = [('likes', ['like', 'unlike']), ('reposts', ['retweet', 'unretweet']), ('bookmarks', ['bookmark', 'removeBookmark'])]
            for key, ids in targets:
                for tid in ids:
                    btn = await page.query_selector(f'[data-testid="{tid}"]')
                    if btn:
                        val = extract_number(await btn.get_attribute("aria-label"))
                        if val > 0: data[key] = val; break
            
            view_link = await page.query_selector('a[href*="/analytics"]')
            if view_link: data['views'] = extract_number(await view_link.get_attribute("aria-label") or await view_link.inner_text())

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
                                
                                # === 解析パート ===
                                pil_img = Image.open(img_path)
                                
                                # 1. 構図判定 (AI)
                                comp_cat, comp_conf = predict_composition(pil_img)
                                
                                # 2. 色彩・輝度解析 (計算)
                                hex_color, brightness = analyze_color_and_brightness(img_path)

                                image_results.append({
                                    "path": img_path,
                                    "url": high_res,
                                    "composition": comp_cat,
                                    "confidence": comp_conf,
                                    "color": hex_color,
                                    "brightness": brightness
                                })
                        finally:
                            await img_page.close()

            # --- 保存 ---
            final_result = {
                "tweet_id": tweet_id,
                "url": tweet_url,
                "timestamp": datetime.now().isoformat(),
                "metrics": data,
                "images": image_results,
                "engagement_rate": round((data['likes']/data['views']*100), 2) if data['views'] > 0 else 0,
                "save_rate": round((data['bookmarks']/data['likes']*100), 2) if data['likes'] > 0 else 0
            }

            db = []
            if os.path.exists(DB_FILE):
                try:
                    with open(DB_FILE, 'r', encoding='utf-8') as f:
                        db = json.load(f)
                except:
                    db = []
            
            db = [entry for entry in db if entry['tweet_id'] != tweet_id]
            db.append(final_result)
            
            with open(DB_FILE, 'w', encoding='utf-8') as f:
                json.dump(db, f, ensure_ascii=False, indent=2)

            print(f"\n✅ Analysis Complete!")
            if image_results:
                print(f"🎨 Color: {image_results[0]['color']} | 💡 Brightness: {image_results[0]['brightness']}")

        except Exception as e:
            print(f"❌ Critical Error: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        asyncio.run(run_analysis(sys.argv[1]))
    else:
        asyncio.run(run_analysis("https://x.com/snow_sayu_/status/1867910835085148236"))