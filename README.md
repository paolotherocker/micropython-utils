# micropython-utils

A small collection of dependency-free MicroPython utility drivers for embedded projects on the Raspberry Pi Pico (RP2040) and other `machine.Pin`-compatible boards.

| Module | Provides | Purpose |
|---|---|---|
| `utils.button` | `Button`, `ButtonEvent` | Debounced push-button with short-press / long-press detection |
| `utils.rotary` | `Rotary`, `RotaryEvent` | KY-040 quadrature rotary encoder driver (CW/CCW detection) |
| `utils.neopixelmanager` | `NeoPixelManager`, `Pattern`, `Solid`, `Off`, `Pulse` | Subset-based NeoPixel/WS2812B strip manager with static and animated patterns |

No external dependencies are required beyond the MicroPython standard `machine`, `neopixel`, `time`, `math`, and `micropython` modules — everything runs on stock firmware.

## Installation

### Option 1 — `mpremote mip install` (recommended)

With your board connected and `mpremote` installed on your host (`pip install mpremote`), install directly from GitHub:

```bash
mpremote mip install github:<your-username>/micropython-utils
```

This reads the repository's `package.json` and copies every file it lists to `/lib/utils/` on the device's filesystem — no manual file transfer needed.

To pin a specific tagged release instead of the default branch:

```bash
mpremote mip install github:<your-username>/micropython-utils@v0.1.0
```

To install to a custom target directory (e.g. if your project doesn't use `/lib`):

```bash
mpremote mip install --target /my_libs github:<your-username>/micropython-utils
```

You can also run this from a serial-connected board's own REPL, without a host copy of `mpremote`, using the built-in `mip` module:

```python
import mip
mip.install("github:<your-username>/micropython-utils")
```

### Option 2 — Manual copy with `mpremote fs`

If you'd rather vendor the source directly into your project (useful for offline builds or version-controlling the library alongside your firmware):

```bash
git clone https://github.com/<your-username>/micropython-utils.git
mpremote fs mkdir :/lib
mpremote fs cp -r micropython-utils/utils :/lib/
```

### `package.json` manifest (for reference)

This file lives at the repo root and is what `mip` reads for Option 1. Each entry is `[destination_on_device, source_in_repo]`, both relative to `package.json`'s own location:

```json
{
    "urls": [
        ["utils/__init__.py", "utils/__init__.py"],
        ["utils/button.py", "utils/button.py"],
        ["utils/rotary.py", "utils/rotary.py"],
        ["utils/neopixelmanager.py", "utils/neopixelmanager.py"]
    ],
    "version": "0.1.0"
}
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
