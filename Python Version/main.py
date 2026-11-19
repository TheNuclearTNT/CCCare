# MicroPython version of cccare_pulse_oxv1.ino for the Raspberry Pi Pico 2 W.
# The Pico runs main.py automatically on power-up.
#
# Nov 2
# can select age and resting heart rate
# gets heart rate reading, not accurate
# takes avg (don't know if thats accurate either, haven't checked)

import json
import os
import socket
import time

import network
import ssd1306  # install once: Thonny > Tools > Manage packages > "ssd1306"
from machine import ADC, I2C, Pin

from max30102 import (ADCRANGE_16384, MODE_MULTILED, PULSEWIDTH_411,
                      SAMPLEAVG_16, SAMPLERATE_400, DFRobot_MAX30102)
from secrets import SHEETS_TOKEN, SHEETS_URL, WIFI_PASSWORD, WIFI_SSID

try:
    import tls  # MicroPython 1.23 and newer
except ImportError:
    tls = None
    import ssl

# Google Sheets logging
boot_id = int.from_bytes(os.urandom(4), "little")  # random per reset; tells Apps Script to start a new tab
wlan = network.WLAN(network.STA_IF)


def connect_wifi():
    if wlan.isconnected():
        return
    print("Connecting to WiFi", end="")
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    start = time.ticks_ms()
    while not wlan.isconnected() and time.ticks_diff(time.ticks_ms(), start) < 15000:
        time.sleep_ms(500)
        print(".", end="")
    print(" connected" if wlan.isconnected() else " failed")


def https_post(url, body, timeout=15):
    """POST body to url and return the HTTP status code.

    Redirects are not followed, same as the Arduino HTTPClient. Apps Script
    runs doPost and then answers 302, so 302 means the reading was saved.
    The certificate isn't checked; the token protects the endpoint.
    """
    _, _, host, path = url.split("/", 3)
    addr = socket.getaddrinfo(host, 443, 0, socket.SOCK_STREAM)[0][-1]
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        sock.connect(addr)
        if tls:
            ctx = tls.SSLContext(tls.PROTOCOL_TLS_CLIENT)
            ctx.verify_mode = tls.CERT_NONE
            sock = ctx.wrap_socket(sock, server_hostname=host)
        else:
            sock = ssl.wrap_socket(sock, server_hostname=host)
        data = body.encode()
        sock.write(("POST /{} HTTP/1.1\r\n"
                    "Host: {}\r\n"
                    "Content-Type: application/json\r\n"
                    "Content-Length: {}\r\n"
                    "Connection: close\r\n\r\n").format(path, host, len(data)).encode())
        sock.write(data)
        status_line = sock.readline()  # e.g. b"HTTP/1.1 302 Moved Temporarily"
        return int(status_line.split()[1])
    finally:
        sock.close()


def send_to_sheets(bpm):
    connect_wifi()
    if not wlan.isconnected():
        return

    body = json.dumps({"boot": boot_id, "bpm": bpm, "token": SHEETS_TOKEN})
    try:
        code = https_post(SHEETS_URL, body)
    except (OSError, ValueError, IndexError) as e:
        code = "error: {}".format(e)
    print("Sheets HTTP", code)


# Screen Variables
SCREEN_WIDTH = 128
SCREEN_HEIGHT = 64


class Screen:
    """Gives the SSD1306 the Adafruit_GFX calls the sketch uses:
    clearDisplay, setCursor, print, println (with line wrapping) and display."""
    CHAR_W = 8  # MicroPython's built-in font is 8x8
    CHAR_H = 8

    def __init__(self, oled):
        self.oled = oled
        self.x = 0
        self.y = 0

    def clearDisplay(self):
        self.oled.fill(0)
        self.x = 0
        self.y = 0

    def setCursor(self, x, y):
        self.x = x
        self.y = y

    def _newline(self):
        self.x = 0
        self.y += self.CHAR_H

    def print(self, value):
        # This font is wider than Adafruit's (16 characters per line instead
        # of 21), so wrap at spaces to avoid splitting words.
        text = str(value)
        for i, ch in enumerate(text):
            if ch == "\n":
                self._newline()
                continue
            if ch == " ":
                if self.x + self.CHAR_W > SCREEN_WIDTH:
                    self._newline()  # wrap here and drop the space
                    continue
            elif i == 0 or text[i - 1] in " \n":
                end = i
                while end < len(text) and text[end] not in " \n":
                    end += 1
                word_w = (end - i) * self.CHAR_W
                if self.x > 0 and self.x + word_w > SCREEN_WIDTH and word_w <= SCREEN_WIDTH:
                    self._newline()  # move the whole word to the next line
            if self.x + self.CHAR_W > SCREEN_WIDTH:
                self._newline()  # word longer than a line: wrap mid-word
            self.oled.text(ch, self.x, self.y, 1)
            self.x += self.CHAR_W

    def println(self, value=""):
        self.print(str(value) + "\n")

    def display(self):
        self.oled.show()


# Default Pico I2C pins, same as the Arduino Wire defaults: SDA = GP4, SCL = GP5
i2c = I2C(0, sda=Pin(4), scl=Pin(5), freq=400000)
display = None
pot = ADC(Pin(28))  # A2 on the Pico is GP28; potentiometer
adc_value = 0  # Variable to store the ADC reading

age = 0
rest_rate = 0
max_rate = 0
rate_reserve = 0
low_rate = 0
high_rate = 0
rates = [0] * 4
rate_avg = 0

button = Pin(2, Pin.IN)

particle_sensor = DFRobot_MAX30102()
# global variables
SPO2 = 0
heart_rate = 0
SPO2_valid = 0
heart_rate_valid = 0


def analog_read():
    """0-1023, like analogRead() on the Pico."""
    return pot.read_u16() >> 6


def setup():
    global display, adc_value, age, rest_rate, max_rate, rate_reserve, low_rate, high_rate

    display = Screen(ssd1306.SSD1306_I2C(SCREEN_WIDTH, SCREEN_HEIGHT, i2c, addr=0x3C))
    display.clearDisplay()
    button_state = button.value()
    connect_wifi()
    while not particle_sensor.begin(i2c):
        print("MAX30102 not found!")
        time.sleep_ms(1000)
    particle_sensor.sensorConfiguration(60, SAMPLEAVG_16, MODE_MULTILED, SAMPLERATE_400,
                                        PULSEWIDTH_411, ADCRANGE_16384)
    while button_state == 0:
        display.clearDisplay()
        display.setCursor(5, 0)
        display.println("Press button to select age")
        adc_value = analog_read()  # Read analog voltage (0-1023)
        adc_value = int((adc_value / 1023.0) * 100.0)
        display.print(adc_value)
        age = adc_value
        display.display()
        time.sleep_ms(100)
        button_state = button.value()
    time.sleep_ms(1000)
    button_state = button.value()
    while button_state == 0:
        display.clearDisplay()
        display.setCursor(5, 0)
        display.println("Press button to select resting heart rate")
        adc_value = analog_read()  # Read analog voltage (0-1023)
        adc_value = int(((adc_value / 1023.0) * 100.0) + 30.0)
        display.print(adc_value)
        rest_rate = adc_value
        display.display()
        time.sleep_ms(100)
        button_state = button.value()
    display.clearDisplay()
    max_rate = 220 - age
    rate_reserve = max_rate - rest_rate
    low_rate = int(0.4 * rate_reserve + rest_rate)
    high_rate = int(0.6 * rate_reserve + rest_rate)
    for i in range(4):
        rates[i] = int((low_rate + high_rate) / 2.0)


def loop():
    global SPO2, SPO2_valid, heart_rate, heart_rate_valid, rate_avg

    time.sleep_ms(100)
    SPO2, SPO2_valid, heart_rate, heart_rate_valid = particle_sensor.heartrateAndOxygenSaturation()
    display.clearDisplay()
    display.setCursor(5, 0)
    display.println("Current heart rate:")
    display.println(heart_rate)
    display.display()
    good_reading = heart_rate_valid and 30 <= heart_rate <= 255
    if good_reading:
        # only valid readings go into the average (no -999)
        for i in range(3):
            rates[i] = rates[i + 1]
        rates[3] = heart_rate
    rate_avg = 0  # start each average from zero
    for i in range(4):
        rate_avg += rates[i]
    rate_avg = int(rate_avg / 4)
    print(rate_avg)
    if good_reading and rate_avg > 0:
        send_to_sheets(rate_avg)
    if rate_avg < low_rate:
        display.println("Heart rate too low")
        display.display()
        time.sleep_ms(100)
    elif rate_avg > high_rate:
        display.println("Heart rate too high")
        display.display()
        time.sleep_ms(100)


setup()
while True:
    loop()
