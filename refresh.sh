#!/bin/bash
# 运营方 Mac 端每小时任务（launchd 调用）：
#   1) 拉取最新代码；2) 抓取"登录类场馆"(RIOC/Prospect/Columbia) -> login_data.json；
#   3) 提交并 push 到托管仓库（GitHub Pages 由此获得登录场馆数据）。
# 免登录场馆由 GitHub Actions 云端抓取，本脚本不碰。
set -o pipefail
cd "$(dirname "$0")" || exit 1        # 脚本所在目录即项目目录（与位置无关）
PY="${TENNIS_PY:-/opt/anaconda3/bin/python3}"
mkdir -p logs
{
  echo "===== $(date '+%F %T') login refresh start ====="
  git pull --rebase --autostash origin main || echo "git pull 跳过/失败，继续"
  "$PY" pipeline.py --login-only
  git add login_data.json
  if git diff --staged --quiet; then
    echo "login_data 无变化，跳过 push"
  else
    git commit -m "chore: refresh login data [skip ci]"
    for i in 1 2 3; do
      git pull --rebase --autostash origin main && git push && break || sleep 5
    done
  fi
  echo "===== $(date '+%F %T') done ====="
} >> logs/refresh.log 2>&1
