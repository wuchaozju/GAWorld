#!/bin/bash
# ============================================================
#  GAWorld × OpenClaw Bridge 启动脚本
#  启动 Relay Server + Bridge，将本机 OpenClaw 接入多智能体模拟
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GAWORLD_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$GAWORLD_DIR"

RELAY_PORT=8877
OPENCLAW_URL="http://127.0.0.1:18789"
SOUL_PATH="$GAWORLD_DIR/examples/openclaw/soul_gaworld.md"
CLUSTER="default"
LOG_DIR="$GAWORLD_DIR/output/distributed"

mkdir -p "$LOG_DIR"

echo "========================================"
echo "  GAWorld × OpenClaw Bridge Launcher"
echo "========================================"
echo ""

# --- 1. Check OpenClaw ---
echo "[1/3] 检查 OpenClaw Gateway..."
if curl -s --max-time 3 "$OPENCLAW_URL" > /dev/null 2>&1; then
    echo "  ✓ OpenClaw 在 $OPENCLAW_URL 运行中"
else
    echo "  ✗ 无法连接 OpenClaw ($OPENCLAW_URL)"
    echo "    请先启动 OpenClaw agent，然后重新运行此脚本"
    exit 1
fi

# --- 2. Start Relay Server ---
echo "[2/3] 启动 Relay Server (port $RELAY_PORT)..."

# Check if already running
if curl -s --max-time 2 "http://127.0.0.1:$RELAY_PORT/health" > /dev/null 2>&1; then
    echo "  ✓ Relay Server 已在运行"
else
    python3 -m gaworld.apps.distributed_comm_server \
        --host 0.0.0.0 \
        --port $RELAY_PORT \
        --state-path "$LOG_DIR/relay_state.json" \
        > "$LOG_DIR/relay_server.log" 2>&1 &
    RELAY_PID=$!
    echo "  启动中... (PID: $RELAY_PID)"
    sleep 2

    if curl -s --max-time 3 "http://127.0.0.1:$RELAY_PORT/health" > /dev/null 2>&1; then
        echo "  ✓ Relay Server 启动成功"
    else
        echo "  ✗ Relay Server 启动失败，查看日志: $LOG_DIR/relay_server.log"
        exit 1
    fi
fi

# --- 3. Start Bridge ---
echo "[3/3] 启动 OpenClaw Bridge..."
echo ""
echo "  SOUL: $SOUL_PATH"
echo "  Relay: http://127.0.0.1:$RELAY_PORT"
echo "  OpenClaw: $OPENCLAW_URL"
echo ""
echo "========================================"
echo "  Bridge 正在运行，按 Ctrl+C 停止"
echo "========================================"
echo ""

python3 scripts/openclaw_bridge.py \
    --relay-url "http://127.0.0.1:$RELAY_PORT" \
    --openclaw-url "$OPENCLAW_URL" \
    --soul-path "$SOUL_PATH" \
    --cluster "$CLUSTER" \
    --poll-interval 5
