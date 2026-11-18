#!/bin/sh
# ai-org のフックから共通で読み込む。リポジトリ固有のフックを続けて呼ぶ。
# 呼ぶ先：git config ai-org.chainHooksPath（以前 core.hooksPath を使っていた場合はその場所を設定する）。
#         設定がなければ、共通の .git/hooks（worktree でも同じ場所。--git-common-dir を使う）。
ai_org_chain() {
  name="$1"; shift
  chain_dir="$(git config --get ai-org.chainHooksPath)"
  if [ -z "$chain_dir" ]; then
    common="$(git rev-parse --git-common-dir)" || exit 1
    chain_dir="$common/hooks"
  fi
  case "$chain_dir" in
    /*|[A-Za-z]:*) ;;
    *) chain_dir="$(git rev-parse --show-toplevel)/$chain_dir" ;;
  esac
  here_dir="$(cd "$(dirname "$0")" && pwd -P)"
  target_dir="$(cd "$chain_dir" 2>/dev/null && pwd -P)"
  # 自分自身（ai-org のフック置き場）を呼び続けないようにする
  if [ -n "$target_dir" ] && [ "$target_dir" != "$here_dir" ] && [ -x "$target_dir/$name" ]; then
    exec "$target_dir/$name" "$@"
  fi
  exit 0
}