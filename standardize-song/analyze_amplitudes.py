#!/usr/bin/env python


import argparse
import matplotlib.pyplot as plt
import numpy as np
import wave
import sys

from pathlib import Path

if __name__ == "__main__":


    parser = argparse.ArgumentParser()

    parser.add_argument("audio", type=Path)

    args = parser.parse_args()


    spf = wave.open(str(args.audio), "r")

    # Extract Raw Audio from Wav
    signal = spf.readframes(-1)
    signal = np.fromstring(signal, np.int16)
    fs = spf.getframerate()

    # If Stereo
    if spf.getnchannels() == 2:
        print("Just mono files")
        sys.exit(0)


    Time = np.linspace(0, len(signal) / fs, num=len(signal))

    plt.figure(1)
    plt.title("Signal Wave...")
    plt.plot(Time, signal)
    plt.show()
