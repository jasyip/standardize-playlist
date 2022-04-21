#!/usr/bin/env python

import argparse
import io
import logging
import sys
from collections.abc import Iterable
from fractions import Fraction
import math
from pathlib import Path
from typing import Any, Optional

from pprint import pformat

import pyloudnorm as pyln
import soundfile as sf
from pydub import AudioSegment
from ffmpeg_bitrate_stats.__main__ import BitrateStats

















_logger = logging.getLogger(__name__)












def _type_assert(obj: Any, t: type | Iterable[type]) -> None:

    if isinstance(t, Iterable):
        t = tuple(t)
    if not isinstance(obj, t):
        raise TypeError(f"{obj} must be {' or '.join(map(str, t)) if isinstance(t, tuple) else t}")


def _value_assert(b: bool, message: str) -> None:
    if not b:
        raise ValueError(message)






def silent_end_ind(sound: AudioSegment,
                   /,
                   silence_threshold: int | float = -50.0,
                   chunk_size: int = 1,
                  ) -> int:

    # argument type and value checking

    _type_assert(silence_threshold, (int, float))

    _value_assert(not isinstance(silence_threshold, float)
                  or  math.isfinite(silence_threshold),
                  "'silence_threshold' must be finite.",
                 )

    _value_assert(silence_threshold < 0, "'silence_threshold' must be negative number")


    _type_assert(chunk_size, int)

    _value_assert(chunk_size != 0, "'chunk_size' must be a non-zero integer")



    # Copied and adapted from https://github.com/jiaaro/pydub/blob/master/pydub/silence.py


    if chunk_size > 0:
        trim_ind = 0
        while (
                   sound[trim_ind : trim_ind + chunk_size].dBFS < silence_threshold
               and trim_ind < len(sound)
              ):
            trim_ind += chunk_size

        return min(trim_ind, len(sound))
    else:
        trim_ind = len(sound)
        while (
                   sound[trim_ind + chunk_size : trim_ind].dBFS < silence_threshold
               and trim_ind > 0
              ):
            trim_ind += chunk_size

        return max(trim_ind, 0)





def process_song(
                 input_audio        ,
                 output_audio = None,
                 input_format  : Optional[str] = None,
                 output_format : Optional[str] = None,
                 allow_overwrite     : bool                  = False,
                 lufs_normalize      : int | float           = -16.0,
                 silence_threshold   : Optional[int | float] = None,
                 iteration_chunk_len : int | Fraction        = 1,
                 silence_padding     : int                   = 0,
                ) -> Optional[io.BytesIO]:

    # argument type and value checking

    _type_assert(allow_overwrite, bool)

    _type_assert(lufs_normalize, (int, float))

    _value_assert(not isinstance(lufs_normalize, float)
                  or  math.isfinite(lufs_normalize),
                  "'lufs_normalize' must be finite.",
                 )

    _value_assert(lufs_normalize <= 0, "'lufs_normalize' must be non-positive number")

    if silence_threshold is not None:
        _type_assert(silence_threshold, (int, float))

        _value_assert(not isinstance(silence_threshold, float)
                      or  math.isfinite(silence_threshold),
                      "'silence_threshold' must be finite.",
                     )

        _value_assert(silence_threshold < 0, "'silence_threshold' must be negative number")


    _type_assert(iteration_chunk_len, (int, Fraction))

    _value_assert(not isinstance(iteration_chunk_len, Fraction)
                  or  iteration_chunk_len < 1,
                  "'iteration_chunk_len' must be less than 1:1",
                 )

    _value_assert(iteration_chunk_len > 0,
                  "'iteration_chunk_len' must be positive integer or fraction",
                 )

    _type_assert(silence_padding, int)

    _value_assert(silence_padding >= 0, "'silence_padding' must be non-negative integer")




    if return_stream := output_audio is None and isinstance(input_audio, io.IOBase):
        output_audio = io.BytesIO()

    if not isinstance(output_audio, io.IOBase) and not isinstance(input_audio, io.IOBase):

        if output_audio is None:
            output_audio = input_audio

        if isinstance(input_audio, str):
            input_audio = Path(input_audio)

        if isinstance(output_audio, str):
            output_audio = Path(output_audio)

        _value_assert(   allow_overwrite
                      or input_audio.resolve() != output_audio.resolve(),
                      ' '.join(("Must give permission to overwrite input file",
                                "or supply different output path.",
                               )),
                     )



    # ffmpeg-bitrate-stats

    bitrate_stats = BitrateStats(input_audio,
                                 stream_type="audio",
                                 chunk_size=0.1,
                                )
    bitrate_stats.calculate_statistics()
    target_bitrate = math.ceil(bitrate_stats.bitrate_stats["max_bitrate"])
    _logger.debug(pformat(bitrate_stats.bitrate_stats, width=100, indent=4))



    # pydub

    song = AudioSegment.from_file(input_audio).normalize()

    _logger.debug("Length of 'input_audio': %d ms", len(song))

    if isinstance(iteration_chunk_len, Fraction):
        iteration_chunk_len = max(round(iteration_chunk_len * len(song)), 1)


    _logger.debug(f"{iteration_chunk_len=} ms")
    _logger.debug("dBFS of audio before silence trimming: %.6f", song.dBFS)


    silent_end_ind_args = {
                           "silence_threshold" : silence_threshold,
                           "chunk_size"        : iteration_chunk_len,
                          }
    silent_end_ind_args = { k : v for k, v in silent_end_ind_args.items() if v is not None}

    if (silent_leading_ind  := silent_end_ind(
                                              song,
                                              **silent_end_ind_args,
                                             )) not in {0, len(song)}:
        song = song[ silent_leading_ind : ]
        _logger.debug(f"{silent_leading_ind=} ms")

    else:
        _logger.info("Could not find any leading silence/whole song was silent")


    silent_end_ind_args = {
                           "silence_threshold" : silence_threshold,
                           "chunk_size"        : -iteration_chunk_len,
                          }
    silent_end_ind_args = { k : v for k, v in silent_end_ind_args.items() if v is not None}

    if (silent_trailing_ind := silent_end_ind(
                                              song,
                                              **silent_end_ind_args,
                                             )) not in {0, len(song)}:
        song = song[ : silent_trailing_ind ]
        _logger.debug(f"{silent_trailing_ind=} ms")

    else:
        _logger.info("Could not find any trailing silence/whole song was silent")


    _logger.debug("Trimmed length of audio: %d ms", len(song))
    _logger.debug("dBFS of audio after silence trimming: %.6f", song.dBFS)

    padding = AudioSegment.silent(duration=silence_padding)
    song = padding + song + padding

    _logger.debug("New (padded) length of audio: %d ms", len(song))

    # compress

    _logger.debug("dBFS of audio before compression: %.6f", song.dBFS)

    song = song.compress_dynamic_range()

    _logger.debug("dBFS of compressed audio: %.6f", song.dBFS)


    with io.BytesIO() as intermediate_stream:

        song.export(intermediate_stream, format="wav")
        # song.export(intermediate_stream, format="wav", bitrate=target_bitrate)


        Path(input_audio).with_stem(Path(input_audio).stem + ".pydub").with_suffix(".wav").write_bytes(intermediate_stream.getbuffer())



        data, rate = sf.read(intermediate_stream)

    input_subtype = sf.SoundFile(input_audio).subtype


    # measure the loudness first 
    meter = pyln.Meter(rate) # create BS.1770 meter
    loudness = meter.integrated_loudness(data)

    # loudness normalize audio
    loudness_normalized_audio = pyln.normalize.loudness(data, loudness, lufs_normalize)


    with io.BytesIO() as intermediate_stream:

        sf.write(intermediate_stream,
                 loudness_normalized_audio,
                 rate,
                 format="wav",
                 subtype=input_subtype
                )

        Path(input_audio).with_stem(Path(input_audio).stem + ".sf").with_suffix(".wav").write_bytes(intermediate_stream.getbuffer())

        song = AudioSegment.from_file(intermediate_stream,
                                      format="wav",
                                     )

    song.export(output_audio,
                format=output_audio.suffix.removeprefix('.'),
                bitrate=f"{target_bitrate}k"
               )




    return output_audio if return_stream else None









if __name__ == "__main__":
    parser = argparse.ArgumentParser(
                                     description="Normalizes, trims silence and compresses an audio file.",
                                    )

    parser.add_argument("input_audio" , type=Path)
    parser.add_argument("output_audio", nargs='?', type=Path)


    meta_group = parser.add_argument_group("meta arguments")

    meta_group.add_argument(
                            "-a", "--allow-overwrite",
                            action="store_true",
                            help=' '.join(("If 'input_audio' and 'output_audio' are the same path,",
                                           "this must be passed to show explicit approval.",
                                          )),
                           )

    meta_group.add_argument("-d", "--debug", action="store_true")


    var_group = parser.add_argument_group("variable arguments")

    var_group.add_argument(
                           "-l", "--lufs-normalize",
                           default=argparse.SUPPRESS,
                           type=float,
                           help="Loudness standard to normalize to in LUFS. Must be <= 0.",
                          )

    var_group.add_argument(
                           "--silence-threshold",
                           default=argparse.SUPPRESS,
                           type=float,
                           help="Volume threshold to consider silence in dBFS. Must be < 0.",
                          )

    var_group.add_argument(
                           "--iteration-chunk-len",
                           default=argparse.SUPPRESS,
                           help=' '.join(("Length of each chunk iteration in ms.",
                                          "Must be integer > 0 or fraction in (0, 1).",
                                         )),
                          )

    var_group.add_argument(
                           "--silence-padding",
                           default=argparse.SUPPRESS,
                           type=int,
                           help="Silence padded to each end in ms. Must be integer >= 0.",
                          )




    args = vars(parser.parse_args())

    logging.basicConfig(level=logging.DEBUG if args.pop("debug") else logging.WARNING)

    if iteration_chunk_len := args.get("iteration_chunk_len"):
        if iteration_chunk_len.count('/'):
            try:
                args["iteration_chunk_len"] = Fraction(iteration_chunk_len)
            except ValueError:
                pass
        else:
            try:
                args["iteration_chunk_len"] = int(iteration_chunk_len)
            except ValueError:
                pass

    try:
        assert process_song(**args) is None
    except ValueError as e:
        parser.error(str(e))










