import os
import glob
from PIL import Image
import torch
from transformers import CLIPProcessor, CLIPModel

# --- 設定 ---
IMAGE_DIR = 'downloaded_images'
# 判定させたい構図のリスト（英語で定義します）
COMPOSITION_LABELS = [
    "a close-up photo of a face",       # 顔のアップ
    "a bust-up portrait of a person",   # バストアップ（胸から上）
    "a full-body photo of a person",    # 全身
    "a photo of scenery or objects"     # 風景や小道具（人物メインじゃない）
]
# わかりやすい表示用の日本語ラベル
LABEL_MAP = {
    0: "顔アップ (Face Close-up)",
    1: "バストアップ (Bust-up)",
    2: "全身 (Full Body)",
    3: "風景・その他 (Scenery/Others)"
}

# --- モデルの準備（初回はダウンロードに時間がかかります） ---
print("🤖 AIモデルをロード中... (初回は数分かかる場合があります)")
model_id = "openai/clip-vit-base-patch32"
# CPUでの実行を明示
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"   Running on: {device}")

model = CLIPModel.from_pretrained(model_id).to(device)
processor = CLIPProcessor.from_pretrained(model_id)
print("✅ モデルロード完了！")

def get_latest_image(directory):
    """ 指定ディレクトリ内で最も新しい画像ファイルを取得 """
    list_of_files = glob.glob(os.path.join(directory, '*.jpg'))
    if not list_of_files:
        return None
    latest_file = max(list_of_files, key=os.path.getctime)
    return latest_file

def analyze_composition(image_path):
    """ 画像の構図を判定する """
    print(f"\n🔍 Analyzing Image: {image_path}")
    try:
        image = Image.open(image_path)
        
        # 画像とテキストをモデルに入力できる形式に変換
        inputs = processor(
            text=COMPOSITION_LABELS,
            images=image,
            return_tensors="pt",
            padding=True
        ).to(device)

        # 推論実行
        with torch.no_grad(): # 学習しないのでメモリ節約
            outputs = model(**inputs)
        
        # 画像と各テキストの類似度スコアを取得
        logits_per_image = outputs.logits_per_image
        # スコアを確率（パーセンテージ）に変換 (softmax)
        probs = logits_per_image.softmax(dim=1)
        
        # 結果をリストに変換
        scores = probs.tolist()[0]
        
        # スコアが高い順に並べ替え
        results = []
        for i, score in enumerate(scores):
            results.append((i, score * 100))
        results.sort(key=lambda x: x[1], reverse=True)

        # --- 結果表示 ---
        print("\n" + "🎨" * 20)
        print("📊 AI構図判定結果")
        print("🎨" * 20)
        
        # 最も可能性が高い判定
        top_label_idx = results[0][0]
        top_score = results[0][1]
        print(f"🏆 判定: 【 {LABEL_MAP[top_label_idx]} 】 (確信度: {top_score:.1f}%)")
        print("-" * 30)
        
        print("詳細スコア:")
        for label_idx, score in results:
             print(f"  - {LABEL_MAP[label_idx]:<20}: {score:.1f}%")
        print("🎨" * 20 + "\n")

    except Exception as e:
        print(f"❌ Error analyzing image: {e}")

if __name__ == "__main__":
    # 最新の画像を取得して解析
    latest_img = get_latest_image(IMAGE_DIR)
    if latest_img:
        analyze_composition(latest_img)
    else:
        print(f"❌ エラー: '{IMAGE_DIR}' フォルダに画像が見つかりません。")
        print("先に fetch_tweet_data.py を実行して画像をダウンロードしてください。")