from flask import Flask, render_template, request, redirect, url_for
import json
import os
import asyncio
from main_analyzer import run_analysis # さっき作った分析スクリプトを読み込む

app = Flask(__name__)
DB_FILE = 'analysis_db.json'

@app.route('/', methods=['GET'])
def index():
    # データベース(JSON)を読み込んで表示
    data = []
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except:
                data = []
    # 新しい順に並び替え
    data.reverse()
    return render_template('index.html', tweets=data)

@app.route('/analyze', methods=['POST'])
def analyze():
    # フォームからURLを取得
    url = request.form.get('url')
    if url:
        print(f"🚀 Webからの分析リクエスト: {url}")
        # 非同期関数を無理やり同期的に実行
        asyncio.run(run_analysis(url))
    
    # 終わったらトップページに戻る
    return redirect(url_for('index'))

if __name__ == '__main__':
    # 外部公開ポート(0.0.0.0)で起動
    app.run(host='0.0.0.0', port=5000, debug=True)