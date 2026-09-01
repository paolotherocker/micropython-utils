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

    # Position of each raw 2-bit (dt << 1 | clk) status along the
    # natural Gray-code sequence 00 -> 01 -> 11 -> 10 -> 00. Any two
    # consecutive positions differ by exactly one physical quarter-step,
    # in either direction, from any starting status -- not just from a
    # single hardcoded rest state.
    _RING_POSITION = (0, 1, 3, 2)

    # Quarter-steps per detent. One CW/CCW event fires once the signed
    # accumulator reaches +-_STEPS_PER_DETENT.
    _STEPS_PER_DETENT = 4

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
        self._accumulator = 0  # signed quarter-step count since the last detent
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
            old_pos = self._RING_POSITION[self._committed_status]
            new_pos = self._RING_POSITION[edge_status]
            delta = (new_pos - old_pos) % 4

            if delta == 1:
                self._accumulator += 1
            elif delta == 3:
                self._accumulator -= 1
            # delta == 0 can't occur here (statuses differ); delta == 2
            # means two quarter-steps were skipped, which is direction-
            # ambiguous from a single jump, so it's left uncounted.

            if self._accumulator >= self._STEPS_PER_DETENT:
                self._pending_event = RotaryEvent.CW
                self._accumulator = 0
            elif self._accumulator <= -self._STEPS_PER_DETENT:
                self._pending_event = RotaryEvent.CCW
                self._accumulator = 0

            self._committed_status = edge_status

        event = self._pending_event
        self._pending_event = RotaryEvent.NONE
        return event
