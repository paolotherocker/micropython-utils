"""
ky040.py

Quadrature-transition based KY-040 rotary encoder driver for MicroPython
(Raspberry Pi Pico or any board with machine.Pin IRQ support).

No switch (SW) handling is included; this module only reports rotation
direction. Type enforcement is done manually since MicroPython has no
`enum` module in the base build.

See ../examples/ky040/main.py for usage
"""

from machine import Pin
import utime as time


class RotaryEvent:
    """Namespace of rotary direction constants."""

    NONE = 0  # no event since the last consume()
    CW = 1  # clockwise step
    CCW = 2  # counter-clockwise step


class KY040:
    """Quadrature-transition based KY-040 rotary encoder reader."""

    # Transition table values, expressed as (last_status << 2) | new_status
    _TRANSITION_CW = 0b1110
    _TRANSITION_CCW = 0b1101

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
        """
        self._dt_pin = Pin(dt_pin, Pin.IN, pull)
        self._clk_pin = Pin(clk_pin, Pin.IN, pull)
        self._debounce_ms = debounce_ms

        self._last_status = self._read_status()
        self._last_event = RotaryEvent.NONE
        self._last_change_ms = time.ticks_ms()

        self._dt_pin.irq(self._on_pin_change, Pin.IRQ_RISING | Pin.IRQ_FALLING)
        self._clk_pin.irq(self._on_pin_change, Pin.IRQ_RISING | Pin.IRQ_FALLING)

    def _read_status(self) -> int:
        """Pack DT/CLK pin levels into a 2-bit int: (dt << 1) | clk."""
        dt_val = self._dt_pin.value()
        clk_val = self._clk_pin.value()
        return (dt_val << 1) | clk_val

    def _on_pin_change(self, pin: Pin) -> None:
        """IRQ handler for both DT and CLK pins.

        Args:
            pin (Pin): the pin that triggered the interrupt.
        """
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_change_ms) < self._debounce_ms:
            return

        new_status = self._read_status()
        if new_status == self._last_status:
            return

        transition = (self._last_status << 2) | new_status

        if transition == self._TRANSITION_CW:
            self._last_event = RotaryEvent.CW
        elif transition == self._TRANSITION_CCW:
            self._last_event = RotaryEvent.CCW
        # any other transition value is a bounce/invalid step; ignored

        self._last_status = new_status
        self._last_change_ms = now

    def consume(self) -> RotaryEvent:
        """Return and clear the most recent rotary event.

        Returns:
            RotaryEvent: NONE, CW, or CCW.
        """
        event = self._last_event
        self._last_event = RotaryEvent.NONE
        return event
