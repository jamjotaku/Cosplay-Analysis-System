import sys
import asyncio
import re
import os
from playwright.async_api import async_playwright

# --- 設定 ---
AUTH_FILE = 'auth.json'

def extract_number_from_label(text):
    """ 
    aria-label="15,234 Likes" や "851 Reposts" から数字だけを抜き出す
    画面表示が "15K" でも、aria-label は正確な数字を持っていることが多い
    """
    if not text: return 0
    # カンマ削除
    clean_text = text.replace(',', '')
    
    # "15K" 表記の場合の対応 (aria-labelも短縮されている場合への保険)
    multiplier = 1
    if 'K' in clean_text.upper() and 'LIKES' not in clean_text.upper(): # 単位としてのKかチェック
         if 'K' in clean_text: multiplier = 1000
         elif 'M' in clean_text: multiplier = 1000000

    # 数字抽出
    match = re.search(r'(\d+(?:\.\d+)?)', clean_text)
    if match:
        val = float(match.group(1))
        return int(val * multiplier)
    return 0

async def analyze_tweet(url):
    print(f"🔍 Analyzing: {url}")

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

            metrics = {'likes': 0, 'reposts': 0, 'bookmarks': 0, 'views': 0}

            # --- 戦略: ボタンの aria-label (読み上げ用テキスト) を攻める ---
            # これが最も確実。画面上 "15K" でも、ここは "15234" だったりする。

            # 1. いいね (Like / Unlike 両対応)
            like_btn = await page.query_selector('[data-testid="like"]') or await page.query_selector('[data-testid="unlike"]')
            if like_btn:
                label = await like_btn.get_attribute("aria-label")
                # 例: "15234 Likes" または "Like" (0の場合)
                metrics['likes'] = extract_number_from_label(label)

            # 2. リポスト (Retweet / Unretweet)
            rp_btn = await page.query_selector('[data-testid="retweet"]') or await page.query_selector('[data-testid="unretweet"]')
            if rp_btn:
                label = await rp_btn.get_attribute("aria-label")
                metrics['reposts'] = extract_number_from_label(label)

            # 3. ブックマーク (Bookmark / RemoveBookmark)
            bm_btn = await page.query_selector('[data-testid="bookmark"]') or await page.query_selector('[data-testid="removeBookmark"]')
            if bm_btn:
                label = await bm_btn.get_attribute("aria-label")
                metrics['bookmarks'] = extract_number_from_label(label)
            
            # 4. インプレッション (Views)
            # これはボタンではなくリンクまたはテキスト
            view_elem = await page.query_selector('a[href*="/analytics"]')
            if view_elem:
                label = await view_elem.get_attribute("aria-label") or await view_elem.inner_text()
                metrics['views'] = extract_number_from_label(label)
            
            # --- 補正: 画面上のテキスト表示 ("15K") からのバックアップ取得 ---
            # aria-labelが "Like" (数字なし) だけど画面には "15K" とある場合の対策
            if metrics['likes'] == 0:
                 like_text_elem = await page.query_selector('[data-testid="like"] span, [data-testid="unlike"] span')
                 if like_text_elem:
                     text = await like_text_elem.inner_text()
                     if text:
                         # K/M変換ロジックを通す
                         text = text.replace('K', '000').replace('M', '000000').replace('.', '') # 簡易変換
                         metrics['likes'] = extract_number_from_label(text)

            # --- 結果出力 ---
            print("\n" + "💎" * 20)
            print(f"📊 正確な分析結果")
            print("💎" * 20)
            print(f"❤️ Likes:    {metrics['likes']:,}")
            print(f"🔄 Reposts:  {metrics['reposts']:,}")
            print(f"🔖 Saves:    {metrics['bookmarks']:,}")
            print(f"👁️ Views:    {metrics['views']:,}")
            
            if metrics['views'] > 0:
                eng_rate = round((metrics['likes'] / metrics['views']) * 100, 2)
                print("-" * 20)
                print(f"⚡ Engagement Rate: {eng_rate}%")
            
            # 保存率の計算
            if metrics['likes'] > 0:
                save_rate = round((metrics['bookmarks'] / metrics['likes']) * 100, 2)
                print(f"💾 Save Rate:       {save_rate}%")
                
            print("💎" * 20 + "\n")

        except Exception as e:
            print(f"❌ Error: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://x.com/snow_sayu_/status/1867910835085148236"
    asyncio.run(analyze_tweet(url))