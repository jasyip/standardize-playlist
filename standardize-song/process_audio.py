#!/usr/bin/env python

import argparse
import logging
import sys
import io
from pathlib import Path
from typing import Optional, NoReturn

import pyloudnorm as pyln
import soundfile as sf
from pydub import AudioSegment
from pydub.silence import detect_silence


_logger = logging.getLogger(__name__)



def _arg_error(message: str) -> NoReturn:
    _logger.critical(message)
    raise ValueError


def process_song(
                 input_audio        ,
                 output_audio = None,
                 allow_overwrite   : bool        = False,
                 lufs_normalize    : int | float = -14.0,
                 min_silence_len   : int         = 1000 ,
                 silence_threshold : int | float = -30.0,
                ) -> Optional[io.BytesIO]:

    if not isinstance(allow_overwrite, bool):
        _arg_error("'allow_overwrite' must be a boolean")

    if not (isinstance(lufs_normalize, (int, float)) and lufs_normalize <= 0):
        _arg_error("'silence_length' must be non-positive")

    if not (isinstance(min_silence_len, int) and min_silence_len >= 0):
        _arg_error("'minimum_silence_length' must be non-negative")

    if not (isinstance(silence_threshold, (int, float)) and silence_threshold < 0):
        _arg_error("'silence_length' must be negative")


    if return_stream := output_audio is None and isinstance(input_audio, io.IOBase):
        output_audio = io.BytesIO()

    if not isinstance(output_audio, io.IOBase) and not isinstance(input_audio, io.IOBase):

        if output_audio is None:
            output_audio = input_audio

        if isinstance(input_audio, str):
            input_audio = Path(input_audio)

        if isinstance(output_audio, str):
            output_audio = Path(output_audio)

        if not allow_overwrite and input_audio.resolve() == output_audio.resolve():
            _arg_error(' '.join(("Must give permission to overwrite input file",
                                  "or supply different output path.",
                                 )))




    # pydub

    song = AudioSegment.from_file(input_audio).normalize()

    silence_segments = detect_silence(
                                      song,
                                      min_silence_len=min_silence_len,
                                      silence_thresh=silence_threshold,
                                     )

    _logger.debug("Length of 'input_audio': %d ms", len(song))
    _logger.debug(f"Segments of detected silence: {silence_segments}")

    if silence_segments and silence_segments != [[0, len(song)]]:
        if silence_segments[-1][1] == len(song):
            song = song[ : silence_segments[-1][0] ]
        if silence_segments[0][0] == 0:
            song = song[ silence_segments[0][1] : ]

    _logger.debug("New length of audio: %d ms", len(song))

    # compress

    _logger.debug("dBFS of audio currently: %.6f", song.dBFS)

    song = song.compress_dynamic_range()

    _logger.debug("dBFS of compressed audio: %.6f", song.dBFS)

    intermediate_stream = io.BytesIO()

    song.export(intermediate_stream, format="wav")


    # normalize
    data, rate = sf.read(intermediate_stream)



    # measure the loudness first 
    meter = pyln.Meter(rate) # create BS.1770 meter
    loudness = meter.integrated_loudness(data)

    # loudness normalize audio to -12 dB LUFS
    loudness_normalized_audio = pyln.normalize.loudness(data, loudness, lufs_normalize)

    sf.write(output_audio, loudness_normalized_audio, rate)

    if return_stream:
        return output_audio









if __name__ == "__main__":
    parser = argparse.ArgumentParser(
                                     description="Normalizes, trims silence and compresses an audio file.",
                                    )

    parser.add_argument("input_audio" , type=Path)
    parser.add_argument("output_audio", nargs='?', type=Path)


    meta_group = parser.add_argument_group("meta arguments")

    meta_group.add_argument(
                            "--allow-overwrite",
                            action="store_true",
                            help=' '.join(("If 'input_audio' and 'output_audio' are the same path,",
                                           "this must be passed to show explicit approval.",
                                          )),
                           )

    meta_group.add_argument("--debug", action="store_true")


    var_group = parser.add_argument_group("variable arguments")

    var_group.add_argument(
                           "--lufs-normalize",
                           default=argparse.SUPPRESS,
                           type=float,
                           help="Loudness standard to normalize to in LUFS. Must be <= 0.",
                          )
    var_group.add_argument(
                           "--min-silence-len",
                           default=argparse.SUPPRESS,
                           type=int,
                           help=' '.join(("Minimum length of silence segment to consider",
                                          "in milliseconds. Must be integer > 0.",
                                          )),
                          )
    var_group.add_argument(
                           "--silence-threshold",
                           default=argparse.SUPPRESS,
                           type=float,
                           help="Volume threshold to consider silence in dBFS. Must be < 0.",
                          )



    args = vars(parser.parse_args())

    logging.basicConfig(level=logging.DEBUG if args.pop("debug") else logging.WARNING)


    try:
        assert process_song(**args) is None
    except ValueError as e:
        parser.exit(2)
