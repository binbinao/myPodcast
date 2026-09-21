#!/bin/zsh
# 启动本机 Qwen3-TTS 服务（backend=qwen3-local 时必需）。
#
#   ./scripts/start-qwen-tts-local.sh           后台启动
#   ./scripts/start-qwen-tts-local.sh --stop    停止
#   ./scripts/start-qwen-tts-local.sh --status  状态
#   ./scripts/start-qwen-tts-local.sh --fg      前台启动（看实时输出）
#
# 服务实现体就在本仓库内：scripts/qwen3-tts-local/
# 只有两样在仓库外（体积大 + 与仓库依赖冲突，故不入库）：
#   - 模型权重  ~/.workbuddy/models/Qwen3-TTS-12Hz-1.7B-CustomVoice  (~4.2GB)
#   - 独立 venv ~/.workbuddy/binaries/python/envs/qwen-tts           (~1.5GB)
# 重建步骤见 scripts/qwen3-tts-local/README.md。
#
# 以下路径均可用环境变量覆盖，换机器/换路径不用改脚本。
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"

# 默认指向仓库内自带实现体；QWEN_TTS_TOOL_DIR 可指向别处的副本
TOOL="${QWEN_TTS_TOOL_DIR:-$HERE/qwen3-tts-local}"
VENV="${QWEN_TTS_VENV:-/Users/jiduobin/.workbuddy/binaries/python/envs/qwen-tts}"
MODEL="${QWEN_TTS_MODEL_PATH:-/Users/jiduobin/.workbuddy/models/Qwen3-TTS-12Hz-1.7B-CustomVoice}"
PORT="${QWEN_TTS_PORT:-8100}"

if [ ! -x "$TOOL/run.sh" ]; then
  echo "✗ 未找到服务实现体：$TOOL/run.sh"
  echo "  默认应在仓库内 scripts/qwen3-tts-local/；用 QWEN_TTS_TOOL_DIR=<路径> 覆盖。"
  exit 1
fi
if [ ! -x "$VENV/bin/python" ]; then
  echo "✗ Python 环境缺失：$VENV"
  echo "  重建：python3 -m venv $VENV && $VENV/bin/pip install qwen-tts torch torchaudio"
  echo "  详见 scripts/qwen3-tts-local/README.md"
  exit 1
fi
if [ ! -f "$MODEL/model.safetensors" ]; then
  echo "✗ 模型权重缺失：$MODEL/model.safetensors"
  echo "  下载见 scripts/qwen3-tts-local/README.md"
  exit 1
fi

case "${1:-}" in
  --fg)     exec "$TOOL/run.sh" ;;
  --stop)   exec "$TOOL/run.sh" --stop ;;
  --status) exec "$TOOL/run.sh" --status ;;
  *)        exec "$TOOL/run.sh" --daemon ;;
esac
