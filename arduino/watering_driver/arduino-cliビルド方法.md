# arduino-cliビルド方法

```
arduino-cli compile --fqbn arduino:avr:nano watering_driver.ino

arduino-cli upload -p /dev/ttyUSB0 --fqbn arduino:avr:nano:cpu=atmega328old watering_driver.ino
```