#!/bin/sh
# ai-org のフックから共通で読み込む。頻繁に動く reference-transaction・post-index-change は、動作が遅くなるため包まない。リポジトリ固有のフックを続けて呼ぶ。
# 呼ぶ先：git config ai-org.chainHooksPath（以前 core.hooksPath を使っていた場合はその場所を設定する）。
#         設定がなければ、共通の .git/hooks（worktree でも同じ場所。--git-common-dir を使う）。
ai_org_chain() {
  name="$1"; shift
  chain_dir="$(git config --get ai-org.chainHooksPath)"
  if [ -z "$chain_dir" ]; then
    common="$(git rev-parse --git-common-dir)" || exit 1
    chain_dir="$common/hooks"
  fi
  # 相対パスは、git がフックを動かすフォルダー（作業ツリーの最上位、bare リポジトリでは git ディレクトリ）を基準にする
  here_dir="$(cd "$(dirname "$0")" && pwd -P)"
  if [ ! -d "$chain_dir" ]; then
    # 設定した置き場が見つからないときは知らせる（固有フックが黙って抜けないように）
    if [ -n "$(git config --get ai-org.chainHooksPath)" ]; then
      echo "[ai-org] 注意：ai-org.chainHooksPath の置き場 $chain_dir が見つからないため、固有の $name フックを呼べません。" >&2
    fi
    exit 0
  fi
  target_dir="$(cd "$chain_dir" 2>/dev/null && pwd -P)"
  # 自分自身（ai-org のフック置き場）を呼び続けないようにする
  if [ -n "$target_dir" ] && [ "$target_dir" != "$here_dir" ] && [ -x "$target_dir/$name" ]; then
    exec "$target_dir/$name" "$@"
  fi
  exit 0
}