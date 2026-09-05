"""
midi.py

MIDI message library for a MicroPython instance. Provides a `Message`
class hierarchy, a `SysEx` type, and `MidiUsb`/`MidiUart` output classes
sharing a `send_message()` / `send_sysex()` API.

`MidiUsb` requires `mpremote mip install usb-device-midi` on firmware
with `usb.device` support. `MidiUart` requires only `machine`. Both are
optional at import time; instantiating one without its dependency
raises `RuntimeError`.

See ../examples/midi/main.py for usage.
"""

try:
    import usb.device
    from usb.device.midi import MIDIInterface
except ImportError:
    usb = None
    MIDIInterface = object

try:
    from machine import UART, Pin
except ImportError:
    UART = None
    Pin = None

# ===========================================================================
# MIDI message classes
# ===========================================================================

_NOTE_OFF = 0x8
_NOTE_ON = 0x9
_POLY_AFTERTOUCH = 0xA
_CONTROL_CHANGE = 0xB
_PROGRAM_CHANGE = 0xC
_CHANNEL_AFTERTOUCH = 0xD
_PITCH_BEND = 0xE

_SYSEX_START = 0xF0
_SYSEX_END = 0xF7
_CLOCK = 0xF8
_START = 0xFA
_CONTINUE = 0xFB
_STOP = 0xFC
_ACTIVE_SENSING = 0xFE
_SYSTEM_RESET = 0xFF

_MIDI_UART_BAUDRATE = 31250


def _clamp7(value: int, name: str = "value") -> int:
    """Validate and return a 7-bit MIDI data-byte value.

    Args:
        value (int): value to validate.
        name (str, optional): name used in the error message.

    Returns:
        int: `value`, unchanged.

    Raises:
        ValueError: if `value` is not in 0-127.
    """
    if not 0 <= value <= 127:
        raise ValueError("%s must be 0-127, got %r" % (name, value))
    return value


def _clamp_channel(channel: int) -> int:
    """Validate and return a zero-based MIDI channel number.

    Args:
        channel (int): channel to validate.

    Returns:
        int: `channel`, unchanged.

    Raises:
        ValueError: if `channel` is not in 0-15.
    """
    if not 0 <= channel <= 15:
        raise ValueError("channel must be 0-15, got %r" % channel)
    return channel


class Message:
    """Base class for fixed-size MIDI messages."""

    def __init__(self, channel: int) -> None:
        """
        Args:
            channel: Zero-based MIDI channel (0-15).

        Raises:
            ValueError: if `channel` is not in 0-15.
        """
        self.channel: int = _clamp_channel(channel)

    def to_bytes(self) -> list:
        """Return the raw MIDI bytes as a list of integers.

        Raises:
            NotImplementedError: always, unless overridden by a subclass.
        """
        raise NotImplementedError

    def cin(self) -> int:
        """Return the USB-MIDI Code Index Number for this message.

        Raises:
            NotImplementedError: always, unless overridden by a subclass.
        """
        raise NotImplementedError

    def __repr__(self) -> str:
        return "<%s bytes=%s>" % (self.__class__.__name__, list(self.to_bytes()))


class NoteOn(Message):
    """MIDI Note On message."""

    def __init__(self, channel: int, note: int, velocity: int) -> None:
        """
        Args:
            channel: Zero-based MIDI channel (0-15).
            note: MIDI note number (0-127).
            velocity: Note-on velocity (0-127).

        Raises:
            ValueError: if `channel`, `note`, or `velocity` are out of range.
        """
        super().__init__(channel)
        self.note: int = _clamp7(note, "note")
        self.velocity: int = _clamp7(velocity, "velocity")

    def to_bytes(self) -> list:
        return [(_NOTE_ON << 4) | self.channel, self.note, self.velocity]

    def cin(self) -> int:
        return _NOTE_ON


class NoteOff(Message):
    """MIDI Note Off message."""

    def __init__(self, channel: int, note: int, velocity: int) -> None:
        """
        Args:
            channel: Zero-based MIDI channel (0-15).
            note: MIDI note number (0-127).
            velocity: Release velocity (0-127).

        Raises:
            ValueError: if `channel`, `note`, or `velocity` are out of range.
        """
        super().__init__(channel)
        self.note: int = _clamp7(note, "note")
        self.velocity: int = _clamp7(velocity, "velocity")

    def to_bytes(self) -> list:
        return [(_NOTE_OFF << 4) | self.channel, self.note, self.velocity]

    def cin(self) -> int:
        return _NOTE_OFF


class ControlChange(Message):
    """MIDI Control Change message."""

    def __init__(self, channel: int, controller: int, value: int) -> None:
        """
        Args:
            channel: Zero-based MIDI channel (0-15).
            controller: Controller number (0-127).
            value: Controller value (0-127).

        Raises:
            ValueError: if `channel`, `controller`, or `value` are out of
                range.
        """
        super().__init__(channel)
        self.controller: int = _clamp7(controller, "controller")
        self.value: int = _clamp7(value, "value")

    def to_bytes(self) -> list:
        return [(_CONTROL_CHANGE << 4) | self.channel, self.controller, self.value]

    def cin(self) -> int:
        return _CONTROL_CHANGE


class ProgramChange(Message):
    """MIDI Program Change message."""

    def __init__(self, channel: int, program: int) -> None:
        """
        Args:
            channel: Zero-based MIDI channel (0-15).
            program: Program number (0-127).

        Raises:
            ValueError: if `channel` or `program` are out of range.
        """
        super().__init__(channel)
        self.program: int = _clamp7(program, "program")

    def to_bytes(self) -> list:
        return [(_PROGRAM_CHANGE << 4) | self.channel, self.program]

    def cin(self) -> int:
        return _PROGRAM_CHANGE


class ChannelAftertouch(Message):
    """MIDI channel pressure (monophonic aftertouch) message."""

    def __init__(self, channel: int, pressure: int) -> None:
        """
        Args:
            channel: Zero-based MIDI channel (0-15).
            pressure: Pressure value (0-127).

        Raises:
            ValueError: if `channel` or `pressure` are out of range.
        """
        super().__init__(channel)
        self.pressure: int = _clamp7(pressure, "pressure")

    def to_bytes(self) -> list:
        return [(_CHANNEL_AFTERTOUCH << 4) | self.channel, self.pressure]

    def cin(self) -> int:
        return _CHANNEL_AFTERTOUCH


class PolyAftertouch(Message):
    """MIDI polyphonic key-pressure message."""

    def __init__(self, channel: int, note: int, pressure: int) -> None:
        """
        Args:
            channel: Zero-based MIDI channel (0-15).
            note: MIDI note number (0-127).
            pressure: Pressure value (0-127).

        Raises:
            ValueError: if `channel`, `note`, or `pressure` are out of
                range.
        """
        super().__init__(channel)
        self.note: int = _clamp7(note, "note")
        self.pressure: int = _clamp7(pressure, "pressure")

    def to_bytes(self) -> list:
        return [(_POLY_AFTERTOUCH << 4) | self.channel, self.note, self.pressure]

    def cin(self) -> int:
        return _POLY_AFTERTOUCH


class PitchBend(Message):
    """MIDI 14-bit pitch bend message."""

    def __init__(self, channel: int, value: int) -> None:
        """
        Args:
            channel: Zero-based MIDI channel (0-15).
            value: Bend amount, -8192 to 8191. Zero is centre/no bend.

        Raises:
            ValueError: if `channel` is out of range, or `value` is not
                in -8192..8191.
        """
        super().__init__(channel)
        if not -8192 <= value <= 8191:
            raise ValueError("pitch bend value must be -8192..8191")
        self.value: int = value

    def to_bytes(self) -> list:
        raw: int = self.value + 8192  # shift to unsigned 14-bit range
        return [
            (_PITCH_BEND << 4) | self.channel,
            raw & 0x7F,  # LSB
            (raw >> 7) & 0x7F,  # MSB
        ]

    def cin(self) -> int:
        return _PITCH_BEND


class SystemRealtime(Message):
    """Base class for single-byte MIDI system realtime messages."""

    _STATUS = None

    def __init__(self, channel: int) -> None:
        """
        Args:
            channel: Unused; kept for a consistent constructor signature
                across all Message subclasses.

        Raises:
            ValueError: if `channel` is not in 0-15.
        """
        super().__init__(channel)

    def to_bytes(self) -> list:
        return [self._STATUS]

    def cin(self) -> int:
        return 0xF


class Clock(SystemRealtime):
    """MIDI Timing Clock (0xF8)."""

    _STATUS: int = _CLOCK


class Start(SystemRealtime):
    """MIDI Start (0xFA)."""

    _STATUS: int = _START


class Continue(SystemRealtime):
    """MIDI Continue (0xFB)."""

    _STATUS: int = _CONTINUE


class Stop(SystemRealtime):
    """MIDI Stop (0xFC)."""

    _STATUS: int = _STOP


class ActiveSensing(SystemRealtime):
    """MIDI Active Sensing (0xFE)."""

    _STATUS: int = _ACTIVE_SENSING


class SystemReset(SystemRealtime):
    """MIDI System Reset (0xFF)."""

    _STATUS: int = _SYSTEM_RESET


# ===========================================================================
# System Exclusive
# ===========================================================================


# Not a Message subclass: SysEx is variable-length and has no single
# fixed cin(), so it deliberately doesn't implement the Message interface.
class SysEx:
    """MIDI System Exclusive message."""

    def __init__(self, data: list) -> None:
        """
        Args:
            data: SysEx payload bytes (0-127 each), excluding the
                start/end bytes, which are added automatically.

        Raises:
            ValueError: if any byte in `data` is not in 0-127.
        """
        self.data: list = list(data)
        for byte in self.data:
            if not 0 <= byte <= 127:
                raise ValueError("SysEx payload bytes must be 0-127")

    def to_bytes(self) -> list:
        return [_SYSEX_START] + self.data + [_SYSEX_END]

    def __repr__(self) -> str:
        return "<SysEx bytes=%s>" % (self.to_bytes(),)


# ===========================================================================
# USB MIDI interface
# ===========================================================================


class MidiUsb(MIDIInterface):
    """Self-initialising USB MIDI interface with Message/SysEx send helpers."""

    def __init__(
        self,
        product_str: str = None,
        manufacturer_str: str = None,
        rxlen: int = 16,
        txlen: int = 16,
        builtin_driver: bool = True,
    ) -> None:
        """
        Args:
            product_str: USB product string shown by the host.
            manufacturer_str: USB manufacturer string.
            rxlen: Receive buffer size in bytes.
            txlen: Transmit buffer size in bytes.
            builtin_driver: Passed to `usb.device.get().init()`.

        Raises:
            RuntimeError: if `usb-device-midi` is not installed.
        """
        if MIDIInterface is object:
            raise RuntimeError(
                "usb.device.midi.MIDIInterface is not available. Install "
                "it with `mpremote mip install usb-device-midi` on "
                "firmware with usb.device support."
            )

        super().__init__(rxlen=rxlen, txlen=txlen)

        init_kwargs = {"builtin_driver": builtin_driver}
        if product_str is not None:
            init_kwargs["product_str"] = product_str
        if manufacturer_str is not None:
            init_kwargs["manufacturer_str"] = manufacturer_str

        usb.device.get().init(self, **init_kwargs)

    def send_message(self, msg: Message) -> None:
        """Send a fixed-size Message as a single USB-MIDI Event Packet.

        Args:
            msg: A `Message` instance.

        Raises:
            TypeError: if `msg` is not a `Message` instance.
        """
        if not isinstance(msg, Message):
            raise TypeError(
                "send_message() expects a Message instance, got %r" % (msg,)
            )
        self.send_event(msg.cin(), *msg.to_bytes())

    def send_sysex(self, msg: SysEx) -> None:
        """Send a SysEx message, split into 3-byte USB-MIDI packets.

        Args:
            msg: A `SysEx` instance.

        Raises:
            TypeError: if `msg` is not a `SysEx` instance.
        """
        if not isinstance(msg, SysEx):
            raise TypeError("send_sysex() expects a SysEx instance, got %r" % (msg,))

        data: list = msg.to_bytes()
        chunk_count: int = (len(data) + 2) // 3

        for index in range(chunk_count):
            chunk: list = data[index * 3 : index * 3 + 3]
            is_last: bool = index == chunk_count - 1

            # CIN 0x4 = SysEx starts or continues (always a full 3-byte
            # chunk). Final chunk uses 0x5/0x6/0x7 for a 1/2/3-byte end.
            if is_last:
                cin: int = {1: 0x5, 2: 0x6, 3: 0x7}[len(chunk)]
            else:
                cin = 0x4

            b0, b1, b2 = (chunk + [0, 0, 0])[:3]  # zero-pad short chunks
            self.send_event(cin, b0, b1, b2)


# ===========================================================================
# UART MIDI interface
# ===========================================================================


class MidiUart:
    """Self-initialising serial MIDI interface, matching the MidiUsb API."""

    def __init__(
        self,
        uart_id: int,
        tx_pin: int,
        rx_pin: int,
        baudrate: int = _MIDI_UART_BAUDRATE,
    ) -> None:
        """
        Args:
            uart_id: `machine.UART` peripheral number to use.
            tx_pin: GPIO pin number connected to the MIDI output circuit.
            rx_pin: GPIO pin number connected to the MIDI input circuit.
            baudrate: Serial baud rate. Defaults to 31250 (standard MIDI).

        Raises:
            RuntimeError: if `machine` is not available.
        """
        if UART is None or Pin is None:
            raise RuntimeError(
                "machine.UART/machine.Pin are not available. MidiUart "
                "requires MicroPython's machine module."
            )

        self._uart = UART(
            uart_id,
            baudrate=baudrate,
            tx=Pin(tx_pin),
            rx=Pin(rx_pin),
            bits=8,
            parity=None,
            stop=1,
        )

    def send_message(self, msg: Message) -> None:
        """Write a fixed-size Message as raw MIDI bytes.

        Args:
            msg: A `Message` instance.

        Raises:
            TypeError: if `msg` is not a `Message` instance.
        """
        if not isinstance(msg, Message):
            raise TypeError(
                "send_message() expects a Message instance, got %r" % (msg,)
            )
        self._uart.write(bytes(msg.to_bytes()))

    def send_sysex(self, msg: SysEx) -> None:
        """Write a SysEx message as raw MIDI bytes.

        Args:
            msg: A `SysEx` instance.

        Raises:
            TypeError: if `msg` is not a `SysEx` instance.
        """
        if not isinstance(msg, SysEx):
            raise TypeError("send_sysex() expects a SysEx instance, got %r" % (msg,))
        self._uart.write(bytes(msg.to_bytes()))
