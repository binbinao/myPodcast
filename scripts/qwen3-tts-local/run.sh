#!/bin/zsh
# Qwen3-TTS 本地服务启动器
#
#   ./run.sh                前台启动（Ctrl-C 停）
#   ./run.sh --daemon       后台启动，日志写 logs/server.log，pid 写 logs/server.pid
#   ./run.sh --stop         停止后台服务
#   ./run.sh --status       查看状态
#   ./run.sh --foreground-cpu  强制 CPU（调试用）
#
# 环境变量覆盖：
#   QWEN_TTS_VENV        Python 环境目录（独立 venv，含 torch/qwen-tts，不入库）
#   QWEN_TTS_MODEL_PATH  模型目录
#   QWEN_TTS_PORT        端口（默认 8100）
#   QWEN_TTS_DEVICE      mps | cpu
#   QWEN_TTS_DTYPE       float16 | float32
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="${QWEN_TTS_VENV:-/Users/jiduobin/.workbuddy/binaries/python/envs/qwen-tts}"
PY="$VENV/bin/python"
LOGDIR="$HERE/logs"
PORT="${QWEN_TTS_PORT:-8100}"

if [ ! -x "$PY" ]; then
  echo "✗ 未找到 Python 环境：$VENV"
  echo "  先执行：python3 -m venv $VENV && $VENV/bin/pip install qwen-tts torch torchaudio"
  exit 1
fi

MODEL="${QWEN_TTS_MODEL_PATH:-/Users/jiduobin/.workbuddy/models/Qwen3-TTS-12Hz-1.7B-CustomVoice}"
if [ ! -f "$MODEL/model.safetensors" ]; then
  echo "✗ 模型权重缺失：$MODEL/model.safetensors"
  exit 1
fi

mkdir -p "$LOGDIR"
PIDFILE="$LOGDIR/server.pid"

running() {
  [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null
}

case "${1:-}" in
  --stop)
    if running; then
      kill "$(cat "$PIDFILE")" && echo "✓ 已停止 (pid $(cat "$PIDFILE"))"
      rm -f "$PIDFILE"
    else
      echo "· 服务未在运行"
      # 兜底：清掉占端口的残留进程
      lsof -ti tcp:"$PORT" 2>/dev/null | xargs -r kill 2>/dev/null
    fi
    exit 0
    ;;
  --status)
    if running; then
      echo "✓ 运行中 (pid $(cat "$PIDFILE"), port $PORT)"
      curl -s --max-time 5 "http://127.0.0.1:$PORT/health" | "$PY" -m json.tool 2>/dev/null
    else
      echo "· 未运行"
    fi
    exit 0
    ;;
  --daemon)
    if running; then
      echo "· 已在运行 (pid $(cat "$PIDFILE"))，先 ./run.sh --stop"
      exit 0
    fi
    if lsof -ti tcp:"$PORT" >/dev/null 2>&1; then
      echo "✗ 端口 $PORT 已被占用："
      lsof -i tcp:"$PORT" | head -5
      exit 1
    fi
    cd "$HERE"
    nohup "$PY" server.py --port "$PORT" >> "$LOGDIR/server.log" 2>&1 &
    echo $! > "$PIDFILE"
    echo "· 启动中 (pid $(cat "$PIDFILE"))，日志：$LOGDIR/server.log"
    echo "· 等待模型加载 ..."
    for i in $(seq 1 90); do
      if curl -s --max-time 3 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
        echo "✓ 就绪：http://127.0.0.1:$PORT  （文档 http://127.0.0.1:$PORT/docs）"
        curl -s "http://127.0.0.1:$PORT/health" | "$PY" -m json.tool
        exit 0
      fi
      sleep 2
    done
    echo "✗ 90s 未就绪，检查日志：$LOGDIR/server.log"
    tail -30 "$LOGDIR/server.log"
    exit 1
    ;;
esac

# 前台
cd "$HERE"
ARGS=(server.py --port "$PORT")
[ "${1:-}" = "--foreground-cpu" ] && ARGS+=(--device cpu)
exec "$PY" "${ARGS[@]}"
