import sys
import asyncio
import re
import os
from playwright.async_api import async_playwright

# --- 設定 ---
AUTH_FILE = 'auth.json'
SAVE_DIR = 'downloaded_images'

# フォルダがない場合は作成
if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR)

def extract_number_from_label(text):
    if not text: return 0
    clean_text = text.replace(',', '')
    multiplier = 1
    if 'K' in clean_text.upper() and 'LIKES' not in clean_text.upper():
         if 'K' in clean_text: multiplier = 1000
         elif 'M' in clean_text: multiplier = 1000000
    match = re.search(r'(\d+(?:\.\d+)?)', clean_text)
    if match:
        val = float(match.group(1))
        return int(val * multiplier)
    return 0

def get_high_res_url(url):
    if not url: return None
    base_match = re.match(r'(https://pbs\.twimg\.com/media/[\w-]+)', url)
    if base_match:
        base_url = base_match.group(1)
        fmt = 'png' if '.png' in url else 'jpg'
        return f"{base_url}?format={fmt}&name=orig"
    return url

async def analyze_tweet(url):
    print(f"🔍 Analyzing: {url}")
    # URLからツイートIDを抽出
    tweet_id = url.split('/')[-1].split('?')[0]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state=AUTH_FILE if os.path.exists(AUTH_FILE) else None,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(3)

            # --- メトリクス取得 ---
            metrics = {'likes': 0, 'reposts': 0, 'bookmarks': 0, 'views': 0}
            like_btn = await page.query_selector('[data-testid="like"]') or await page.query_selector('[data-testid="unlike"]')
            if like_btn: metrics['likes'] = extract_number_from_label(await like_btn.get_attribute("aria-label"))
            bm_btn = await page.query_selector('[data-testid="bookmark"]') or await page.query_selector('[data-testid="removeBookmark"]')
            if bm_btn: metrics['bookmarks'] = extract_number_from_label(await bm_btn.get_attribute("aria-label"))
            view_elem = await page.query_selector('a[href*="/analytics"]')
            if view_elem: metrics['views'] = extract_number_from_label(await view_elem.inner_text())

            # --- 画像の抽出とダウンロード ---
            image_urls = []
            tweet_photo_container = await page.query_selector('[data-testid="tweetPhoto"]')
            if tweet_photo_container:
                images = await tweet_photo_container.query_selector_all('img')
                for i, img in enumerate(images):
                    src = await img.get_attribute('src')
                    if src and 'pbs.twimg.com/media' in src:
                        high_res = get_high_res_url(src)
                        if high_res and high_res not in image_urls:
                            image_urls.append(high_res)
                            
                            # ダウンロード実行
                            save_path = os.path.join(SAVE_DIR, f"{tweet_id}_{len(image_urls)}.jpg")
                            try:
                                img_page = await context.new_page()
                                response = await img_page.goto(high_res)
                                if response:
                                    await response.body()
                                    with open(save_path, "wb") as f:
                                        f.write(await response.body())
                                    print(f"  ✅ Saved: {save_path}")
                                await img_page.close()
                            except Exception as e:
                                print(f"  ❌ Failed to download {high_res}: {e}")

            # --- 結果出力 ---
            print("\n" + "📸" * 20)
            print(f"📊 分析完了: {len(image_urls)}枚の画像を保存しました")
            print("📸" * 20)
            print(f"❤️ Likes:    {metrics['likes']:,}")
            print(f"🔖 Saves:    {metrics['bookmarks']:,}")
            print(f"👁️ Views:    {metrics['views']:,}")
            print(f"📂 Location: ./{SAVE_DIR}/")
            print("📸" * 20 + "\n")

        except Exception as e:
            print(f"❌ Error: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "https://x.com/snow_sayu_/status/1867910835085148236"
    asyncio.run(analyze_tweet(target))