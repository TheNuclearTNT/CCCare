# MicroPython driver for the MAX30102, ported from the DFRobot_MAX30102
# Arduino library (MIT License, Copyright (c) 2010 DFRobot Co.Ltd).
# Only the parts cccare_pulse_oxv1.ino uses are included.

import time

from spo2_algorithm import maxim_heart_rate_and_oxygen_saturation

MAX30102_IIC_ADDRESS = 0x57

# Registers
MAX30102_FIFOWRITEPTR = 0x04
MAX30102_FIFOOVERFLOW = 0x05
MAX30102_FIFOREADPTR = 0x06
MAX30102_FIFODATA = 0x07
MAX30102_FIFOCONFIG = 0x08
MAX30102_MODECONFIG = 0x09
MAX30102_PARTICLECONFIG = 0x0A
MAX30102_LED1_PULSEAMP = 0x0C
MAX30102_LED2_PULSEAMP = 0x0D
MAX30102_MULTILEDCONFIG1 = 0x11
MAX30102_PARTID = 0xFF
MAX30102_EXPECTED_PARTID = 0x15

# sampleAverage
SAMPLEAVG_1 = 0
SAMPLEAVG_2 = 1
SAMPLEAVG_4 = 2
SAMPLEAVG_8 = 3
SAMPLEAVG_16 = 4
SAMPLEAVG_32 = 5

# ledMode
MODE_REDONLY = 2
MODE_RED_IR = 3
MODE_MULTILED = 7

# adcRange
ADCRANGE_2048 = 0
ADCRANGE_4096 = 1
ADCRANGE_8192 = 2
ADCRANGE_16384 = 3

# sampleRate
SAMPLERATE_50 = 0
SAMPLERATE_100 = 1
SAMPLERATE_200 = 2
SAMPLERATE_400 = 3
SAMPLERATE_800 = 4
SAMPLERATE_1000 = 5
SAMPLERATE_1600 = 6
SAMPLERATE_3200 = 7

# pulseWidth
PULSEWIDTH_69 = 0
PULSEWIDTH_118 = 1
PULSEWIDTH_215 = 2
PULSEWIDTH_411 = 3

# Multi-LED slots
SLOT_NONE = 0
SLOT_RED_LED = 1
SLOT_IR_LED = 2

_BUFFER_LENGTH = 100


class DFRobot_MAX30102:
    def __init__(self):
        self._i2c = None
        self._addr = MAX30102_IIC_ADDRESS
        self._active_leds = 2
        # samples read from the FIFO but not yet used (the library's senseBuf)
        self._red = []
        self._ir = []

    # ---- register helpers ----
    def _read_byte(self, reg):
        return self._i2c.readfrom_mem(self._addr, reg, 1)[0]

    def _write_byte(self, reg, value):
        self._i2c.writeto_mem(self._addr, reg, bytes([value & 0xFF]))

    def _set_bits(self, reg, mask, value):
        self._write_byte(reg, (self._read_byte(reg) & ~mask) | (value & mask))

    # ---- public API (same names as the Arduino library) ----
    def begin(self, i2c, i2c_addr=MAX30102_IIC_ADDRESS):
        """Returns True if a MAX30102 answers on the I2C bus."""
        self._i2c = i2c
        self._addr = i2c_addr
        try:
            if self._read_byte(MAX30102_PARTID) != MAX30102_EXPECTED_PARTID:
                return False
        except OSError:
            return False
        self._soft_reset()
        return True

    def sensorConfiguration(self, ledBrightness=0x1F, sampleAverage=SAMPLEAVG_4,
                            ledMode=MODE_MULTILED, sampleRate=SAMPLERATE_400,
                            pulseWidth=PULSEWIDTH_411, adcRange=ADCRANGE_4096):
        self._set_bits(MAX30102_FIFOCONFIG, 0xE0, sampleAverage << 5)
        self._set_bits(MAX30102_PARTICLECONFIG, 0xE0, adcRange << 5)
        self._set_bits(MAX30102_PARTICLECONFIG, 0x1C, sampleRate << 2)
        self._set_bits(MAX30102_PARTICLECONFIG, 0x03, pulseWidth)
        self._write_byte(MAX30102_LED1_PULSEAMP, ledBrightness)
        self._write_byte(MAX30102_LED2_PULSEAMP, ledBrightness)
        self._set_bits(MAX30102_MULTILEDCONFIG1, 0x0F, SLOT_RED_LED)
        if ledMode > MODE_REDONLY:
            self._set_bits(MAX30102_MULTILEDCONFIG1, 0xF0, SLOT_IR_LED << 4)
        self._set_bits(MAX30102_MODECONFIG, 0x3F, ledMode)
        self._active_leds = 1 if ledMode == MODE_REDONLY else 2
        self._set_bits(MAX30102_FIFOCONFIG, 0x10, 0x10)  # enable FIFO rollover
        self._reset_fifo()

    def getRed(self):
        self._get_new_data()
        return self._red[-1]

    def getIR(self):
        self._get_new_data()
        return self._ir[-1]

    def heartrateAndOxygenSaturation(self):
        """Collects 100 samples (4 seconds) and runs the Maxim algorithm.

        Returns (SPO2, SPO2Valid, heartRate, heartRateValid), the four values
        the Arduino version writes through pointers.
        """
        red_buffer = []
        ir_buffer = []
        while len(ir_buffer) < _BUFFER_LENGTH:
            self._get_new_data()
            take = min(len(self._ir), _BUFFER_LENGTH - len(ir_buffer))
            red_buffer.extend(self._red[:take])
            ir_buffer.extend(self._ir[:take])
            # leftover samples stay for the next call, like the library's buffer
            self._red = self._red[take:]
            self._ir = self._ir[take:]
        return maxim_heart_rate_and_oxygen_saturation(ir_buffer, red_buffer)

    # ---- internals ----
    def _soft_reset(self):
        self._set_bits(MAX30102_MODECONFIG, 0x40, 0x40)
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < 100:
            if not self._read_byte(MAX30102_MODECONFIG) & 0x40:
                break
            time.sleep_ms(1)

    def _reset_fifo(self):
        self._write_byte(MAX30102_FIFOWRITEPTR, 0)
        self._write_byte(MAX30102_FIFOOVERFLOW, 0)
        self._write_byte(MAX30102_FIFOREADPTR, 0)

    def _get_new_data(self):
        """Wait until the FIFO has samples, then read all of them."""
        while True:
            read_ptr = self._read_byte(MAX30102_FIFOREADPTR)
            write_ptr = self._read_byte(MAX30102_FIFOWRITEPTR)
            if read_ptr != write_ptr:
                break
            time.sleep_ms(1)

        count = write_ptr - read_ptr
        if count < 0:
            count += 32
        for _ in range(count):
            if self._active_leds > 1:
                b = self._i2c.readfrom_mem(self._addr, MAX30102_FIFODATA, 6)
                self._red.append(((b[0] << 16) | (b[1] << 8) | b[2]) & 0x3FFFF)
                self._ir.append(((b[3] << 16) | (b[4] << 8) | b[5]) & 0x3FFFF)
            else:
                b = self._i2c.readfrom_mem(self._addr, MAX30102_FIFODATA, 3)
                self._red.append(((b[0] << 16) | (b[1] << 8) | b[2]) & 0x3FFFF)
                self._ir.append(0)
