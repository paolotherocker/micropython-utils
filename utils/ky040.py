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
    CW = 1  # clockwise step
    CCW = 2  # counter-clockwise step


class KY040:
    """Quadrature-transition based KY-040 rotary encoder reader."""

    # Transition table values, expressed as (committed_status << 2) | new_status
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

        initial_status = self._read_status()
        self._committed_status = initial_status  # last status consume() has acted on
        self._last_edge_status = initial_status  # latest raw status seen by the IRQ
        self._last_edge_ms = time.ticks_ms()  # restarts on every edge (debounce timer)
        self._pending_event = RotaryEvent.NONE

        self._dt_pin.irq(self._on_pin_change, Pin.IRQ_RISING | Pin.IRQ_FALLING)
        self._clk_pin.irq(self._on_pin_change, Pin.IRQ_RISING | Pin.IRQ_FALLING)

    def _read_status(self) -> int:
        """Pack DT/CLK pin levels into a 2-bit int: (dt << 1) | clk."""
        return (self._dt_pin.value() << 1) | self._clk_pin.value()

    def _on_pin_change(self, pin: Pin) -> None:
        """IRQ handler for both DT and CLK pins.

        Args:
            pin (Pin): the pin that triggered the interrupt.
        """
        self._last_edge_status = self._read_status()
        self._last_edge_ms = time.ticks_ms()

    def consume(self) -> RotaryEvent:
        """Return and clear the most recent rotary event.

        Returns:
            RotaryEvent: NONE, CW, or CCW.
        """
        now = time.ticks_ms()

        irq_state = disable_irq()
        edge_status = self._last_edge_status
        edge_ms = self._last_edge_ms
        enable_irq(irq_state)

        if (
            edge_status != self._committed_status
            and time.ticks_diff(now, edge_ms) >= self._debounce_ms
        ):
            transition = (self._committed_status << 2) | edge_status

            if transition == self._TRANSITION_CW:
                self._pending_event = RotaryEvent.CW
            elif transition == self._TRANSITION_CCW:
                self._pending_event = RotaryEvent.CCW
            # any other transition value is a bounce/invalid step; ignored

            self._committed_status = edge_status

        event = self._pending_event
        self._pending_event = RotaryEvent.NONE
        return event
