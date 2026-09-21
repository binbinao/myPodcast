#!/bin/zsh
# 启动本机 Qwen3-TTS 服务（backend=qwen3-local 时必需）。
#
#   ./scripts/start-qwen-tts-local.sh           后台启动
#   ./scripts/start-qwen-tts-local.sh --stop    停止
#   ./scripts/start-qwen-tts-local.sh --status  状态
#   ./scripts/start-qwen-tts-local.sh --fg      前台启动（看实时输出）
#
# 真正的实现在独立工具目录（模型环境与播客仓库的 Python 环境互相隔离）：
#   ~/Documents/GitHub/Personal/qwen3-tts-local/
set -u

TOOL="${QWEN_TTS_TOOL_DIR:-/Users/jiduobin/Documents/GitHub/Personal/qwen3-tts-local}"
VENV="/Users/jiduobin/.workbuddy/binaries/python/envs/qwen-tts"
MODEL="${QWEN_TTS_MODEL_PATH:-/Users/jiduobin/.workbuddy/models/Qwen3-TTS-12Hz-1.7B-CustomVoice}"
PORT="${QWEN_TTS_PORT:-8100}"

if [ ! -x "$TOOL/run.sh" ]; then
  echo "✗ 未找到本地 TTS 工具目录：$TOOL/run.sh"
  echo "  用 QWEN_TTS_TOOL_DIR=<路径> 指定。"
  exit 1
fi
if [ ! -x "$VENV/bin/python" ]; then
  echo "✗ Python 环境缺失：$VENV"
  exit 1
fi
if [ ! -f "$MODEL/model.safetensors" ]; then
  echo "✗ 模型权重缺失：$MODEL/model.safetensors"
  echo "  下载见 $TOOL/README.md"
  exit 1
fi

case "${1:-}" in
  --fg)     exec "$TOOL/run.sh" ;;
  --stop)   exec "$TOOL/run.sh" --stop ;;
  --status) exec "$TOOL/run.sh" --status ;;
  *)        exec "$TOOL/run.sh" --daemon ;;
esac
