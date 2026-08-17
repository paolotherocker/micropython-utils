# micropython-utils

A small collection of dependency-free MicroPython utility drivers for embedded projects on the Raspberry Pi Pico (RP2040) and other `machine.Pin`-compatible boards.

| Module | Provides | Purpose |
|---|---|---|
| `utils.button` | `Button`, `ButtonEvent` | Debounced push-button with short-press / long-press detection |
| `utils.rotary` | `Rotary`, `RotaryEvent` | KY-040 quadrature rotary encoder driver (CW/CCW detection) |
| `utils.neopixelmanager` | `NeoPixelManager`, `Pattern`, `Solid`, `Off`, `Pulse` | Subset-based NeoPixel/WS2812B strip manager with static and animated patterns |

No external dependencies are required beyond the MicroPython standard `machine`, `neopixel`, `time`, `math`, and `micropython` modules — everything runs on stock firmware.

## Installation

With your board connected and `mpremote` installed on your host (`pip install mpremote`), install directly from GitHub:

```bash
mpremote mip install github:paolotherocker/micropython-utils
```

## Using the Library in Your Project

Once installed, `utils` sits in `/lib` on the device, which is automatically on MicroPython's module search path — no `sys.path` changes needed. Import whichever submodules you need:

```python
from utils.button import Button, ButtonEvent
from utils.rotary import Rotary, RotaryEvent
from utils.neopixelmanager import NeoPixelManager, Solid, Off, Pulse
```

## License

see `LICENSE`.
