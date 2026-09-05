from machine import Pin
from micropython import const
from utils.button import Button, ButtonEvent
import time

BUTTON_PIN = const(15)  # GPIO pin the button is connected to

button = Button(BUTTON_PIN, Pin.PULL_UP)
led = Pin(25, Pin.OUT)

button_event = ButtonEvent.NONE

while True:
    button_event = button.consume()

    if button_event in (ButtonEvent.PRESS):
        led.on()
    elif button_event in (ButtonEvent.SHORT_RELEASE, ButtonEvent.LONG_RELEASE):
        led.off()

    if button_event != ButtonEvent.NONE:
        if button_event == ButtonEvent.PRESS:
            print("pressed")
        elif button_event == ButtonEvent.SHORT_RELEASE:
            print("short release")
        elif button_event == ButtonEvent.LONG_PRESS:
            print("long press")
        elif button_event == ButtonEvent.LONG_RELEASE:
            print("long release")

    time.sleep_ms(1)
