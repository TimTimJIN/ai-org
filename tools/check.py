"""ai-org の自動テストをまとめて実行する（hub と extensions/dev・extensions/relay）。1つでも失敗したら終了コード 1。"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
SUITES = [
    ("hub", ["-m", "unittest", "discover", "-p", "test_*.py"]),
    ("extensions/dev", ["-m", "unittest", "test_dev"]),
    ("extensions/relay", ["-m", "unittest", "test_relay"]),
]

failed = []
for folder, args in SUITES:
    print(f"=== {folder}", flush=True)
    if subprocess.run([sys.executable, *args], cwd=ROOT / folder).returncode != 0:
        failed.append(folder)
print("失敗：" + "、".join(failed) if failed else "すべて成功")
sys.exit(1 if failed else 0)
