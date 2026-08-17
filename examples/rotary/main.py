import utime as time
from lib_common.rotary import Rotary, RotaryEvent
from machine import Pin

rotary = Rotary(dt_pin=2, clk_pin=3)

while True:
    evt = rotary.consume()
    if evt == RotaryEvent.CW:
        print("CW")
    elif evt == RotaryEvent.CCW:
        print("CCW")
    time.sleep_ms(10)
