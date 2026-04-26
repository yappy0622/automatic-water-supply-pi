#!/bin/bash
PORT=/dev/ttyUSB0
TIMEOUT=1000

stty -F "$PORT" 9600 cs8 -cstopb -parenb raw -echo

cleanup() {
    printf "PUMP_OFF\r\n" > "$PORT"
    kill "$CAT_PID" 2>/dev/null
    wait "$CAT_PID" 2>/dev/null
    echo ""
    echo "ポンプ OFF"
    echo "水やり終了"
    exit 0
}

trap cleanup INT TERM HUP

echo "水やり開始 (E で停止 / 最大 ${TIMEOUT}秒で自動停止)"

# 受信をバックグラウンドで起動しっぱなし
cat "$PORT" &
CAT_PID=$!

# READY待ち
sleep 2

printf "PUMP_ON\r\n" > "$PORT"
echo "ポンプ ON"

START=$SECONDS
while true; do
    ELAPSED=$((SECONDS - START))
    REMAINING=$((TIMEOUT - ELAPSED))

    if [[ $REMAINING -le 0 ]]; then
        echo ""
        echo "⚠ タイムアウト：自動停止します"
        cleanup
    fi

    printf "\r残り時間: %d秒   " "$REMAINING"

    if read -r -n 1 -t 1 key; then
        if [[ "$key" == "E" ]] || [[ "$key" == "e" ]]; then
            cleanup
        fi
    fi
done
