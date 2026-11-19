# Heart rate / SpO2 algorithm, ported line for line from the DFRobot_MAX30102
# Arduino library (src/SPO2/algorithm.cpp), which is Maxim's MAXREFDES117 code.
#
# Copyright (C) 2016 Maxim Integrated Products, Inc., All Rights Reserved.
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions: The above copyright
# notice and this permission notice shall be included in all copies or
# substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS",
# WITHOUT WARRANTY OF ANY KIND.
#
# C integer division rounds toward zero and Python's // rounds down, so the
# helpers below reproduce the C results exactly.

FREQ_S = 25                 # sampling frequency (400 Hz / 16-sample average)
BUFFER_SIZE = FREQ_S * 4    # 100 samples = 4 seconds
MA4_SIZE = 4

# uch_spo2_table is approximated as -45.060*ratio^2 + 30.354*ratio + 94.845
SPO2_TABLE = (
    95, 95, 95, 96, 96, 96, 97, 97, 97, 97, 97, 98, 98, 98, 98, 98, 99, 99, 99, 99,
    99, 99, 99, 99, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100,
    100, 100, 100, 100, 99, 99, 99, 99, 99, 99, 99, 99, 98, 98, 98, 98, 98, 98, 97, 97,
    97, 97, 96, 96, 96, 96, 95, 95, 95, 94, 94, 94, 93, 93, 93, 92, 92, 92, 91, 91,
    90, 90, 89, 89, 89, 88, 88, 87, 87, 86, 86, 85, 85, 84, 84, 83, 82, 82, 81, 81,
    80, 80, 79, 78, 78, 77, 76, 76, 75, 74, 74, 73, 72, 72, 71, 70, 69, 69, 68, 67,
    66, 66, 65, 64, 63, 62, 62, 61, 60, 59, 58, 57, 56, 56, 55, 54, 53, 52, 51, 50,
    49, 48, 47, 46, 45, 44, 43, 42, 41, 40, 39, 38, 37, 36, 35, 34, 33, 31, 30, 29,
    28, 27, 26, 25, 23, 22, 21, 20, 19, 17, 16, 15, 14, 12, 11, 10, 9, 7, 6, 5,
    3, 2, 1,
    0,  # the C array has 184 slots but only 183 values, so the last one is 0
)


def _idiv(a, b):
    """C-style integer division (rounds toward zero)."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def _i32(v):
    """Wrap to a signed 32-bit int, like int32_t overflow on the Pico."""
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v & 0x80000000 else v


def maxim_heart_rate_and_oxygen_saturation(ir_buffer, red_buffer):
    """Returns (spo2, spo2_valid, heart_rate, heart_rate_valid).

    Invalid values are -999 with a valid flag of 0, same as the C library.
    """
    n_ir_buffer_length = len(ir_buffer)

    # calculate DC mean and subtract DC from ir
    ir_mean = sum(ir_buffer) // n_ir_buffer_length

    # remove DC and invert signal so that we can use peak detector as valley detector
    an_x = [-(v - ir_mean) for v in ir_buffer]

    # 4 pt moving average
    for k in range(BUFFER_SIZE - MA4_SIZE):
        an_x[k] = _idiv(an_x[k] + an_x[k + 1] + an_x[k + 2] + an_x[k + 3], 4)

    # calculate threshold
    th1 = _idiv(sum(an_x[:BUFFER_SIZE]), BUFFER_SIZE)
    if th1 < 30:
        th1 = 30  # min allowed
    if th1 > 60:
        th1 = 60  # max allowed

    valley_locs = [0] * 15
    # since we flipped the signal, we use the peak detector as a valley detector
    npks = maxim_find_peaks(valley_locs, an_x, BUFFER_SIZE, th1, 4, 15)

    if npks >= 2:
        interval_sum = 0
        for k in range(1, npks):
            interval_sum += valley_locs[k] - valley_locs[k - 1]
        interval_sum = _idiv(interval_sum, npks - 1)
        heart_rate = _idiv(FREQ_S * 60, interval_sum)
        hr_valid = 1
    else:
        heart_rate = -999  # unable to calculate because # of peaks are too small
        hr_valid = 0

    # load raw values again for SpO2 calculation: RED (=y) and IR (=x)
    an_x = list(ir_buffer)
    an_y = list(red_buffer)

    exact_valley_count = npks

    for k in range(exact_valley_count):
        if valley_locs[k] > BUFFER_SIZE:
            return -999, 0, heart_rate, hr_valid  # valley loc out of range

    ratios = [0] * 5
    ratio_count = 0
    x_dc_max_idx = 0
    y_dc_max_idx = 0

    # find max between two valley locations and use the ratio between the
    # AC and DC components of IR & red for SpO2
    for k in range(exact_valley_count - 1):
        y_dc_max = -16777216
        x_dc_max = -16777216
        l0 = valley_locs[k]
        l1 = valley_locs[k + 1]
        if l1 - l0 > 3:
            for i in range(l0, l1):
                if an_x[i] > x_dc_max:
                    x_dc_max = an_x[i]
                    x_dc_max_idx = i
                if an_y[i] > y_dc_max:
                    y_dc_max = an_y[i]
                    y_dc_max_idx = i
            y_ac = _i32((an_y[l1] - an_y[l0]) * (y_dc_max_idx - l0))  # red
            y_ac = an_y[l0] + _idiv(y_ac, l1 - l0)
            y_ac = an_y[y_dc_max_idx] - y_ac  # subtract linear DC component from raw
            x_ac = _i32((an_x[l1] - an_x[l0]) * (x_dc_max_idx - l0))  # ir
            x_ac = an_x[l0] + _idiv(x_ac, l1 - l0)
            x_ac = an_x[y_dc_max_idx] - x_ac  # (original library uses the red max index here)
            nume = _i32(y_ac * x_dc_max) >> 7  # prepare x100 to preserve floating value
            denom = _i32(x_ac * y_dc_max) >> 7
            if denom > 0 and ratio_count < 5 and nume != 0:
                ratios[ratio_count] = _idiv(_i32(nume * 100), denom)
                ratio_count += 1

    # choose the median value since the PPG signal may vary from beat to beat
    maxim_sort_ascend(ratios, ratio_count)
    middle_idx = ratio_count // 2

    if middle_idx > 1:
        ratio_average = _idiv(ratios[middle_idx - 1] + ratios[middle_idx], 2)  # use median
    else:
        ratio_average = ratios[middle_idx]

    if 2 < ratio_average < 184:
        return SPO2_TABLE[ratio_average], 1, heart_rate, hr_valid
    return -999, 0, heart_rate, hr_valid  # ratio out of range


def maxim_find_peaks(locs, x, size, min_height, min_distance, max_num):
    """Find at most max_num peaks above min_height separated by at least min_distance.
    Fills locs in place and returns the number of peaks."""
    npks = maxim_peaks_above_min_height(locs, x, size, min_height)
    npks = maxim_remove_close_peaks(locs, npks, x, min_distance)
    return min(npks, max_num)


def maxim_peaks_above_min_height(locs, x, size, min_height):
    """Find all peaks above min_height. Returns the number of peaks."""
    i = 1
    npks = 0
    while i < size - 1:
        if x[i] > min_height and x[i] > x[i - 1]:  # find left edge of potential peaks
            width = 1
            while i + width < size and x[i] == x[i + width]:  # find flat peaks
                width += 1
            if i + width < size and x[i] > x[i + width] and npks < 15:  # find right edge
                locs[npks] = i  # for flat peaks, peak location is left edge
                npks += 1
                i += width + 1
            else:
                i += width
        else:
            i += 1
    return npks


def maxim_remove_close_peaks(locs, npks, x, min_distance):
    """Remove peaks separated by less than min_distance. Returns the new count."""
    # order peaks from large to small
    maxim_sort_indices_descend(x, locs, npks)

    i = -1
    while i < npks:
        old_npks = npks
        npks = i + 1
        for j in range(i + 1, old_npks):
            dist = locs[j] - (-1 if i == -1 else locs[i])  # lag-zero peak of autocorr is at index -1
            if dist > min_distance or dist < -min_distance:
                locs[npks] = locs[j]
                npks += 1
        i += 1

    # re-sort indices into ascending order
    maxim_sort_ascend(locs, npks)
    return npks


def maxim_sort_ascend(x, size):
    """Sort the first `size` items in ascending order (insertion sort)."""
    for i in range(1, size):
        temp = x[i]
        j = i
        while j > 0 and temp < x[j - 1]:
            x[j] = x[j - 1]
            j -= 1
        x[j] = temp


def maxim_sort_indices_descend(x, indx, size):
    """Sort indices by descending value of x (insertion sort)."""
    for i in range(1, size):
        temp = indx[i]
        j = i
        while j > 0 and x[temp] > x[indx[j - 1]]:
            indx[j] = indx[j - 1]
            j -= 1
        indx[j] = temp
