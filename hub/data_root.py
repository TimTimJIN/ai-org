"""データの置き場所を決める。

ai-org はコード（このリポジトリ）とデータ（案件記録など）を分けて置く。データの正本はローカルのデータフォルダーで、
環境変数 AI_ORG_DATA で指定する。データフォルダーには cases、inbox、data、knowledge-vault、work-test が入る。

AI_ORG_DATA が未設定なら、利用者の設定ファイルの data を使う。
どちらも、絶対パスで、既存のフォルダーで、中に cases があるものだけを受け付ける。
綴りの誤りや相対パスで、別の場所に新しい案件記録を作らないため。
AI_ORG_DATA が未設定でも、コードと同じフォルダーに cases がある旧来の配置（app-relay）なら、そのフォルダーを使う。
どちらでもなければ止める。リポジトリの中に案件記録を作らないため。
"""
import os
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
ENV = "AI_ORG_DATA"


def user_config_data():
    """利用者の設定（%USERPROFILE%\\.ai-org\\config.json、AI_ORG_CONFIG で変更可）の data。"""
    import json
    path = Path(os.environ.get("AI_ORG_CONFIG") or Path.home() / ".ai-org" / "config.json")
    if not path.is_file():
        return ""
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig")).get("data", "")
    except (OSError, ValueError, AttributeError) as error:
        raise ValueError(f"利用者の設定を読み取れません（{path}）：{error}") from error
    return str(value or "").strip()


def data_root():
    value = os.environ.get(ENV, "").strip() or user_config_data()
    # 既存のコマンドが ValueError を利用者向けのメッセージとして扱うため、それに合わせる。
    if value:
        path = Path(value)
        if not path.is_absolute():
            raise ValueError(f"{ENV} は絶対パスで指定してください（{value}）。")
        if not (path / "cases").is_dir():
            raise ValueError(f"{ENV} のフォルダーに cases がありません（{value}）。データフォルダーを確認してください。")
        return path.resolve()
    if (CODE_DIR / "cases").is_dir():
        return CODE_DIR
    raise ValueError(f"データの置き場所が未設定です。環境変数 {ENV} にデータフォルダーを指定してください。")
