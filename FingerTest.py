from machine import Pin, I2C
from max30102 import MAX30102

i2c = I2C(
    0,
    scl=Pin(1),
    sda=Pin(0),
    freq=400000
)

print("Devices:", i2c.scan())

sensor = MAX30102(i2c)

red, ir = sensor.read_sequential(10)

print("Red:", red)
print("IR:", ir)

def sensor_read():
    red, ir = sensor.read_sequential(100)

    mean_ir = sum(ir) / len(ir)

    raw_peaks = []

    for i in range(1, len(ir)-1):
        if (ir[i] > ir[i-1] and ir[i] > ir[i+1] and ir[i] > mean_ir):
            raw_peaks.append(i)

    peaks = []
    for p in raw_peaks:
        if not peaks or p- peaks[-1] > 10:
            peaks.append(p)
    if len(peaks) >= 2:

        intervals = []

        for i in range(1, len(peaks)):
            intervals.append(peaks[i] - peaks[i-1])

        avg_interval = sum(intervals) / len(intervals)

        bpm = 25 * 60 / avg_interval
        
    print(bpm)
while True:
    sensor_read()