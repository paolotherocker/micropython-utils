"""
midimanager.py
===============

A transport-agnostic MIDI output library for a MicroPython instance.

The library contains:

- A `Message` class hierarchy for standard MIDI messages.
- `MidiManager`, which sends each message to USB MIDI, UART MIDI, or both.

The common sending interface is:

    midi.send_message(message)

Dependencies
------------

USB MIDI
~~~~~~~~
USB MIDI is optional. To use it, install MicroPython's USB MIDI device
package on a compatible MicroPython build:

    mpremote mip install usb-device-midi

Your firmware must provide `usb.device` support. Create and register a
`usb.device.midi.MIDIInterface` before constructing `MidiManager`.

UART MIDI
~~~~~~~~~
UART MIDI is optional. It uses the built-in `machine.UART` class; no
additional package is required. Configure the UART for standard MIDI:

- baud rate: 31250
- data bits: 8
- parity: none
- stop bits: 1

Pass the configured `machine.UART` instance to `MidiManager`.

Examples
--------

USB only::

    import usb.device
    from usb.device.midi import MIDIInterface
    from midi_manager import MidiManager, NoteOn

    usb_midi = MIDIInterface()
    usb.device.get().init(usb_midi, builtin_driver=True)
    midi = MidiManager(usb_midi=usb_midi)
    midi.send_message(NoteOn(note=60, velocity=100, channel=0))

UART only::

    import machine
    from midi_manager import MidiManager, ControlChange

    uart = machine.UART(1, baudrate=31250,
                        tx=machine.Pin(4), rx=machine.Pin(5))
    midi = MidiManager(uart=uart)
    midi.send_message(ControlChange(controller=7, value=100, channel=0))

USB and UART simultaneously::

    midi = MidiManager(usb_midi=usb_midi, uart=uart)
    midi.send_message(ProgramChange(program=10, channel=0))

USB compatibility
-----------------

`usb.device.midi.MIDIInterface` implementations can expose different raw
send-method names between package or firmware releases. `MidiManager` looks
for the methods listed in `_USB_SEND_CANDIDATES`. If the USB transport does
not match your installed interface, inspect `help(usb_midi)` and update that
tuple or override `_transmit_usb_packet()` for the API exposed by your build.
"""

try:
    from machine import UART
except ImportError:
    UART = object

try:
    from usb.device.midi import MIDIInterface
except ImportError:
    MIDIInterface = object

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


def _clamp7(value: int, name: str = "value") -> int:
    """Validate and return a 7-bit MIDI data-byte value."""
    if not 0 <= value <= 127:
        raise ValueError("%s must be 0-127, got %r" % (name, value))
    return value


def _clamp_channel(channel: int) -> int:
    """Validate and return a zero-based MIDI channel number."""
    if not 0 <= channel <= 15:
        raise ValueError("channel must be 0-15, got %r" % channel)
    return channel


class Message:
    """
    Abstract base class for MIDI messages.

    Concrete subclasses implement `to_bytes()` and specify `cin`, the
    USB-MIDI Code Index Number. Channels are zero-based: channel=0 is
    MIDI channel 1, and channel=15 is MIDI channel 16.
    """

    cin = None

    def __init__(self, channel: int = 0) -> None:
        self.channel: int = _clamp_channel(channel)

    def to_bytes(self) -> list:
        """Return the raw MIDI bytes as a list of integers."""
        raise NotImplementedError

    def __repr__(self) -> str:
        return "<%s bytes=%s>" % (self.__class__.__name__, list(self.to_bytes()))


class NoteOn(Message):
    """MIDI Note On message."""
    cin: int = _NOTE_ON

    def __init__(self, note: int, velocity: int = 127, channel: int = 0) -> None:
        super().__init__(channel)
        self.note: int = _clamp7(note, "note")
        self.velocity: int = _clamp7(velocity, "velocity")

    def to_bytes(self) -> list:
        return [(_NOTE_ON << 4) | self.channel, self.note, self.velocity]


class NoteOff(Message):
    """MIDI Note Off message."""
    cin: int = _NOTE_OFF

    def __init__(self, note: int, velocity: int = 0, channel: int = 0) -> None:
        super().__init__(channel)
        self.note: int = _clamp7(note, "note")
        self.velocity: int = _clamp7(velocity, "velocity")

    def to_bytes(self) -> list:
        return [(_NOTE_OFF << 4) | self.channel, self.note, self.velocity]


class ControlChange(Message):
    """MIDI Control Change message."""
    cin: int = _CONTROL_CHANGE

    def __init__(self, controller: int, value: int, channel: int = 0) -> None:
        super().__init__(channel)
        self.controller: int = _clamp7(controller, "controller")
        self.value: int = _clamp7(value, "value")

    def to_bytes(self) -> list:
        return [(_CONTROL_CHANGE << 4) | self.channel, self.controller, self.value]


class ProgramChange(Message):
    """MIDI Program Change message."""
    cin: int = _PROGRAM_CHANGE

    def __init__(self, program: int, channel: int = 0) -> None:
        super().__init__(channel)
        self.program: int = _clamp7(program, "program")

    def to_bytes(self) -> list:
        return [(_PROGRAM_CHANGE << 4) | self.channel, self.program]


class ChannelAftertouch(Message):
    """MIDI channel pressure (monophonic aftertouch) message."""
    cin: int = _CHANNEL_AFTERTOUCH

    def __init__(self, pressure: int, channel: int = 0) -> None:
        super().__init__(channel)
        self.pressure: int = _clamp7(pressure, "pressure")

    def to_bytes(self) -> list:
        return [(_CHANNEL_AFTERTOUCH << 4) | self.channel, self.pressure]


class PolyAftertouch(Message):
    """MIDI polyphonic key-pressure message."""
    cin: int = _POLY_AFTERTOUCH

    def __init__(self, note: int, pressure: int, channel: int = 0) -> None:
        super().__init__(channel)
        self.note: int = _clamp7(note, "note")
        self.pressure: int = _clamp7(pressure, "pressure")

    def to_bytes(self) -> list:
        return [(_POLY_AFTERTOUCH << 4) | self.channel, self.note, self.pressure]


class PitchBend(Message):
    """
    MIDI 14-bit pitch bend.

    `value` ranges from -8192 to 8191. Zero is centre/no bend.
    """
    cin: int = _PITCH_BEND

    def __init__(self, value: int = 0, channel: int = 0) -> None:
        super().__init__(channel)
        if not -8192 <= value <= 8191:
            raise ValueError("pitch bend value must be -8192..8191")
        self.value: int = value

    def to_bytes(self) -> list:
        raw: int = self.value + 8192
        return [
            (_PITCH_BEND << 4) | self.channel,
            raw & 0x7F,
            (raw >> 7) & 0x7F,
        ]


class SystemRealtime(Message):
    """Base class for single-byte MIDI system realtime messages."""
    cin: int = 0xF
    _STATUS = None

    def __init__(self) -> None:
        super().__init__(channel=0)

    def to_bytes(self) -> list:
        return [self._STATUS]


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


class SysEx(Message):
    """
    MIDI System Exclusive message.

    `data` is the payload only. Do not include 0xF0 and 0xF7; this class
    adds them when rendering the complete wire-format message.
    """
    cin = None

    def __init__(self, data: list) -> None:
        super().__init__(channel=0)
        self.data: list = list(data)
        for byte in self.data:
            if not 0 <= byte <= 127:
                raise ValueError("SysEx payload bytes must be 0-127")

    def to_bytes(self) -> list:
        return [_SYSEX_START] + self.data + [_SYSEX_END]


# ===========================================================================
# MIDI output manager
# ===========================================================================

class MidiManager:
    """
    Send MIDI messages to USB MIDI, UART MIDI, or both transports.

    Example::

        midi = MidiManager(usb_midi=usb_midi, uart=uart)
        midi.send_message(ControlChange(7, 100, channel=0))
    """

    _USB_SEND_CANDIDATES: tuple = (
        "send_event",
        "send_midi_event",
        "write_event",
        "send",
    )

    def __init__(
        self,
        usb_midi: MIDIInterface = None,
        uart: UART = None,
        usb_cable: int = 0,
    ) -> None:
        """
        Arguments:
            usb_midi: An optional `usb.device.midi.MIDIInterface` instance.
            uart: An optional configured `machine.UART` instance.
            usb_cable: USB-MIDI virtual cable number, from 0 to 15.
        """
        if usb_midi is None and uart is None:
            raise ValueError("MidiManager needs at least one of usb_midi or uart")

        self.usb_midi: MIDIInterface = usb_midi
        self.uart: UART = uart
        self.usb_cable: int = usb_cable & 0x0F
        self._usb_send_method = None

        if self.usb_midi is not None:
            self._usb_send_method = self._resolve_usb_send_method()

    def send_message(self, msg: Message) -> None:
        """
        Send `msg` through every enabled MIDI transport.

        `msg` must be an instance of `Message` or one of its concrete
        subclasses, such as `ControlChange` or `ProgramChange`.
        """
        if not isinstance(msg, Message):
            raise TypeError(
                "send_message() expects a Message instance, got %r" % (msg,)
            )

        data: list = msg.to_bytes()

        if self.uart is not None:
            self.uart.write(bytes(data))

        if self.usb_midi is not None:
            if isinstance(msg, SysEx):
                self._send_usb_sysex(data)
            else:
                self._send_usb_event(msg.cin, data)

    def _resolve_usb_send_method(self):
        for name in self._USB_SEND_CANDIDATES:
            method = getattr(self.usb_midi, name, None)
            if callable(method):
                return method

        raise AttributeError(
            "No USB MIDI send method found. Tried: %s"
            % (self._USB_SEND_CANDIDATES,)
        )

    def _send_usb_event(self, cin: int, data_bytes: list) -> None:
        """Build and transmit one four-byte USB-MIDI Event Packet."""
        b0, b1, b2 = (list(data_bytes) + [0, 0, 0])[:3]
        header: int = (self.usb_cable << 4) | (cin & 0x0F)
        self._transmit_usb_packet(header, b0, b1, b2)

    def _send_usb_sysex(self, data_bytes: list) -> None:
        """Packetise a variable-length SysEx message for USB MIDI."""
        chunks: list = [
            data_bytes[index:index + 3]
            for index in range(0, len(data_bytes), 3)
        ]

        for index, chunk in enumerate(chunks):
            is_last: bool = index == len(chunks) - 1
            if is_last:
                cin: int = {1: 0x5, 2: 0x6, 3: 0x7}[len(chunk)]
            else:
                cin = 0x4

            b0, b1, b2 = (chunk + [0, 0, 0])[:3]
            header: int = (self.usb_cable << 4) | cin
            self._transmit_usb_packet(header, b0, b1, b2)

    def _transmit_usb_packet(self, header: int, b0: int, b1: int, b2: int) -> None:
        """Submit a raw USB-MIDI packet through the available interface API."""
        try:
            self._usb_send_method(self.usb_cable, header & 0x0F, b0, b1, b2)
        except TypeError:
            self._usb_send_method(bytes((header, b0, b1, b2)))
