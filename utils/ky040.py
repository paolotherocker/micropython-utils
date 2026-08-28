"""
ky040.py

Quadrature-transition based KY-040 rotary encoder driver for MicroPython
(Raspberry Pi Pico or any board with machine.Pin IRQ support).

Usage:

    from machine import Pin
    from rotary import Rotary, RotaryEvent
    import utime as time

    dt = Pin(0, Pin.IN, Pin.PULL_UP)
    clk = Pin(1, Pin.IN, Pin.PULL_UP)
    r = Rotary(dt_pin=dt, clk_pin=clk)

    while True:
        event = r.consume()
        if event == RotaryEvent.CW:
            print("CW")
        elif event == RotaryEvent.CCW:
            print("CCW")
        time.sleep_ms(10)

No switch (SW) handling is included -- this module only reports rotation
direction. No external libraries are used beyond `machine`, so type
enforcement is done manually via isinstance() checks and plain int
constants (MicroPython has no `enum` module in the base build).

Note: dt_pin and clk_pin must already be configured as Pin.IN before
being passed in. This is not checked or enforced -- Rotary just uses
the pins as given.
"""

from machine import Pin


class RotaryEvent:
    """Namespace of direction constants returned by Rotary.consume()."""

    NONE = 0  # no event since the last consume()
    CW = 1  # clockwise step
    CCW = 2  # counter-clockwise step


class KY040:
    """
    KY-040 rotary encoder reader using a quadrature transition table.

    Only tracks the most recent direction event. Call consume() to fetch
    and clear it. If multiple steps occur between consume() calls, only
    the latest one is kept (no queueing).
    """

    # Transition table values, expressed as (last_status << 2) | new_status
    _TRANSITION_CW = 0b1110
    _TRANSITION_CCW = 0b1101

    def __init__(self, dt_pin: int, clk_pin: int, pull: int = Pin.PULL_UP) -> None:
        """
        Args:
            dt_pin (int): DT pin ID number
            clk_pin (int): CLK pin ID number
            pull (int, optional): Can be Pin.PULL_UP, Pin.PULL_DOWN or None
        """
        self._dt_pin = Pin(dt_pin, Pin.IN, pull)
        self._clk_pin = Pin(clk_pin, Pin.IN, pull)

        self._last_status = self._read_status()
        self._last_event = RotaryEvent.NONE

        self._dt_pin.irq(self._on_pin_change, Pin.IRQ_RISING | Pin.IRQ_FALLING)
        self._clk_pin.irq(self._on_pin_change, Pin.IRQ_RISING | Pin.IRQ_FALLING)

    def _read_status(self) -> int:
        """Pack DT/CLK pin levels into a 2-bit int: (dt << 1) | clk."""
        dt_val = self._dt_pin.value()
        clk_val = self._clk_pin.value()
        return (dt_val << 1) | clk_val

    def _on_pin_change(self, pin: Pin) -> None:
        """IRQ handler for both DT and CLK pins. Updates the pending event."""
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

    def consume(self) -> RotaryEvent:
        """
        Return the most recent RotaryEvent (NONE, CW, or CCW) and reset
        the stored event back to NONE.
        """
        event = self._last_event
        self._last_event = RotaryEvent.NONE
        return event
