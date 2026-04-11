"""
mock_arduino.py - Arduino シミュレータ

実機がなくてもラズパイ側のコードを開発・テストできるようにする
仮想シリアルポート (pty) を使ってArduinoの応答をシミュレートする。

使い方:
    $ python mock_arduino.py

    別ターミナルで:
    $ python -c "
    from arduino.serial_driver import ArduinoDriver
    d = ArduinoDriver('/tmp/mock_arduino')
    d.open()
    print(d.read_soil())
    d.close()
    "

    または対話的テスト:
    $ python test_serial.py /tmp/mock_arduino
"""

import os
import pty
import select
import signal
import sys
import termios
import tty
import time
import random
import argparse

# シミュレーション用の内部状態
state = {
    "pump": False,
    "pump_start_time": 0,
    "water_level": 1,       # 1 = 水あり, 0 = 水不足
    "soil_base": [450, 430], # ベースライン土壌湿度
    "temperature": 25.0,
    "humidity": 60.0,
    "light_lux": 500.0,     # 照度 (lux)
    "ec_value": 1.2,        # EC (mS/cm) 土壌電気伝導度
}

PUMP_TIMEOUT = 60  # 秒
FW_NAME = "WateringDriver"
FW_VERSION = "1.2.0"


def simulate_soil() -> list[int]:
    """ノイズ付きの土壌湿度値を生成"""
    values = []
    for base in state["soil_base"]:
        if state["pump"]:
            elapsed = time.time() - state["pump_start_time"]
            base += int(elapsed * 10)
        noise = random.randint(-15, 15)
        values.append(max(0, min(1023, base + noise)))
    return values


def process_command(cmd: str) -> str:
    """コマンドを処理してレスポンスを返す"""
    cmd = cmd.strip()

    if not cmd:
        return ""

    # ポンプタイムアウトチェック
    if state["pump"]:
        elapsed = time.time() - state["pump_start_time"]
        if elapsed >= PUMP_TIMEOUT:
            state["pump"] = False
            state["pump_start_time"] = 0
            return "WARN:PUMP_TIMEOUT"

    if cmd == "PING":
        return "PONG"

    elif cmd == "VERSION":
        return f"VERSION:{FW_NAME},{FW_VERSION}"

    elif cmd == "READ_SOIL":
        values = simulate_soil()
        return "SOIL:" + ",".join(str(v) for v in values)

    elif cmd == "READ_WATER":
        return f"WATER:{state['water_level']}"

    elif cmd == "READ_LIGHT":
        # 照度シミュレーション (0 - 10000 lux)
        lux = state["light_lux"] + random.uniform(-20.0, 20.0)
        lux = max(0.0, lux)
        return f"LIGHT:{lux:.1f}"

    elif cmd == "READ_EC":
        ec = state["ec_value"] + random.uniform(-0.05, 0.05)
        ec = max(0.0, ec)
        return f"EC:{ec:.2f}"

    elif cmd == "READ_DHT":
        temp = state["temperature"] + random.uniform(-0.5, 0.5)
        hum = state["humidity"] + random.uniform(-2.0, 2.0)
        return f"DHT:{temp:.1f},{hum:.1f}"

    elif cmd == "READ_ALL":
        soil_vals = simulate_soil()
        soil_str = ",".join(str(v) for v in soil_vals)
        temp = state["temperature"] + random.uniform(-0.5, 0.5)
        hum = state["humidity"] + random.uniform(-2.0, 2.0)
        pump_str = "ON" if state["pump"] else "OFF"
        lux = state["light_lux"] + random.uniform(-20.0, 20.0)
        lux = max(0.0, lux)
        ec = state["ec_value"] + random.uniform(-0.05, 0.05)
        ec = max(0.0, ec)
        return f"SOIL:{soil_str};WATER:{state['water_level']};DHT:{temp:.1f},{hum:.1f};LIGHT:{lux:.1f};EC:{ec:.2f};PUMP:{pump_str}"

    elif cmd == "PUMP_ON":
        if state["water_level"] == 0:
            return "ERR:NO_WATER"
        state["pump"] = True
        state["pump_start_time"] = time.time()
        return "OK:PUMP_ON"

    elif cmd == "PUMP_OFF":
        state["pump"] = False
        state["pump_start_time"] = 0
        return "OK:PUMP_OFF"

    elif cmd == "STATUS_PUMP":
        return "PUMP:" + ("ON" if state["pump"] else "OFF")

    else:
        return f"ERR:UNKNOWN_CMD:{cmd}"


def run_mock(link_path: str = "/tmp/mock_arduino"):
    """仮想シリアルポートを作成してArduinoをシミュレート"""
    master, slave = pty.openpty()
    slave_name = os.ttyname(slave)

    # pty のエコーバックを無効にする (重要!)
    # これがないと送信データが自分自身に返ってきてループする
    attrs = termios.tcgetattr(slave)
    attrs[3] = attrs[3] & ~termios.ECHO  # ローカルフラグからECHOを除去
    termios.tcsetattr(slave, termios.TCSANOW, attrs)

    # raw モード: 改行変換等を無効化
    tty.setraw(master)

    # シンボリックリンクを作成
    if os.path.exists(link_path):
        os.remove(link_path)
    os.symlink(slave_name, link_path)

    print(f"=== Mock Arduino 起動 ===")
    print(f"  実ポート : {slave_name}")
    print(f"  リンク   : {link_path}")
    print(f"  ボーレート: 9600 (シミュレーション)")
    print()
    print("操作コマンド (このターミナルで入力):")
    print("  water_empty  - 水位を「不足」にする")
    print("  water_full   - 水位を「正常」に戻す")
    print("  dry          - 土壌を「乾燥」状態にする (値: 200台)")
    print("  wet          - 土壌を「湿潤」状態にする (値: 600台)")
    print("  bright       - 照度を「明るい」に (値: 5000 lux)")
    print("  dark         - 照度を「暗い」に (値: 50 lux)")
    print("  ec_high      - ECを「高い」に (値: 3.0 mS/cm)")
    print("  ec_low       - ECを「低い」に (値: 0.3 mS/cm)")
    print("  quit         - 終了")
    print()
    print("待機中... (ラズパイ側から接続してください)")
    print()
    sys.stdout.flush()

    # Ctrl+C で終了
    running = True
    def signal_handler(sig, frame):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, signal_handler)

    buf = b""

    # READY メッセージはドライバが接続してから送信するのではなく、
    # 実機のArduinoと同じく起動直後にバッファに入れておく
    ready_msg = f"READY:{FW_NAME},{FW_VERSION}\n"
    os.write(master, ready_msg.encode("ascii"))

    while running:
        try:
            readable, _, _ = select.select([master, sys.stdin], [], [], 0.1)
        except (OSError, ValueError):
            break

        for fd in readable:
            if fd == master:
                try:
                    data = os.read(master, 1024)
                except OSError:
                    continue

                if not data:
                    continue

                buf += data

                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    cmd = line.decode("ascii", errors="ignore").strip()
                    # \r を除去
                    cmd = cmd.replace("\r", "")
                    if cmd:
                        print(f"  [RX] {cmd}")
                        sys.stdout.flush()
                        response = process_command(cmd)
                        if response:
                            print(f"  [TX] {response}")
                            sys.stdout.flush()
                            os.write(master, (response + "\n").encode("ascii"))

            elif fd == sys.stdin:
                user_input = sys.stdin.readline().strip().lower()

                if user_input == "water_empty":
                    state["water_level"] = 0
                    print("  >> 水位: 不足")
                elif user_input == "water_full":
                    state["water_level"] = 1
                    print("  >> 水位: 正常")
                elif user_input == "dry":
                    state["soil_base"] = [220, 200]
                    print("  >> 土壌: 乾燥 (200台)")
                elif user_input == "wet":
                    state["soil_base"] = [620, 600]
                    print("  >> 土壌: 湿潤 (600台)")
                elif user_input == "bright":
                    state["light_lux"] = 5000.0
                    print("  >> 照度: 明るい (5000 lux)")
                elif user_input == "dark":
                    state["light_lux"] = 50.0
                    print("  >> 照度: 暗い (50 lux)")
                elif user_input == "ec_high":
                    state["ec_value"] = 3.0
                    print("  >> EC: 高い (3.0 mS/cm)")
                elif user_input == "ec_low":
                    state["ec_value"] = 0.3
                    print("  >> EC: 低い (0.3 mS/cm)")
                elif user_input == "quit":
                    running = False
                elif user_input:
                    print(f"  >> 不明なコマンド: {user_input}")
                sys.stdout.flush()

    # クリーンアップ
    os.close(master)
    os.close(slave)
    if os.path.exists(link_path):
        os.remove(link_path)
    print("\nMock Arduino 終了")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Arduino モックシミュレータ")
    parser.add_argument(
        "--port", default="/tmp/mock_arduino",
        help="仮想ポートのリンクパス (default: /tmp/mock_arduino)"
    )
    args = parser.parse_args()
    run_mock(args.port)
