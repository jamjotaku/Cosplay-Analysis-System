import os, json, re, asyncio, csv, threading, time, random
from flask import Flask, render_template, request, redirect, url_for
from main_analyzer import run_analysis

app = Flask(__name__)
app.config['DB_FILE'] = 'analysis_db.json'
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def load_data():
    if os.path.exists(app.config['DB_FILE']):
        with open(app.config['DB_FILE'], 'r', encoding='utf-8') as f:
            try: return json.load(f)
            except: return []
    return []

def analyze_keywords(data):
    """【新機能】キーワード別の保存率貢献度を算出 [cite: 2026-02-12] """
    kw_stats = {}
    targets = ["水着", "制服", "新衣装", "速報", "宅コス", "うるは", "のあ", "なずな", "るな", "ひなの"]
    
    for d in data:
        text = d.get('tweet_text', "")
        s_rate = d.get('save_rate', 0)
        tags = re.findall(r'#(\w+)', text)
        found_kws = [k for k in targets if k in text]
        
        for word in set(tags + found_kws):
            if word not in kw_stats: kw_stats[word] = {'count': 0, 'sum_save': 0}
            kw_stats[word]['count'] += 1
            kw_stats[word]['sum_save'] += s_rate

    results = [{'word': k, 'count': v['count'], 'avg_save': round(v['sum_save']/v['count'], 2)} 
               for k, v in kw_stats.items() if v['count'] >= 2] # 2回以上出現
    return sorted(results, key=lambda x: x['avg_save'], reverse=True)

def background_batch_analysis(csv_path):
    """【耐久仕様】休憩を挟みながら解析 """
    urls = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            url = row.get('Expanded URL') or row.get('URL')
            if url: urls.append(url)

    for i, url in enumerate(urls):
        try:
            asyncio.run(run_analysis(url))
            time.sleep(random.uniform(5, 12)) # ステルス待機
            if (i+1) % 50 == 0: time.sleep(300) # 50件ごとの大休憩
        except: continue

@app.route('/')
def index():
    data = load_data()
    data.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return render_template('index.html', tweets=data)

@app.route('/stats')
def stats():
    data = load_data()
    if not data: return render_template('stats.html', stats=None)
    
    stats_data = {
        "total_tweets": len(data), "avg_save_rate": 0, "avg_eng_rate": 0,
        "hourly_stats": [0]*24, "scatter_data": [], "skin_scatter": [],
        "comp_efficiency": {}, "keyword_ranking": analyze_keywords(data), "raw_tweets": data
    }
    
    h_sums, h_counts, comp_map = [0]*24, [0]*24, {}
    total_s, total_e = 0, 0
    for d in data:
        s, e = d.get('save_rate', 0), d.get('engagement_rate', 0)
        total_s += s; total_e += e
        img = d['images'][0] if d.get('images') else {}
        comp = img.get('composition', 'Unknown')
        stats_data['scatter_data'].append({'x': e, 'y': s, 'id': d.get('tweet_id')})
        if 'skin_ratio' in img: stats_data['skin_scatter'].append({'x': img['skin_ratio'], 'y': s, 'comp': comp})
        if comp not in comp_map: comp_map[comp] = []
        comp_map[comp].append(s)
        c_at = d.get('created_at')
        if c_at:
            h = int(c_at.split('T')[1].split(':')[0])
            h_sums[h] += s; h_counts[h] += 1

    stats_data['avg_save_rate'] = round(total_s / len(data), 2)
    stats_data['avg_eng_rate'] = round(total_e / len(data), 2)
    for h in range(24):
        if h_counts[h] > 0: stats_data['hourly_stats'][h] = round(h_sums[h]/h_counts[h], 2)
    stats_data['comp_efficiency'] = {k: round(sum(v)/len(v), 2) for k, v in comp_map.items()}
    
    return render_template('stats.html', stats=stats_data)

@app.route('/upload_csv', methods=['POST'])
def upload_csv():
    file = request.files.get('file')
    if file:
        path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(path)
        threading.Thread(target=background_batch_analysis, args=(path,)).start()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)