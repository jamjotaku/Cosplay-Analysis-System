import os
import json
import asyncio
import csv
from flask import Flask, render_template, request, redirect, url_for
from werkzeug.utils import secure_filename
from datetime import datetime

# main_analyzer.py から分析ロジックをインポート
# ※ main_analyzer.py が同じフォルダにある前提です
from main_analyzer import run_analysis

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['DB_FILE'] = 'analysis_db.json'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ---------------------------------------------------------
# データ読み込み & ユーティリティ
# ---------------------------------------------------------
def load_data():
    if os.path.exists(app.config['DB_FILE']):
        with open(app.config['DB_FILE'], 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except:
                return []
    return []

def background_batch_analysis(csv_path):
    """ バックグラウンドでCSVのURLを順次処理する """
    urls = []
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # 'Expanded URL' または 'URL' カラムを探す
                url = row.get('Expanded URL') or row.get('URL')
                if url:
                    urls.append(url)
    except Exception as e:
        print(f"❌ CSV Read Error: {e}")
        return

    print(f"🚀 Batch Analysis Started: {len(urls)} tweets")
    for i, url in enumerate(urls):
        print(f"Processing {i+1}/{len(urls)}: {url}")
        asyncio.run(run_analysis(url))
    print("🎉 All Batch Analysis Completed!")

# ---------------------------------------------------------
# ルーティング
# ---------------------------------------------------------
@app.route('/')
def index():
    """ ダッシュボード (一覧画面) """
    data = load_data()
    # 新しい順に並び替え
    data.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return render_template('index.html', tweets=data)

@app.route('/upload_csv', methods=['POST'])
def upload_csv():
    """ CSVアップロード & 解析開始 """
    if 'file' not in request.files:
        return redirect(url_for('index'))
    file = request.files['file']
    if file.filename == '':
        return redirect(url_for('index'))

    if file:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        # 非同期で解析を実行 (簡易的な実装)
        import threading
        thread = threading.Thread(target=background_batch_analysis, args=(filepath,))
        thread.start()

        return redirect(url_for('index'))

@app.route('/stats')
def stats():
    """ ★分析レポート画面 (完全版) """
    data = load_data()
    if not data:
        return render_template('stats.html', stats=None)

    # --- 集計用データの初期化 ---
    stats_data = {
        "total_tweets": len(data),
        "avg_save_rate": 0,
        "avg_eng_rate": 0,
        "composition_stats": {}, # 構図別平均
        "hourly_stats": [0] * 24, # 0時~23時の平均保存率
        "scatter_data": [],       # メインマトリクス用
        "skin_scatter": []        # 肌色率 vs 保存率用
    }

    hourly_sums = [0] * 24
    hourly_counts = [0] * 24
    comp_groups = {}

    total_save_rate = 0
    total_eng_rate = 0

    for d in data:
        save_rate = d.get('save_rate', 0)
        eng_rate = d.get('engagement_rate', 0)
        total_save_rate += save_rate
        total_eng_rate += eng_rate
        
        # 1. マトリクス用データ
        img_path = ""
        comp_cat = "Unknown"
        skin_ratio = 0
        
        if d.get('images'):
            img_data = d['images'][0]
            img_path = img_data.get('path', '')
            comp_cat = img_data.get('composition', 'Unknown')
            skin_ratio = img_data.get('skin_ratio', 0)

        stats_data['scatter_data'].append({
            'x': eng_rate,
            'y': save_rate,
            'id': d.get('tweet_id'),
            'img': img_path
        })

        # 2. ★肌色率データ (構図情報も含めるのがポイント)
        # 画像があり、かつ肌色データがある場合のみ
        if d.get('images'):
            stats_data['skin_scatter'].append({
                'x': skin_ratio,
                'y': save_rate,
                'comp': comp_cat  # ★フロントエンドで色分けするために必須
            })

        # 3. 時間帯データ (ISO形式の日時文字列から時間を抽出)
        created_at = d.get('created_at')
        if created_at:
            try:
                # "2026-02-10T19:30:00" -> 19
                hour = int(created_at.split('T')[1].split(':')[0])
                hourly_sums[hour] += save_rate
                hourly_counts[hour] += 1
            except:
                pass

        # 4. 構図別データ集計
        if comp_cat not in comp_groups:
            comp_groups[comp_cat] = []
        comp_groups[comp_cat].append(save_rate)

    # --- 平均値の計算 ---
    if len(data) > 0:
        stats_data['avg_save_rate'] = round(total_save_rate / len(data), 2)
        stats_data['avg_eng_rate'] = round(total_eng_rate / len(data), 2)

    # 時間帯別平均
    for h in range(24):
        if hourly_counts[h] > 0:
            stats_data['hourly_stats'][h] = round(hourly_sums[h] / hourly_counts[h], 2)

    # 構図別平均
    stats_data['composition_stats'] = {
        k: round(sum(v)/len(v), 2) for k, v in comp_groups.items()
    }

    return render_template('stats.html', stats=stats_data)

if __name__ == '__main__':
    app.run(debug=True, port=5000)