import json

def convert():
    try:
        with open('cookies_raw.json', 'r', encoding='utf-8') as f:
            raw_cookies = json.load(f)

        # Playwrightが求める構造に変換
        auth_data = {
            "cookies": [],
            "origins": [
                {
                    "origin": "https://x.com",
                    "localStorage": []
                }
            ]
        }

        for cookie in raw_cookies:
            # 必要なフィールドだけを抽出
            converted = {
                "name": cookie["name"],
                "value": cookie["value"],
                "domain": cookie["domain"].lstrip('.'), # ドメインの先頭のドットを削除
                "path": cookie["path"],
                "expires": cookie.get("expirationDate", -1),
                "httpOnly": cookie.get("httpOnly", False),
                "secure": cookie.get("secure", True),
                "sameSite": "Lax" # 基本的にLaxでOK
            }
            auth_data["cookies"].append(converted)

        with open('auth.json', 'w', encoding='utf-8') as f:
            json.dump(auth_data, f, ensure_ascii=False, indent=2)
        
        print("✨ auth.json の作成に成功しました！")
        print("これでログイン画面をスキップして詳細分析が可能です。")

    except FileNotFoundError:
        print("❌ エラー: cookies_raw.json が見つかりません。")
    except Exception as e:
        print(f"❌ エラーが発生しました: {e}")

if __name__ == "__main__":
    convert()