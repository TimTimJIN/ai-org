"""データの置き場所を決める。

ai-org はコード（このリポジトリ）とデータ（案件記録など）を分けて置く。データの正本はローカルのデータフォルダーで、
環境変数 AI_ORG_DATA で指定する。データフォルダーには cases、inbox、data、knowledge-vault、work-test が入る。

AI_ORG_DATA が未設定でも、コードと同じフォルダーに cases がある旧来の配置（app-relay）なら、そのフォルダーを使う。
どちらでもなければ止める。リポジトリの中に案件記録を作らないため。
"""
import os
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
ENV = "AI_ORG_DATA"


def data_root():
    value = os.environ.get(ENV)
    if value:
        return Path(value).resolve()
    if (CODE_DIR / "cases").is_dir():
        return CODE_DIR
    # 既存のコマンドが ValueError を利用者向けのメッセージとして扱うため、それに合わせる。
    raise ValueError(f"データの置き場所が未設定です。環境変数 {ENV} にデータフォルダーを指定してください。")
