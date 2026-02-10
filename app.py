from flask import Flask, render_template, request, redirect, url_for
import json
import os
import asyncio
from main_analyzer import run_analysis

app = Flask(__name__)
DB_FILE = 'analysis_db.json'

def load_data():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            try: return json.load(f)
            except: return []
    return []

@app.route('/', methods=['GET'])
def index():
    data = load_data()
    data.reverse() # 新しい順
    return render_template('index.html', tweets=data)

@app.route('/analyze', methods=['POST'])
def analyze():
    url = request.form.get('url')
    if url:
        print(f"🚀 Webからの分析リクエスト: {url}")
        asyncio.run(run_analysis(url))
    return redirect(url_for('index'))

@app.route('/stats', methods=['GET'])
def stats():
    data = load_data()
    if not data:
        return render_template('stats.html', stats=None)

    # --- 集計ロジック ---
    stats_data = {
        "total_tweets": len(data),
        "avg_save_rate": 0,
        "avg_eng_rate": 0,
        "composition_stats": {},
        "brightness_stats": {},
        "top_tweets": []
    }

    # 1. 全体平均
    total_save = sum(d['save_rate'] for d in data)
    total_eng = sum(d['engagement_rate'] for d in data)
    stats_data['avg_save_rate'] = round(total_save / len(data), 2)
    stats_data['avg_eng_rate'] = round(total_eng / len(data), 2)

    # 2. 構図別の平均保存率
    comp_groups = {}
    for d in data:
        if not d['images']: continue
        comp = d['images'][0]['composition']
        if comp not in comp_groups: comp_groups[comp] = []
        comp_groups[comp].append(d['save_rate'])
    
    stats_data['composition_stats'] = {
        k: round(sum(v)/len(v), 2) for k, v in comp_groups.items()
    }

    # 3. 明るさ別の平均エンゲージメント
    bright_groups = {}
    for d in data:
        if not d['images']: continue
        b = d['images'][0].get('brightness', 'Unknown')
        if b not in bright_groups: bright_groups[b] = []
        bright_groups[b].append(d['engagement_rate'])
    
    stats_data['brightness_stats'] = {
        k: round(sum(v)/len(v), 2) for k, v in bright_groups.items()
    }

    # 4. ランキング（保存率TOP3）
    sorted_data = sorted(data, key=lambda x: x['save_rate'], reverse=True)
    stats_data['top_tweets'] = sorted_data[:3]

    return render_template('stats.html', stats=stats_data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)