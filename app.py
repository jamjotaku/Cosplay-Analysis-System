import os
import json
import asyncio
import csv
import threading
from flask import Flask, render_template, request, redirect, url_for

# main_analyzer.py から v4.0 のロジックを読み込み
try:
    from main_analyzer import run_analysis
except ImportError:
    print("❌ main_analyzer.py が見つかりません。")

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['DB_FILE'] = 'analysis_db.json'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def load_data():
    if os.path.exists(app.config['DB_FILE']):
        try:
            with open(app.config['DB_FILE'], 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []
    return []

# --- 🚀 解析処理群 ---

def background_batch_analysis(csv_path):
    """ CSV用：504エラー回避スレッド """
    urls = []
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = row.get('Expanded URL') or row.get('URL')
                if url: urls.append(url)
    except: return

    for i, url in enumerate(urls):
        try:
            print(f"🔄 {i+1}/{len(urls)}: {url}")
            asyncio.run(run_analysis(url))
        except: continue

@app.route('/analyze_single', methods=['POST'])
def analyze_single():
    """ ★デバッグ用：1件だけその場で解析する """
    url = request.form.get('url')
    if url:
        print(f"🎯 Single Debug: {url}")
        try:
            # 単発の場合は完了を待ってから画面をリロード
            asyncio.run(run_analysis(url))
        except Exception as e:
            print(f"❌ Error: {e}")
    return redirect(url_for('index'))

@app.route('/upload_csv', methods=['POST'])
def upload_csv():
    """ CSV用：即リダイレクトして裏で回す """
    file = request.files.get('file')
    if file and file.filename.endswith('.csv'):
        path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(path)
        threading.Thread(target=background_batch_analysis, args=(path,)).start()
    return redirect(url_for('index'))

# --- 📊 表示処理群 ---

@app.route('/')
def index():
    data = load_data()
    data.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return render_template('index.html', tweets=data)

@app.route('/stats')
def stats():
    """ 最新の肌色・時間・構図分析を統合 """
    data = load_data()
    if not data: return render_template('stats.html', stats=None)

    stats_data = {
        "total_tweets": len(data),
        "avg_save_rate": 0, "avg_eng_rate": 0,
        "composition_stats": {},
        "hourly_stats": [0] * 24,
        "scatter_data": [],
        "skin_scatter": []
    }

    h_sums, h_counts = [0]*24, [0]*24
    comp_groups = {}
    total_s, total_e = 0, 0

    for d in data:
        s_rate, e_rate = d.get('save_rate', 0), d.get('engagement_rate', 0)
        total_s += s_rate; total_e += e_rate
        img = d['images'][0] if d.get('images') else {}
        comp = img.get('composition', 'Unknown')

        # マトリクス用
        stats_data['scatter_data'].append({'x': e_rate, 'y': s_rate, 'id': d.get('tweet_id')})
        
        # 肌色用 (★compを含めることで色分け可能に)
        if 'skin_ratio' in img:
            stats_data['skin_scatter'].append({'x': img['skin_ratio'], 'y': s_rate, 'comp': comp})

        # 時間帯用
        c_at = d.get('created_at')
        if c_at and 'T' in c_at:
            try:
                hour = int(c_at.split('T')[1].split(':')[0])
                h_sums[hour] += s_rate; h_counts[hour] += 1
            except: pass

        if comp not in comp_groups: comp_groups[comp] = []
        comp_groups[comp].append(s_rate)

    stats_data['avg_save_rate'] = round(total_s / len(data), 2)
    stats_data['avg_eng_rate'] = round(total_e / len(data), 2)
    for h in range(24):
        if h_counts[h] > 0: stats_data['hourly_stats'][h] = round(h_sums[h]/h_counts[h], 2)
    stats_data['composition_stats'] = {k: round(sum(v)/len(v), 2) for k, v in comp_groups.items()}

    return render_template('stats.html', stats=stats_data)

if __name__ == '__main__':
    app.run(debug=True, port=5000)