"""旧来の配置（データフォルダーの中に置いたスクリプト）から、ai-org の使う版へ中継する。

データフォルダー（例：AI駆動×AI駆動\\app-relay）に、このファイルを次の名前で置く（docs/MIGRATION.md の一覧を参照）：
workspace_hub.py、hub_ui.py、app.py、knowledge.py、verify_work.py、seed_knowledge.py。
`python ../../workspace_hub.py claim ...` のような旧コマンドや、案件画面の起動用 .cmd がそのまま使える。

- データの置き場所：常に、このファイルがあるフォルダー（環境変数 AI_ORG_DATA より優先する）。
- 使う版の場所：同じフォルダーの ai-org-home.txt に書いたフォルダー。ファイルがないときだけ環境変数 AI_ORG_HOME を使う。
  相対パスはこのフォルダーを基準に解決し、%LOCALAPPDATA% などの環境変数は展開する。
  そのフォルダーの hub/ にある同じ名前のスクリプトを実行する。
- import されたときは何もせずに止める（中継はコマンドとして実行されたときだけ動く）。
"""
import os
import runpy
import sys
from pathlib import Path

if __name__ != "__main__":
    raise ImportError("この中継スクリプトは import できません。ai-org の使う版の hub/ を import してください。")

here = Path(__file__).resolve().parent
os.environ["AI_ORG_DATA"] = str(here)

home_file = here / "ai-org-home.txt"
if home_file.is_file():
    home = home_file.read_text(encoding="utf-8-sig").strip()
else:
    home = os.environ.get("AI_ORG_HOME", "").strip()
if not home:
    sys.exit("ai-org の使う版の場所が分かりません。ai-org-home.txt に書くか、AI_ORG_HOME を設定してください。")

home_path = Path(os.path.expandvars(home))
if not home_path.is_absolute():
    home_path = here / home_path
hub = home_path.resolve() / "hub"
target = hub / Path(__file__).name
if not target.is_file():
    sys.exit(f"ai-org の使う版に {target.name} が見つかりません（{hub}）。")

# 中継先の hub/ を最優先にする（このフォルダーにある同名の中継ファイルを読み込まないため）。
sys.path.insert(0, str(hub))
sys.argv[0] = str(target)
runpy.run_path(str(target), run_name="__main__")
