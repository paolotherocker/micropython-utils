import utime as time
from utils.ky040 import KY040, RotaryEvent
from machine import Pin

rotary = KY040(dt_pin=2, clk_pin=3)

while True:
    evt = rotary.consume()
    if evt == RotaryEvent.CW:
        print("CW")
    elif evt == RotaryEvent.CCW:
        print("CCW")
    time.sleep_ms(10)
