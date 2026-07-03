#!/usr/bin/env bash
# Stop-hook: nếu code (backend *.py / frontend *.dart) mới hơn docs/structure.md
# thì chặn việc dừng và nhắc Claude chạy /sync-docs trước khi kết thúc.
# stop_hook_active=true => đã chặn 1 lần rồi, thoát để tránh vòng lặp.

input=$(cat)
case "$input" in
  *'"stop_hook_active":true'*) exit 0 ;;
esac

root="${CLAUDE_PROJECT_DIR:-.}"
docs="$root/.claude/docs/structure.md"
[ -f "$docs" ] || exit 0

changed=$(find "$root/backend" "$root/frontend/lib" -type f \
  \( -name '*.py' -o -name '*.dart' \) \
  ! -name '*.g.dart' ! -name '*.freezed.dart' \
  -newer "$docs" 2>/dev/null | head -5)

if [ -n "$changed" ]; then
  printf '{"decision":"block","reason":"Code da thay doi nhung tai lieu chua duoc dong bo. Hay chay /sync-docs de cap nhat .claude/docs/ va CLAUDE.md cho khop code. Neu da sync roi hoac thay doi khong dang ke, bao user va dung lai."}\n'
fi
exit 0
