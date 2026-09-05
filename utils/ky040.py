"""
ky040.py

Quadrature-transition based KY-040 rotary encoder driver for MicroPython
(Raspberry Pi Pico or any board with machine.Pin IRQ support).

No switch (SW) handling is included; this module only reports rotation
direction. Type enforcement is done manually since MicroPython has no
`enum` module in the base build.

See ../examples/ky040/main.py for usage
"""

from machine import Pin, disable_irq, enable_irq
import utime as time


class RotaryEvent:
    """Namespace of rotary direction constants."""

    NONE = 0  # no event since the last consume()
    CW = 1    # clockwise step
    CCW = 2   # counter-clockwise step


class KY040:
    """Quadrature-transition based KY-040 rotary encoder reader."""

    def __init__(
        self,
        dt_pin: int,
        clk_pin: int,
        pull: int = Pin.PULL_UP,
        debounce_ms: int = 2,
    ) -> None:
        """
        Args:
            dt_pin (int): DT pin ID number.
            clk_pin (int): CLK pin ID number.
            pull (int, optional): Pin.PULL_UP, Pin.PULL_DOWN, or None.
            debounce_ms (int, optional): Debounce time in ms.

        Raises:
            ValueError: if dt_pin and clk_pin are the same pin, or if
                debounce_ms is negative.
        """
        if dt_pin == clk_pin:
            raise ValueError("dt_pin and clk_pin must be different pins")
        if debounce_ms < 0:
            raise ValueError("debounce_ms must be >= 0")

        self._dt_pin = Pin(dt_pin, Pin.IN, pull)
        self._clk_pin = Pin(clk_pin, Pin.IN, pull)
        self._debounce_ms = debounce_ms

        self._last_status = self._read_status()
        self._last_change_ms = time.ticks_ms()
        self._position_delta = 0

        # Rest state captured here so the transition table adapts to
        # whichever pull configuration is wired, instead of assuming
        # both pins idle high. CW is defined as "CLK bit flips first
        # out of rest"; CCW as "DT bit flips first out of rest".
        rest = self._last_status
        self._transition_cw = (rest << 2) | (rest ^ 0b01)
        self._transition_ccw = (rest << 2) | (rest ^ 0b10)

        self._dt_pin.irq(self._on_pin_change, Pin.IRQ_RISING | Pin.IRQ_FALLING)
        self._clk_pin.irq(self._on_pin_change, Pin.IRQ_RISING | Pin.IRQ_FALLING)

    def _read_status(self) -> int:
        """Pack DT/CLK pin levels into a 2-bit int: (dt << 1) | clk."""
        dt_val = self._dt_pin.value()
        clk_val = self._clk_pin.value()
        return (dt_val << 1) | clk_val

    def _on_pin_change(self, pin: Pin) -> None:
        """IRQ handler for both DT and CLK pins.

        Runs in hard-IRQ context (MicroPython default for Pin.irq()):
        no heap allocation is permitted here. Keep this body limited
        to integer arithmetic and attribute assignment; anything that
        allocates (list/dict/str construction, etc.) will raise inside
        the ISR and be dropped rather than propagated.

        Args:
            pin (Pin): the pin that triggered the interrupt.
        """
        new_status = self._read_status()
        if new_status == self._last_status:
            return

        now = time.ticks_ms()
        in_debounce = time.ticks_diff(now, self._last_change_ms) < self._debounce_ms

        # Resync tracked state on every real edge, even a debounced
        # one, so a later accepted edge is classified against the
        # true prior state rather than a stale one.
        transition = (self._last_status << 2) | new_status
        self._last_status = new_status

        if in_debounce:
            return

        if transition == self._transition_cw:
            self._position_delta += 1
        elif transition == self._transition_ccw:
            self._position_delta -= 1
        # any other transition value is a bounce/invalid step; ignored

        self._last_change_ms = now

    def consume(self) -> int:
        """Return and clear the net rotary event since the last call.

        Multiple same-direction steps between calls collapse into a
        single event; opposite-direction steps can cancel to NONE.

        Returns:
            RotaryEvent: NONE, CW, or CCW.
        """
        state = disable_irq()
        delta = self._position_delta
        self._position_delta = 0
        enable_irq(state)

        if delta > 0:
            return RotaryEvent.CW
        if delta < 0:
            return RotaryEvent.CCW
        return RotaryEvent.NONE
