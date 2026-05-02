"""
test_calibration.py - センサーキャリブレーションのテスト

使い方:
    $ python3 tests/test_calibration.py

またはプロジェクトルートから:
    $ cd /home/yappy/automatic-water-supply-pi/raspi
    $ python3 -m pytest tests/test_calibration.py -v
"""

import sys
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from logic.watering import normalize_sensor_value


def test_dry_greater_than_wet():
    dry, wet = 442, 297
    
    result = normalize_sensor_value(442, dry, wet)
    assert abs(result - 0.0) < 0.01, f"乾燥時: {result} (期待0.0)"  # 0.0=乾燥
    
    result = normalize_sensor_value(297, dry, wet)
    assert abs(result - 1.0) < 0.01, f"湿潤時: {result} (期待1.0)"  # 1.0=湿潤
    
    result = normalize_sensor_value(370, dry, wet)
    assert abs(result - 0.5) < 0.01, f"中間: {result} (期待~0.5)"
    
    print("✓ dry > wet (一般的センサー) OK")


def test_dry_less_than_wet():
    """dry < wet の場合 (逆特性のセンサー)"""
    dry, wet = 5, 47
    
    # 乾燥時
    result = normalize_sensor_value(5, dry, wet)
    assert abs(result - 0.0) < 0.01, f"乾燥時: {result} (期待0.0)"
    
    # 湿潤時
    result = normalize_sensor_value(47, dry, wet)
    assert abs(result - 1.0) < 0.01, f"湿潤時: {result} (期待1.0)"
    
    # 中間
    result = normalize_sensor_value(26, dry, wet)
    assert abs(result - 0.5) < 0.01, f"中間: {result} (期待~0.5)"
    
    print("✓ dry < wet (逆特性センサー) OK")


def test_boundary_values():
    dry, wet = 442, 297  # dry > wet: 大きい値=乾燥, 小さい値=湿潤

    # raw=0 は wet=297 より小さい → さらに湿潤側 → クランプで 1.0
    result = normalize_sensor_value(0, dry, wet)
    assert abs(result - 1.0) < 0.01, f"範囲外(小): {result} (期待1.0)"

    # raw=1023 は dry=442 より大きい → さらに乾燥側... だが dry側=湿潤=0.0
    # dry > wet なので大きい値ほど乾燥=1.0 ではなく、
    # normalize の符号に注意: (1023-442)/(297-442) = 負 → クランプで 0.0
    result = normalize_sensor_value(1023, dry, wet)
    assert abs(result - 0.0) < 0.01, f"範囲外(大): {result} (期待0.0)"

    print("✓ 境界値 OK")


def test_dry_equals_wet():
    """dry == wet の場合 (ゼロ除算防止)"""
    result = normalize_sensor_value(100, 500, 500)
    assert result == 0.5, f"dry==wet: {result} (期待0.5)"
    
    print("✓ dry == wet (ゼロ除算防止) OK")


def test_config_values():
    """config.yaml の設定値でのテスト"""
    sensor1_dry, sensor1_wet = 442, 297
    sensor2_dry, sensor2_wet = 5, 47

    # センサー1 (dry > wet): 0.0=乾燥, 1.0=湿潤
    assert abs(normalize_sensor_value(442, sensor1_dry, sensor1_wet) - 0.0) < 0.01
    assert abs(normalize_sensor_value(297, sensor1_dry, sensor1_wet) - 1.0) < 0.01

    # センサー2 (dry < wet): 0.0=乾燥, 1.0=湿潤
    assert abs(normalize_sensor_value(5, sensor2_dry, sensor2_wet) - 0.0) < 0.01
    assert abs(normalize_sensor_value(47, sensor2_dry, sensor2_wet) - 1.0) < 0.01

    print("✓ config.yaml 設定値 OK")


if __name__ == "__main__":
    print("=" * 50)
    print("  キャリブレーションテスト")
    print("=" * 50)
    
    test_dry_greater_than_wet()
    test_dry_less_than_wet()
    test_boundary_values()
    test_dry_equals_wet()
    test_config_values()
    
    print()
    print("=" * 50)
    print("  全テスト合格!")
    print("=" * 50)