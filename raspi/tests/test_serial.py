"""
test_serial.py - Arduino シリアルドライバの対話テスト

mock_arduino.py と組み合わせて、実機なしでドライバの全機能をテストする。

使い方:
    ターミナル1: python raspi/tests/mock_arduino.py
    ターミナル2: python raspi/tests/test_serial.py

    または実機接続時:
    $ python raspi/tests/test_serial.py --port /dev/ttyUSB0
"""

import sys
import os
import argparse
import time

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from arduino.serial_driver import (
    ArduinoDriver,
    ArduinoError,
    ArduinoNoWaterError,
    SensorReadAll,
)


def divider(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def test_ping(driver: ArduinoDriver) -> bool:
    divider("TEST: PING")
    result = driver.ping()
    print(f"  結果: {'OK' if result else 'FAIL'}")
    return result


def test_version(driver: ArduinoDriver) -> bool:
    divider("TEST: VERSION")
    try:
        version = driver.version()
        print(f"  バージョン: {version}")
        return True
    except ArduinoError as e:
        print(f"  エラー: {e}")
        return False


def test_read_soil(driver: ArduinoDriver) -> bool:
    divider("TEST: READ_SOIL")
    try:
        values = driver.read_soil()
        print(f"  土壌湿度: {values}")
        for i, v in enumerate(values):
            print(f"    センサー{i+1}: {v} (0=乾燥 / 1023=湿潤)")
        return True
    except ArduinoError as e:
        print(f"  エラー: {e}")
        return False


def test_read_water(driver: ArduinoDriver) -> bool:
    divider("TEST: READ_WATER")
    try:
        has_water = driver.read_water()
        status = "正常 (水あり)" if has_water else "警告: 水不足!"
        print(f"  水位: {status}")
        return True
    except ArduinoError as e:
        print(f"  エラー: {e}")
        return False


def test_read_dht(driver: ArduinoDriver) -> bool:
    divider("TEST: READ_DHT")
    try:
        temp, hum = driver.read_dht()
        print(f"  温度: {temp:.1f} °C")
        print(f"  湿度: {hum:.1f} %")
        return True
    except ArduinoError as e:
        print(f"  エラー: {e}")
        return False


def test_read_all(driver: ArduinoDriver) -> bool:
    divider("TEST: READ_ALL")
    try:
        data: SensorReadAll = driver.read_all()
        print(f"  土壌湿度 : {data.soil}")
        print(f"  水位     : {'正常' if data.water_ok else '不足'}")
        print(f"  温度     : {data.temperature} °C")
        print(f"  湿度     : {data.humidity} %")
        print(f"  ポンプ   : {'稼働中' if data.pump_running else '停止中'}")
        return True
    except ArduinoError as e:
        print(f"  エラー: {e}")
        return False


def test_pump_cycle(driver: ArduinoDriver) -> bool:
    divider("TEST: PUMP ON/OFF サイクル")
    try:
        # 状態確認
        is_running = driver.status_pump()
        print(f"  開始時のポンプ状態: {'ON' if is_running else 'OFF'}")

        # ON
        print("  ポンプ ON 送信...")
        driver.pump_on()
        time.sleep(0.5)
        is_running = driver.status_pump()
        print(f"  ポンプ状態: {'ON' if is_running else 'OFF'}")

        if not is_running:
            print("  FAIL: ポンプがONになっていません")
            return False

        # 3秒間稼働
        print("  3秒間稼働中...")
        time.sleep(3)

        # OFF
        print("  ポンプ OFF 送信...")
        driver.pump_off()
        time.sleep(0.5)
        is_running = driver.status_pump()
        print(f"  ポンプ状態: {'ON' if is_running else 'OFF'}")

        if is_running:
            print("  FAIL: ポンプがOFFになっていません")
            return False

        print("  OK: ポンプON/OFFサイクル正常")
        return True

    except ArduinoNoWaterError:
        print("  SKIP: 水位不足のためポンプテストをスキップ")
        return True
    except ArduinoError as e:
        print(f"  エラー: {e}")
        return False


def test_no_water_safety(driver: ArduinoDriver) -> bool:
    divider("TEST: 水不足時の安全機能")
    print("  ※ このテストは mock_arduino で 'water_empty' を")
    print("    実行してから行ってください")
    print()

    try:
        has_water = driver.read_water()
        if has_water:
            print("  SKIP: 水位は正常です (テストするには水位を不足にしてください)")
            return True

        print("  水位: 不足")
        print("  ポンプ ON 送信... (拒否されるはず)")
        driver.pump_on()
        print("  FAIL: ポンプONが拒否されませんでした")
        driver.pump_off()  # 安全のため停止
        return False

    except ArduinoNoWaterError:
        print("  OK: ERR:NO_WATER で正しく拒否されました")
        return True
    except ArduinoError as e:
        print(f"  エラー: {e}")
        return False


def run_all_tests(port: str):
    """全テストを実行"""
    print(f"Arduino シリアルドライバ テスト")
    print(f"ポート: {port}")

    results = {}

    try:
        with ArduinoDriver(port=port) as driver:
            results["PING"] = test_ping(driver)
            results["VERSION"] = test_version(driver)
            results["READ_SOIL"] = test_read_soil(driver)
            results["READ_WATER"] = test_read_water(driver)
            results["READ_DHT"] = test_read_dht(driver)
            results["READ_ALL"] = test_read_all(driver)
            results["PUMP_CYCLE"] = test_pump_cycle(driver)
            results["NO_WATER_SAFETY"] = test_no_water_safety(driver)

    except ArduinoError as e:
        print(f"\n接続エラー: {e}")
        return

    # 結果サマリー
    divider("テスト結果サマリー")
    passed = 0
    failed = 0
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        mark = "✓" if ok else "✗"
        print(f"  {mark} {name}: {status}")
        if ok:
            passed += 1
        else:
            failed += 1

    print()
    print(f"  合計: {passed} passed / {failed} failed / {len(results)} total")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Arduino シリアルドライバ テスト")
    parser.add_argument(
        "--port", default="/tmp/mock_arduino",
        help="シリアルポート (default: /tmp/mock_arduino)"
    )
    args = parser.parse_args()
    run_all_tests(args.port)
