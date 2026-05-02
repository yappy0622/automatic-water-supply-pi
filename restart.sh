#!/bin/bash
cd /home/yappy/automatic-water-supply-pi/raspi

PIDFILE="watering.pid"
VENV_PATH="/home/yappy/automatic-water-supply-pi/raspi/venv"

# 既存プロセスを止める
if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "既存プロセス (PID: $PID) を終了"
        kill "$PID"
        sleep 2
    fi
    rm "$PIDFILE"
fi

# 仮想環境を有効化
source "$VENV_PATH/bin/activate"

# 起動してPIDを保存
nohup python main.py > /dev/null 2>&1 &
echo $! > "$PIDFILE"
echo "起動しました (PID: $!)"