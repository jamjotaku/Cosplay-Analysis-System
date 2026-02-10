import sys
import asyncio
import json
import re
from datetime import datetime
from playwright.async_api import async_playwright

# --- 設定 ---
AUTH_FILE = 'auth.json'  # ログイン情報（これがないと詳細データが見れない場合がある）

# ロケーション判定用キーワード (レガシー機能移植)
LOCATION_KEYWORDS = {
    "Event": ["コミケ", "C9", "C10", "夏コミ", "冬コミ", "アコスタ", "acosta", "池ハロ", "となコス", "超会議", "ニコ超", "ラグコス", "ワンフェス", "ホココス", "ビビコス", "ストフェス", "a!"],
    "Studio": ["スタジオ", "studio", "撮", "撮影会", "宅コス", "家", "自撮り", "セルフィー", "笹塚"]
}

def parse_metric(text):
    """ '1.5万' などの表記を数値に変換 """
    if not text: return 0
    text = text.replace(',', '').strip()
    try:
        if '万' in text: return int(float(text.replace('万', '')) * 10000)
        if 'K' in text: return int(float(text.replace('K', '')) * 1000)
        if 'M' in text: return int(float(text.replace('M', '')) * 1000000)
        return int(''.join(filter(str.isdigit, text)) or 0)
    except: return 0

async def analyze_tweet(url):
    print(f"🔍 Analyzing: {url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state=AUTH_FILE if asyncio.os.path.exists(AUTH_FILE) else None,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(3) # レンダリング待ち

            # --- 1. 基本メトリクス取得 (いいね, RP, ブックマーク, インプレッション) ---
            # aria-label属性から正確な数値を拾う戦略
            metrics = {
                'likes': 0, 'reposts': 0, 'bookmarks': 0, 'views': 0, 'replies': 0
            }

            # data-testid 属性を使って特定
            likes_elem = await page.query_selector('[data-testid="like"]') or await page.query_selector('[data-testid="unlike"]')
            if likes_elem:
                 # aria-label="1234 likes" から抽出
                 label = await likes_elem.get_attribute("aria-label")
                 metrics['likes'] = parse_metric(label)

            rp_elem = await page.query_selector('[data-testid="retweet"]') or await page.query_selector('[data-testid="unretweet"]')
            if rp_elem:
                 label = await rp_elem.get_attribute("aria-label")
                 metrics['reposts'] = parse_metric(label)

            bm_elem = await page.query_selector('[data-testid="bookmark"]') or await page.query_selector('[data-testid="removeBookmark"]')
            if bm_elem:
                 label = await bm_elem.get_attribute("aria-label")
                 metrics['bookmarks'] = parse_metric(label)
            
            # インプレッション (Views) - 表示場所が変動するためテキスト探索
            # 通常は "xyz Views" のように表示されるリンクまたはspanを探す
            view_elem = await page.query_selector('a[href$="/analytics"]')
            if view_elem:
                text = await view_elem.inner_text() # "1.2万を表示" など
                metrics['views'] = parse_metric(text)
            
            # --- 2. ユーザー情報 (フォロワー数) ---
            # Viral Efficiency計算用
            user_link = await page.query_selector('[data-testid="User-Name"] a')
            follower_count = 0
            screen_name = "Unknown"
            if user_link:
                href = await user_link.get_attribute("href")
                screen_name = href.replace('/', '')
                # プロフィールをホバーまたは別タブで開かないと取れない場合があるが、
                # 今回は単一分析なので、プロフィールページへジャンプして取るのもアリ
                # (簡易版として一旦スキップし、必要なら実装追加)

            # --- 3. テキスト & ロケーション判定 ---
            text_content = ""
            text_elem = await page.query_selector('[data-testid="tweetText"]')
            if text_elem:
                text_content = await text_elem.inner_text()
            
            loc_label = 'Others'
            if any(k in text_content for k in LOCATION_KEYWORDS['Event']): loc_label = 'Event'
            elif any(k in text_content for k in LOCATION_KEYWORDS['Studio']): loc_label = 'Studio/Home'

            # --- 4. 画像分析 (アスペクト比) ---
            images = []
            img_elems = await page.query_selector_all('[data-testid="tweetPhoto"] img')
            aspect_label = 'No Image'
            
            for img in img_elems:
                src = await img.get_attribute("src")
                # スタイルからアスペクト比を推測
                style = await img.get_attribute("style") # width/heightが入っていることが多い
                # ここでは簡易的に1枚目のURLを取得
                images.append(src)
            
            if images:
                # 実際の画像サイズ取得は別途画像処理が必要だが、
                # ここでは「画像がある」ことまでは確定
                aspect_label = 'Image Found' 

            # --- 5. 時間帯 ---
            time_elem = await page.query_selector('time')
            post_time = "Unknown"
            post_hour = -1
            if time_elem:
                dt_str = await time_elem.get_attribute("datetime")
                post_time = dt_str
                try:
                    dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                    post_hour = dt.hour
                except: pass

            # --- 結果出力 ---
            result = {
                'url': url,
                'screen_name': screen_name,
                'metrics': metrics,
                'text_analysis': {
                    'length': len(text_content),
                    'hashtags': text_content.count('#'),
                    'location_type': loc_label
                },
                'image_analysis': {
                    'count': len(images),
                    'urls': images,
                    'aspect_status': aspect_label
                },
                'time_analysis': {
                    'posted_at': post_time,
                    'hour': post_hour
                }
            }
            
            # コンソールに見やすく表示
            print("-" * 40)
            print(f"📊 分析結果: {screen_name}")
            print(f"❤️ Likes: {metrics['likes']:,}")
            print(f"👁️ Views: {metrics['views']:,}")
            print(f"🔖 Saves: {metrics['bookmarks']:,}")
            
            if metrics['views'] > 0:
                eng_rate = round((metrics['likes'] / metrics['views']) * 100, 2)
                print(f"⚡ Engagement Rate: {eng_rate}% (Likes/Views)")
            
            print(f"📍 Location: {loc_label}")
            print(f"⏰ Hour: {post_hour}時")
            print("-" * 40)

            return result

        except Exception as e:
            print(f"❌ Error: {e}")
            return None
            
        finally:
            await browser.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fetch_tweet_data.py <TWEET_URL>")
    else:
        url = sys.argv[1]
        asyncio.run(analyze_tweet(url))
