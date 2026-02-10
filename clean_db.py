import json
import os

DB_FILE = 'analysis_db.json'

def clean_database():
    if not os.path.exists(DB_FILE):
        print("📁 データベースファイルが見つかりません。")
        return

    print("🧹 クリーニングを開始します...")
    
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        initial_count = len(data)
        valid_data = []
        removed_count = 0

        for entry in data:
            # 判定基準: 画像がない、または いいね数が0 (失敗データとみなす)
            has_images = len(entry.get('images', [])) > 0
            has_metrics = entry.get('metrics', {}).get('likes', 0) > 0

            # 画像があればOK、画像がなくても数値が取れていれば一応残す？
            # 今回は「画像分析」が主目的なので、「画像がない」ものは容赦なく消します
            if has_images:
                valid_data.append(entry)
            else:
                removed_count += 1
                print(f"🗑️ 削除: ID {entry.get('tweet_id')} (No Image/Failed)")

        # 上書き保存
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(valid_data, f, ensure_ascii=False, indent=2)

        print("-" * 30)
        print(f"✅ 完了しました！")
        print(f"元データ数: {initial_count} 件")
        print(f"削除した数: {removed_count} 件")
        print(f"残ったデータ: {len(valid_data)} 件")
    
    except Exception as e:
        print(f"❌ エラーが発生しました: {e}")

if __name__ == "__main__":
    clean_database()