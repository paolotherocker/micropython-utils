from machine import Pin
from lib_common.neopixelmanager import NeoPixelManager, Pulse
import time

PIN_NUM = 15
NUM_PIXELS = 16

# Create the strip manager and start with everything off.
np = NeoPixelManager(PIN_NUM, NUM_PIXELS)
np.clear()
np.write()

np.add_subset(8)
np.add_subset(8)

# Trigger a pulse across all 16 pixels, breathing between red and off,
# once every 2 seconds.
np.set_pattern(
    Pulse(
        color1=(0, 32, 200),
        color2=(0, 64, 200),
        period_ms=2000,
    ),
    id=0,
)

np.set_pattern(
    Pulse(
        color1=(0, 200, 32),
        color2=(0, 200, 96),
        period_ms=2000,
    ),
    id=1,
)

print("Pulsing... press Ctrl+C to stop")

try:
    while True:
        np.poll()  # recompute pulse colours and push to the strip
        time.sleep_ms(20)
except KeyboardInterrupt:
    pass
finally:
    np.reset()
    np.write()
    print("Stopped and cleared strip")
