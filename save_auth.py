import asyncio
from playwright.async_api import async_playwright
import os

async def save_auth():
    async with async_playwright() as p:
        # 手動でログイン操作を行うため、ブラウザを表示（headless=False）で起動
        # Codespaceで実行する場合、GUI環境がないとエラーになるため注意
        try:
            browser = await p.chromium.launch(headless=False)
        except Exception as e:
            print(f"❌ エラー: ブラウザを起動できませんでした。GUI環境が必要です。\n{e}")
            print("\n💡 ヒント: Codespaceではなく、ローカルPCのターミナルで実行して生成された auth.json をアップロードするのが一番簡単です。")
            return

        context = await browser.new_context()
        page = await context.new_page()

        # X(Twitter)のログイン画面へ移動
        await page.goto("https://x.com/i/flow/login")

        print("\n" + "="*50)
        print("1. ブラウザが起動したら、Xにログインしてください。")
        print("2. ログインが完了し、タイムラインが表示されたらここに戻ってください。")
        print("="*50 + "\n")

        # ユーザーの入力を待機（ログインが終わるまで待つ）
        await asyncio.get_event_loop().run_in_executor(
            None, input, "ログインが完了したら Enter キーを押してください..."
        )

        # 現在の認証状態（Cookie、localStorageなど）を保存
        await context.storage_state(path="auth.json")
        
        print("\n✨ auth.json にログイン情報を保存しました！")
        print("⚠️ このファイルにはパスワードに相当する情報が含まれています。取り扱いに注意してください。")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(save_auth())
