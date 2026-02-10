from flask import Flask, render_template, request, redirect, url_for
import json
import os
import asyncio
import csv
import io
import threading
from main_analyzer import run_analysis

app = Flask(__name__)
# セッション通知用にキーを設定（必須ではないですが念のため）
app.secret_key = 'cosplay_analysis_secret'
DB_FILE = 'analysis_db.json'

def load_data():
    """ JSONデータベースを読み込むヘルパー関数 """
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            try: return json.load(f)
            except: return []
    return []

# --- 🧵 バックグラウンド処理用の関数 ---
def background_batch_analysis(urls):
    """ 裏側（別スレッド）で実行される分析ループ """
    print(f"🧵 バックグラウンド処理を開始: 全 {len(urls)} 件")
    
    # スレッドごとに新しいイベントループを作成
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    for i, url in enumerate(urls):
        # 進捗をログに出す（これがターミナルで見える）
        print(f"📦 Batch Progress: {i+1}/{len(urls)} -> {url}")
        try:
            # main_analyzer.py の処理を呼び出す
            # (main_analyzer側にスキップ機能があるので、既に終わっていれば一瞬で次へ進みます)
            loop.run_until_complete(run_analysis(url))
        except Exception as e:
            print(f"❌ Error in batch: {url} -> {e}")
    
    print("🏁 すべてのバックグラウンド分析が完了しました！")
    loop.close()

@app.route('/', methods=['GET'])
def index():
    """ トップページ: 最新の分析結果リストを表示 """
    data = load_data()
    data.reverse() # 新しい順
    return render_template('index.html', tweets=data)

@app.route('/analyze', methods=['POST'])
def analyze():
    """ 単発分析用 """
    url = request.form.get('url')
    if url:
        print(f"🚀 単発リクエスト: {url}")
        asyncio.run(run_analysis(url))
    return redirect(url_for('index'))

@app.route('/upload_csv', methods=['POST'])
def upload_csv():
    """ CSV一括分析用（スレッド対応版） """
    if 'file' not in request.files:
        return redirect(url_for('index'))
    
    file = request.files['file']
    if file.filename == '' or not file:
        return redirect(url_for('index'))

    # CSVからURLリストを作成
    stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
    csv_input = csv.reader(stream)
    
    # x.com または twitter.com を含むURLだけ抽出
    urls = [row[0].strip() for row in csv_input if row and ("x.com" in row[0] or "twitter.com" in row[0])]

    if urls:
        # ★ここが重要！
        # メイン処理を止めないように、別のスレッド（分身）を作って仕事を丸投げする
        thread = threading.Thread(target=background_batch_analysis, args=(urls,))
        thread.start()
        
        print(f"✅ {len(urls)} 件の分析をバックグラウンドで予約しました。")

    # ユーザーを待たせずに即座にトップページへ戻す
    return redirect(url_for('index'))

@app.route('/stats', methods=['GET'])
def stats():
    """ 分析レポート用（4象限マトリクス対応） """
    data = load_data()
    
    if not data:
        return render_template('stats.html', stats=None)

    # --- 統計データの計算 ---
    stats_data = {
        "total_tweets": len(data),
        "avg_save_rate": 0,
        "avg_eng_rate": 0,
        "composition_stats": {},
        "brightness_stats": {},
        "top_tweets": [],
        "scatter_data": [] # 散布図用のデータ
    }

    # 1. 全体平均の計算
    if len(data) > 0:
        total_save = sum(d.get('save_rate', 0) for d in data)
        total_eng = sum(d.get('engagement_rate', 0) for d in data)
        stats_data['avg_save_rate'] = round(total_save / len(data), 2)
        stats_data['avg_eng_rate'] = round(total_eng / len(data), 2)

    # 2. カテゴリ別集計（構図・明るさ）
    # ループを1回にまとめて高速化
    comp_groups = {}
    bright_groups = {}
    
    for d in data:
        # 画像がないデータはスキップ
        if not d.get('images'): continue
        
        # 構図集計
        comp = d['images'][0].get('composition', 'Unknown')
        if comp not in comp_groups: comp_groups[comp] = []
        comp_groups[comp].append(d.get('save_rate', 0))
        
        # 明るさ集計
        bright = d['images'][0].get('brightness', 'Unknown')
        if bright not in bright_groups: bright_groups[bright] = []
        bright_groups[bright].append(d.get('engagement_rate', 0))
        
        # ★散布図用のデータ作成 (X:Eng, Y:Save)
        stats_data['scatter_data'].append({
            'x': d.get('engagement_rate', 0),
            'y': d.get('save_rate', 0),
            'id': d.get('tweet_id'),
            'url': d.get('url'),
            'img': d['images'][0]['path'] # ツールチップ画像用
        })
    
    # 平均値の算出
    stats_data['composition_stats'] = {k: round(sum(v)/len(v), 2) for k, v in comp_groups.items()}
    stats_data['brightness_stats'] = {k: round(sum(v)/len(v), 2) for k, v in bright_groups.items()}

    # 4. ランキング（保存率TOP5）
    stats_data['top_tweets'] = sorted(data, key=lambda x: x.get('save_rate', 0), reverse=True)[:5]

    return render_template('stats.html', stats=stats_data)

if __name__ == '__main__':
    # 外部公開設定
    app.run(host='0.0.0.0', port=5000, debug=True)