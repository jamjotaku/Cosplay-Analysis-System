import os
import json
import asyncio
import csv
import threading
from flask import Flask, render_template, request, redirect, url_for
from main_analyzer import run_analysis

app = Flask(__name__)
app.config['DB_FILE'] = 'analysis_db.json'
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def load_data():
    """データベースから解析済みデータを読み込む"""
    if os.path.exists(app.config['DB_FILE']):
        with open(app.config['DB_FILE'], 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except:
                return []
    return []

# --- 🚀 解析ロジック群 ---

def background_batch_analysis(csv_path):
    """CSVの全URLを裏側で1件ずつ解析する (504タイムアウト対策)"""
    urls = []
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # 柔軟なカラム名対応
                url = row.get('Expanded URL') or row.get('URL')
                if url:
                    urls.append(url)
    except Exception as e:
        print(f"❌ CSV Read Error: {e}")
        return

    print(f"🚀 CSV Batch Start: {len(urls)} items")
    for i, url in enumerate(urls):
        try:
            # 各URLに対して非同期解析を実行
            asyncio.run(run_analysis(url))
        except Exception as e:
            print(f"⚠️ Skip {url} due to error: {e}")
            continue
    print("🎉 All tasks finished!")

@app.route('/analyze_single', methods=['POST'])
def analyze_single():
    """デバッグ用：特定のURLを1件だけその場で解析する"""
    url = request.form.get('url')
    if url:
        asyncio.run(run_analysis(url))
    return redirect(url_for('index'))

@app.route('/upload_csv', methods=['POST'])
def upload_csv():
    """CSVをアップロードし、バックグラウンドで一括解析を開始する"""
    file = request.files.get('file')
    if file and file.filename.endswith('.csv'):
        path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(path)
        # スレッドを分離して即座に画面を返す
        threading.Thread(target=background_batch_analysis, args=(path,)).start()
    return redirect(url_for('index'))

# --- 📊 表示ロジック群 ---

@app.route('/')
def index():
    """解析済みツイートのカード一覧を表示"""
    data = load_data()
    # 最新の解析結果が上にくるようにソート
    data.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return render_template('index.html', tweets=data)

@app.route('/stats')
def stats():
    """グラフおよび深掘りテーブル用の統計データを作成"""
    data = load_data()
    if not data:
        return render_template('stats.html', stats=None)
    
    stats_data = {
        "total_tweets": len(data),
        "avg_save_rate": 0,
        "avg_eng_rate": 0,
        "hourly_stats": [0] * 24,
        "scatter_data": [],
        "skin_scatter": [],
        "raw_tweets": data  # 深掘り用に生データをフロントに渡す
    }
    
    h_sums, h_counts = [0]*24, [0]*24
    total_s, total_e = 0, 0
    
    for d in data:
        s_rate = d.get('save_rate', 0)
        e_rate = d.get('engagement_rate', 0)
        total_s += s_rate
        total_e += e_rate
        
        img = d['images'][0] if d.get('images') else {}
        comp = img.get('composition', 'Unknown')
        
        # 4象限マトリクス用データ
        stats_data['scatter_data'].append({
            'x': e_rate, 
            'y': s_rate, 
            'id': d.get('tweet_id')
        })
        
        # 肌色露出度分析用 (色分けのための構図情報を付与)
        if 'skin_ratio' in img:
            stats_data['skin_scatter'].append({
                'x': img['skin_ratio'], 
                'y': s_rate, 
                'comp': comp
            })
            
        # Snowflake時刻から時間帯を集計
        c_at = d.get('created_at')
        if c_at and 'T' in c_at:
            try:
                hour = int(c_at.split('T')[1].split(':')[0])
                h_sums[hour] += s_rate
                h_counts[hour] += 1
            except:
                pass

    # 平均値の算出
    stats_data['avg_save_rate'] = round(total_s / len(data), 2)
    stats_data['avg_eng_rate'] = round(total_e / len(data), 2)
    
    for h in range(24):
        if h_counts[h] > 0:
            stats_data['hourly_stats'][h] = round(h_sums[h] / h_counts[h], 2)
    
    return render_template('stats.html', stats=stats_data)

@app.route('/clear_db')
def clear_db():
    """データベースをリセットするユーティリティ"""
    if os.path.exists(app.config['DB_FILE']):
        os.remove(app.config['DB_FILE'])
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)