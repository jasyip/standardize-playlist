#!/usr/bin/env python

from pathlib import Path
from ffmpeg_bitrate_stats.__main__ import BitrateStats
from pprint import pformat


for path in (*Path().glob("*.wav"), *Path().glob("*.flac")):
    bs = BitrateStats(path, "audio", chunk_size=0.1)
    bs.calculate_statistics()
    print(pformat(bs.bitrate_stats, indent=4))
