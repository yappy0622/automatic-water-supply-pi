"""
test_watering_logic.py - 給水ロジックのテスト

使い方:
    $ python3 tests/test_watering_logic.py

またはプロジェクトルートから:
    $ cd /home/yappy/automatic-water-supply-pi/raspi
    $ python3 -m pytest tests/test_watering_logic.py -v
"""

import sys
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from raspi.logic.watering import normalize_sensor_value


def test_threshold_comparison():
    """閾値判定のテスト"""
    # config.yaml の設定値
    soil_threshold = 0.4
    
    # テストケース: (生センサー値, 期待結果)
    # センサー1: dry=442, wet=297
    # センサー2: dry=5, wet=47
    
    test_cases = [
        # (sensor1_raw, sensor2_raw, 期待: True=給水不要, False=給水実行)
        ([442, 47], True),   # 両方湿潤 → 給水不要
        ([370, 30], True),   # 中間程度 → 給水不要
        ([442, 5], False),   # センサー1乾燥、センサー2乾燥 → 給水実行
        ([297, 47], True),   # 両方湿潤 → 給水不要
        ([442, 20], False),  # センサー1乾燥、センサー2中間 → 給水実行
    ]
    
    sensor1_dry, sensor1_wet = 442, 297
    sensor2_dry, sensor2_wet = 5, 47
    
    for raw_values, expected_no_watering in test_cases:
        # 正規化
        calibrated = [
            normalize_sensor_value(raw_values[0], sensor1_dry, sensor1_wet),
            normalize_sensor_value(raw_values[1], sensor2_dry, sensor2_wet),
        ]
        avg_moisture = sum(calibrated) / len(calibrated)
        
        # 判定
        should_not_water = avg_moisture >= soil_threshold
        
        status = "✓" if should_not_water == expected_no_watering else "✗"
        print(f"  生値{raw_values} → 正規化{calibrated} → 平均{avg_moisture:.2f} >= 閾値{soil_threshold}? {should_not_water} {status}")
        
        assert should_not_water == expected_no_watering, \
            f"生値{raw_values}: 期待{expected_no_watering}, 実際{should_not_water}"
    
    print("✓ 閾値判定 OK")


def test_full_flow():
    """全体フローのテスト"""
    # 設定
    config = {
        'soil_threshold': 0.4,
        'sensor1_dry': 442,
        'sensor1_wet': 297,
        'sensor2_dry': 5,
        'sensor2_wet': 47,
    }
    
    # テストケース
    test_cases = [
        # 説明, 生センサー値, 給水実行?
        ("乾燥状態", [440, 10], True),
        ("湿潤状態", [300, 40], False),
        ("境界線上", [370, 26], False),  # 平均 ≈ 0.5
    ]
    
    for desc, raw_soil, should_water in test_cases:
        # 正規化
        calibrated = [
            normalize_sensor_value(raw_soil[0], config['sensor1_dry'], config['sensor1_wet']),
            normalize_sensor_value(raw_soil[1], config['sensor2_dry'], config['sensor2_wet']),
        ]
        avg = sum(calibrated) / len(calibrated)
        
        # 判定
        will_water = avg < config['soil_threshold']
        
        status = "✓" if will_water == should_water else "✗"
        print(f"  {desc}: 生値{raw_soil} → 平均{avg:.2f} → {'給水実行' if will_water else '給水不要'} {status}")
        
        assert will_water == should_water, f"{desc}: 期待{'給水実行' if should_water else '給水不要'}"
    
    print("✓ 全体フロー OK")


if __name__ == "__main__":
    print("=" * 50)
    print("  給水ロジックテスト")
    print("=" * 50)
    
    test_threshold_comparison()
    print()
    test_full_flow()
    
    print()
    print("=" * 50)
    print("  全テスト合格!")
    print("=" * 50)
