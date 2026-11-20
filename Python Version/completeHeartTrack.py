import bluetooth
import struct
import time
import machine
import ubinascii
import ssd1306
from ble_advertising import advertising_payload
from micropython import const
from machine import Pin
from machine import Pin, I2C
from max30102 import MAX30102

#Sheets implementation
import json
import os
import socket
import network

from secrets import (
    WIFI_SSID,
    WIFI_PASSWORD,
    SHEETS_URL,
    SHEETS_TOKEN
)

try:
    import tls
except ImportError:
    tls = None
    import ssl



#import FingerTest
i2c = I2C(
    1,
    scl=Pin(27),
    sda=Pin(26),
    freq=400000
)

print("Devices:", i2c.scan())

sensor = MAX30102(i2c)

boot_id = int.from_bytes(os.urandom(4), "little")

wlan = network.WLAN(network.STA_IF)

def connect_wifi():
    if wlan.isconnected():
        return

    print("Connecting to WiFi...")
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)

    timeout = 15
    while timeout > 0:
        if wlan.isconnected():
            print("WiFi connected")
            print(wlan.ifconfig())
            return

        time.sleep(1)
        timeout -= 1

    print("WiFi connection failed")


def https_post(url, body, timeout=15):
    _, _, host, path = url.split("/", 3)

    addr = socket.getaddrinfo(
        host,
        443,
        0,
        socket.SOCK_STREAM
    )[0][-1]

    sock = socket.socket()
    sock.settimeout(timeout)

    try:
        sock.connect(addr)

        if tls:
            ctx = tls.SSLContext(tls.PROTOCOL_TLS_CLIENT)
            ctx.verify_mode = tls.CERT_NONE
            sock = ctx.wrap_socket(
                sock,
                server_hostname=host
            )
        else:
            sock = ssl.wrap_socket(
                sock,
                server_hostname=host
            )

        data = body.encode()

        sock.write(
            (
                "POST /{} HTTP/1.1\r\n"
                "Host: {}\r\n"
                "Content-Type: application/json\r\n"
                "Content-Length: {}\r\n"
                "Connection: close\r\n\r\n"
            ).format(path, host, len(data)).encode()
        )

        sock.write(data)

        status_line = sock.readline()
        return int(status_line.split()[1])

    finally:
        sock.close()


def send_to_sheets(bpm): #------------------------------------------------------Send to Sheets--------------------------------------------
    

    if not wlan.isconnected():
        print("WiFi Connection Error")
        return

    body = json.dumps({
        "boot": boot_id,
        "bpm": bpm,
        "token": SHEETS_TOKEN
    })

    try:
        code = https_post(
            SHEETS_URL,
            body
        )
        print("Sheets HTTP:", code)

    except Exception as e:
        print("Upload failed:", e)

red, ir = sensor.read_sequential(10)



#print("Red:", red)


#print("IR:", ir)
bpmOld = 0

def sensor_read():#---------------------------------------------------------Sensor Read------------------------------------------------------
    red, ir = sensor.read_sequential(100)

    mean_ir = sum(ir) / len(ir)

    raw_peaks = []

    for i in range(1, len(ir) - 1):
        if (
            ir[i] > ir[i - 1]
            and ir[i] > ir[i + 1]
            and ir[i] > mean_ir
        ):
            raw_peaks.append(i)

    peaks = []

    for p in raw_peaks:
        if not peaks or p - peaks[-1] > 10:
            peaks.append(p)

    if len(peaks) >= 2:
        intervals = []

        for i in range(1, len(peaks)):
            intervals.append(peaks[i] - peaks[i - 1])

        avg_interval = sum(intervals) / len(intervals)

        bpm = 25 * 60 / avg_interval
        bpmOld = int(bpm)
        #print(bpm)
        return int(bpm)

    return bpmOld

_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_INDICATE_DONE = const(20)

_FLAG_READ = const(0x0002)
_FLAG_NOTIFY = const(0x0010)

# Custom Service and Characteristic UUIDs
# Modify these as needed.
_SERVICE_UUID = bluetooth.UUID("3ec837af-b0c6-4e7e-a8c5-4b31311d98cf")
_CHAR_UUID = (
    bluetooth.UUID("945c4d90-825d-452f-820a-0d8b0cc74a12"),
    _FLAG_READ | _FLAG_NOTIFY,
)

_SERVICE = (
    _SERVICE_UUID,
    (_CHAR_UUID,),
)

led = Pin("LED", Pin.OUT)

class BLEText:
    def __init__(self, ble, name=""):
        # Initialize the BLE interface and register the custom service
        self._ble = ble
        self._ble.active(True)
        self._ble.irq(self._irq)
        ((self._handle,),) = self._ble.gatts_register_services((_SERVICE,))
        self._connections = set()

        # If no name is provided, generate one based on the MAC address
        if len(name) == 0:
            print("No name found")
            name = 'Pico %s' % ubinascii.hexlify(self._ble.config('mac')[1], ':').decode().upper()
        print('Device name: %s' % name)

        # Create the advertising payload with the custom service
        self._payload = advertising_payload(
            name=name, services=[_SERVICE_UUID]
        )
        self._advertise()

    def _irq(self, event, data):
        # Handle BLE events
        if event == _IRQ_CENTRAL_CONNECT:
            # A central has connected
            conn_handle, _, _ = data
            self._connections.add(conn_handle)
            print("New connection", conn_handle)
            led.value(1)
        elif event == _IRQ_CENTRAL_DISCONNECT:
            # A central has disconnected
            conn_handle, _, _ = data
            self._connections.remove(conn_handle)
            print("Disconnected", conn_handle)
            led.value(0)
            # Start advertising again to allow a new connection
            self._advertise()
        elif event == _IRQ_GATTS_INDICATE_DONE:
            # Indication confirmation received (not used here)
            conn_handle, value_handle, status = data

    def send_text(self, text):
        # Write the given text to the characteristic value
        self._ble.gatts_write(self._handle, text.encode('utf-8'))
        # Notify all connected centrals about the new value
        for conn_handle in self._connections:
            self._ble.gatts_notify(conn_handle, self._handle)

    def _advertise(self, interval_us=500000):
        print("Starting advertising")
        # Start BLE advertising with the given interval
        self._ble.gap_advertise(interval_us, adv_data=self._payload)

    def is_connected(self):
        return len(self._connections) > 0

def demo():
    potentiometer = machine.ADC(28)
    button = Pin(15, Pin.IN)
    i2c_oled = I2C(0, sda_oled=Pin(20), scl_oled=Pin(21))
    oled = ssd1306.SSD1306_I2C(128, 64, i2c_oled)
    age = 0
    resthr = 0
    oled.fill(0)
    oled.show()
    time.sleep(1)
    
    # Start WiFi
    connect_wifi()
    
    # Create a BLE instance and a BLEText peripheral
    ble = bluetooth.BLE()
    ble_text = BLEText(ble,"pico2w")

    while button.value() == 0:
        age = (potentiometer.read_u16() / 65535.0) * 100.0
        oled.fill(0)
        oled.text('Press button to', 0, 0)
        oled.text('select age', 0, 16)
        oled.text(str(age), 0, 32)
        oled.show()
        time.sleep_ms(200)
    time.sleep(1)
    while button.value() == 0:
        resthr = ((potentiometer.read_u16() / 65535.0) * 100.0) + 30.0
        oled.fill(0)
        oled.text('Press button to', 0, 0)
        oled.text('select resting', 0, 16)
        oled.text('heart rate', 0, 32)
        oled.text(str(resthr), 0, 48)
        oled.show()
        time.sleep_ms(200)
    oled.fill(0)
    oled.show()
    maxhr = 220 - age
    hrreserve = maxhr - resthr
    lowhr = 0.4 * hrreserve + resthr
    highhr = 0.6 * hrreserve + resthr

    # Continuously read input from the terminal and send it via BLE
    while True:
        print("Scanning")
        bpm = sensor_read()
        if bpm is None:
                print("No BPM found")
        if bpm is not None:
                print("BPM:", bpm)    
                oled.fill(0)
                oled.text("Heart rate:", 0, 0)
                oled.text(str(bpm), 0, 16)      
                if bpm < lowhr:
                    oled.text("Heartrate too low", 0, 32)
                    time.sleep(5)
                    if ble_text.is_connected():            
                        ble_text.send_text("Heartrate too low. BPM: {}".format(bpm))
                elif bpm > highhr:
                    oled.text("Heartrate too high", 0, 32)
                    time.sleep(5)
                    if ble_text.is_connected():            
                        ble_text.send_text("Heartrate too high. BPM: {}".format(bpm))
                oled.show()

                
        send_to_sheets(bpm)
        

if __name__ == "__main__":
    print("In main")
    print("Connecting to WiFi")
    connect_wifi()
    demo()



