import os
import json
import asyncio
import csv
import threading
import time
import random
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

# --- 🚀 解析ミッション・コントロール (耐久仕様) ---

def background_batch_analysis(csv_path):
    """
    【耐久レース仕様】アクセス制限を回避しながら完走するロジック
   
    """
    urls = []
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = row.get('Expanded URL') or row.get('URL')
                if url:
                    urls.append(url)
    except Exception as e:
        print(f"❌ CSV読み込み失敗: {e}")
        return

    total = len(urls)
    print(f"🚀 解析マラソン開始: 全 {total} 件")

    for i, url in enumerate(urls):
        current_num = i + 1
        try:
            print(f"🔄 [{current_num}/{total}] 解析中: {url}")
            
            # 非同期関数を同期的に実行
            asyncio.run(run_analysis(url))
            
            # --- 🛡️ アクセス制限(ボット判定)回避ロジック ---
            
            # 1. 毎回の「ゆらぎ」待機 (5~12秒)
            # 人間が操作しているような不規則な間隔を作る
            time.sleep(random.uniform(5, 12))
            
            # 2. 50件ごとの「大休憩」 (5分)
            # サーバー側の監視をリセットさせるためのクールダウン
            if current_num % 50 == 0:
                print(f"☕ 50件到達。X側の監視をそらすため5分間休憩します...")
                time.sleep(300) 
                
        except Exception as e:
            print(f"⚠️ スキップ ({url}): {e}")
            # エラー時はX側のペナルティを考慮し、少し長めに休む
            time.sleep(30)
            continue

    print("🎉 全ての解析タスクが完了しました！")

@app.route('/analyze_single', methods=['POST'])
def analyze_single():
    """特定のURLを即座に1件解析するデバッグ機能"""
    url = request.form.get('url')
    if url:
        asyncio.run(run_analysis(url))
    return redirect(url_for('index'))

@app.route('/upload_csv', methods=['POST'])
def upload_csv():
    """CSVを受け取り、スレッドを分離して解析を開始する"""
    file = request.files.get('file')
    if file and file.filename.endswith('.csv'):
        path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(path)
        # バックグラウンドで解析をキック
        threading.Thread(target=background_batch_analysis, args=(path,)).start()
    return redirect(url_for('index'))

# --- 📊 統計ダッシュボード・ロジック ---

@app.route('/')
def index():
    data = load_data()
    # 最新の解析結果が上にくるようソート
    data.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return render_template('index.html', tweets=data)

@app.route('/stats')
def stats():
    """深掘り分析・ランキング・構図効率のデータを生成"""
    data = load_data()
    if not data:
        return render_template('stats.html', stats=None)
    
    stats_data = {
        "total_tweets": len(data),
        "avg_save_rate": 0, "avg_eng_rate": 0,
        "hourly_stats": [0] * 24,
        "scatter_data": [], "skin_scatter": [],
        "comp_efficiency": {}, # 構図別平均保存率
        "raw_tweets": data     # ランキングテーブル用
    }
    
    h_sums, h_counts, comp_map = [0]*24, [0]*24, {}
    total_s, total_e = 0, 0
    
    for d in data:
        s_rate = d.get('save_rate', 0)
        e_rate = d.get('engagement_rate', 0)
        total_s += s_rate; total_e += e_rate
        
        img = d['images'][0] if d.get('images') else {}
        comp = img.get('composition', 'Unknown')
        
        # 散布図データ
        stats_data['scatter_data'].append({'x': e_rate, 'y': s_rate, 'id': d.get('tweet_id')})
        if 'skin_ratio' in img:
            stats_data['skin_scatter'].append({'x': img['skin_ratio'], 'y': s_rate, 'comp': comp})
            
        # 構図集計
        if comp not in comp_map: comp_map[comp] = []
        comp_map[comp].append(s_rate)

        # 時間帯集計
        c_at = d.get('created_at')
        if c_at and 'T' in c_at:
            try:
                hour = int(c_at.split('T')[1].split(':')[0])
                h_sums[hour] += s_rate; h_counts[hour] += 1
            except: pass

    # 各統計値の算出
    stats_data['avg_save_rate'] = round(total_s / len(data), 2)
    stats_data['avg_eng_rate'] = round(total_e / len(data), 2)
    for h in range(24):
        if h_counts[h] > 0: stats_data['hourly_stats'][h] = round(h_sums[h]/h_counts[h], 2)
    
    # 構図効率
    stats_data['comp_efficiency'] = {k: round(sum(v)/len(v), 2) for k, v in comp_map.items()}
    
    return render_template('stats.html', stats=stats_data)

@app.route('/clear_db')
def clear_db():
    if os.path.exists(app.config['DB_FILE']):
        os.remove(app.config['DB_FILE'])
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)