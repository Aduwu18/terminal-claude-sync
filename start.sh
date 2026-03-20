#!/bin/bash
# Terminal Claude Sync 启动脚本
# 用于在容器环境中挂载即用

set -e

export TERMINAL_SYNC_DIR=${TERMINAL_SYNC_DIR:-/libs/terminal-claude-sync}

# Python 路径：包含依赖目录和源码目录
export PYTHONPATH=$TERMINAL_SYNC_DIR/libs:$TERMINAL_SYNC_DIR:$PYTHONPATH

echo "=========================================="
echo "Terminal Claude Sync"
echo "Working Dir: $TERMINAL_SYNC_DIR"
echo "=========================================="

cd $TERMINAL_SYNC_DIR

case "${1:-bridge}" in
    bridge)
        echo "Starting Bridge Server..."
        exec python -m src.bridge
        ;;
    client)
        shift
        echo "Starting Terminal Client..."
        exec python -m src.terminal_client "$@"
        ;;
    *)
        echo "Usage: $0 {bridge|client [options]}"
        echo ""
        echo "Commands:"
        echo "  bridge   - Start the bridge server (default)"
        echo "  client   - Start the terminal client"
        echo ""
        echo "Client options:"
        echo "  --cli-mode <pty|print>  CLI mode (default: print)"
        echo "  --sync-mode <notify|sync>  Sync mode (default: notify)"
        echo "  --debug  Enable debug logging"
        exit 1
        ;;
esac