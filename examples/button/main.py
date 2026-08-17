from machine import Pin
from micropython import const
from lib_common.button import Button, ButtonEvent
import time

BUTTON_PIN = const(15)  # GPIO pin the button is connected to

button = Button(BUTTON_PIN, Pin.PULL_UP)
led = Pin(25, Pin.OUT)

button_event = ButtonEvent.NONE
state = False
prev_state = False

while True:
    button_event = button.consume()
    state = button.is_pressed()

    if state == True:
        led.on()
    else:
        led.off()

    if state != prev_state and state == True:
        print("pressed")

    if button_event != ButtonEvent.NONE:
        if button_event == ButtonEvent.SHORT_PRESS:
            print("short")
        elif button_event == ButtonEvent.LONG_PRESS:
            print("long")

    prev_state = state
    time.sleep_ms(10)
