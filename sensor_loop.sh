#!/bin/bash
# sensor_loop.sh

PORT=/dev/ttyUSB0
INTERVAL=2        # 読み取り間隔（秒）
COMMAND="READ_ALL"

# シリアルポート設定（一度だけ）
stty -F "$PORT" 9600 cs8 -cstopb -parenb raw -echo

# Ctrl+C時の終了処理
cleanup() {
    kill "$CAT_PID" 2>/dev/null
    wait "$CAT_PID" 2>/dev/null
    echo ""
    echo "終了"
    exit 0
}
trap cleanup INT TERM

echo "センサ読み取り開始 (Ctrl+C で終了)"

# 受信はバックグラウンドで起動しっぱなし（ループの外）
cat "$PORT" &
CAT_PID=$!

# READY待ち
sleep 2

while true; do
    printf "%s\r\n" "$COMMAND" > "$PORT"
    sleep "$INTERVAL"
done
