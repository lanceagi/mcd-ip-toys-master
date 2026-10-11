#!/bin/bash
# 一键测试:结构自检 + 离线全量 + (可选)在线只读。
# bash run_all_tests.sh          # 离线
# bash run_all_tests.sh --full   # 追加真实 MCP 在线项(只读)
set -u
cd "$(dirname "$0")"
rc=0
run() {
  echo
  echo "===== $1 ====="
  shift
  "$@" || rc=1
}
run "结构自检(离线)" python3 scripts/selftest.py
run "流程与门禁测试(离线,假 API)" python3 scripts/test_toys.py
if [ "${1:-}" = "--full" ]; then
  run "在线自检(真实 MCP,只读)" python3 scripts/selftest.py --full
fi
echo
if [ "$rc" -eq 0 ]; then
  echo "✅ run_all_tests 全绿"
else
  echo "❌ 存在失败,退出码非零"
fi
exit $rc
