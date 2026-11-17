"""旧来の配置（データフォルダーの中に置いたスクリプト）から、ai-org の使う版へ中継する。

データフォルダー（例：AI駆動×AI駆動\\app-relay）に、このファイルを workspace_hub.py・hub_ui.py などの名前で置く。
`python ../../workspace_hub.py claim ...` のような旧コマンドや、案件画面の起動用 .cmd がそのまま使える。

- データの置き場所：このファイルがあるフォルダー（AI_ORG_DATA が設定済みならそちら）。
- 使う版の場所：環境変数 AI_ORG_HOME、なければ同じフォルダーの ai-org-home.txt に書いたフォルダー。
  そのフォルダーの hub/ にある同じ名前のスクリプトを実行する。
"""
import os
import runpy
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
os.environ.setdefault("AI_ORG_DATA", str(here))

home = os.environ.get("AI_ORG_HOME", "").strip()
home_file = here / "ai-org-home.txt"
if not home and home_file.is_file():
    home = home_file.read_text(encoding="utf-8-sig").strip()
if not home:
    sys.exit("ai-org の使う版の場所が分かりません。AI_ORG_HOME を設定するか、ai-org-home.txt に書いてください。")

hub = Path(home).resolve() / "hub"
target = hub / Path(__file__).name
if not target.is_file():
    sys.exit(f"ai-org の使う版に {target.name} が見つかりません（{hub}）。")

# 中継先の hub/ を最優先にする（このフォルダーにある同名の中継ファイルを読み込まないため）。
sys.path.insert(0, str(hub))
sys.argv[0] = str(target)
runpy.run_path(str(target), run_name="__main__")
