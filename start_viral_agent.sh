#!/bin/bash
# 启动爆款文案智能体 UI

cd "$(dirname "$0")"

# 本地密钥放在 .env 中；.env 已被 .gitignore 忽略
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

echo "🚀 启动爆款文案智能体 Web 界面..."
echo ""

# 使用 conda 环境的 Python
/opt/miniconda3/bin/python viral_agent_ui.py
