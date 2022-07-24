import os
import pathlib
import json
import shlex
from pathlib import Path
from subprocess import run, CalledProcessError

import opentimelineio as otio
import pyseq

VMAF_LIB_DIR = os.getenv(
    'VMAF_LIB_DIR',
    f'{os.path.dirname(__file__)}/.venv/usr/local/lib/x86_64-linux-gnu'
)


# Which vmaf model to use
VMAF_HD_MODEL = os.getenv(
    'VMAF_MODEL',
    f'{os.path.dirname(__file__)}/../../tools/vmaf-2.3.1/model/'
) + "/vmaf_v0.6.1.json"


VMAF_4K_MODEL = os.getenv(
    'VMAF_MODEL',
    f'{os.path.dirname(__file__)}/../../tools/vmaf-2.3.1/model'
) + "/vmaf_4k_v0.6.1.json"


# Based on accepted answer here:
# https://stackoverflow.com/questions/1094841/get-human-readable-version-of-file-size
def sizeof_fmt(path, suffix="B"):
    num = os.path.getsize(path)
    for unit in ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"]:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0

    return f"{num:.1f}Yi{suffix}"


def calculate_rate(rate_str):
    numerator, denominator = rate_str.split('/')
    return float(numerator) / float(denominator)


def get_nearest_model(width):
    models = {
        1920: VMAF_HD_MODEL,
        4096: VMAF_4K_MODEL
    }
    diff = lambda list_value: abs(list_value - width)

    return models[min(models, key=diff)]


def get_media_info(path, startframe=None):
    cmd = f'ffprobe ' \
          f'-v quiet ' \
          f'-hide_banner ' \
          f'-print_format json ' \
          f'-show_streams ' \
          f'-i "{path.as_posix()}"'

    if startframe:
         cmd = cmd + f' -start_number %d ' % startframe

    env = os.environ
    if 'LD_LIBRARY_PATH' in env:
        env.update({'LD_LIBRARY_PATH': env['LD_LIBRARY_PATH'] + ":" + VMAF_LIB_DIR})

    else:
        env.update({'LD_LIBRARY_PATH': VMAF_LIB_DIR})

    try:
        proc = run(shlex.split(cmd), capture_output=True, env=env, check=True)
        raw_json = json.loads(proc.stdout)

    except CalledProcessError as err:
        print(f'Unable to probe "{path.name}, {err}"')
        return None

    stream = None
    for raw_stream in raw_json.get('streams'):
        if raw_stream.get('codec_type') == 'video':
            stream = raw_stream
            break

    if not stream:
        print(f'Unable to locate video stream in "{path.name}"')
        return None

    info = {
        'path': path.as_posix(),
        'width': stream.get('width'),
        'height': stream.get('height'),
        'in': startframe or 0,
        'duration': int(stream.get('nb_frames', stream.get('duration_ts', 1))),
        'rate': calculate_rate(stream.get('r_frame_rate'))
    }

    return info


def create_media_reference(path, source_clip):
    config = get_source_metadata_dict(source_clip)
    rate = float(config.get('rate'))
    duration = float(config.get('duration'))

    if path.is_dir():
        # Create ImageSequenceReference
        seq = pyseq.get_sequences(path.as_posix())[0]
        available_range = otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(
                seq.start(), rate
            ),
            duration=otio.opentime.RationalTime(
                seq.length(), rate
            )
        )
        mr = otio.schema.ImageSequenceReference(
            target_url_base=Path(seq.directory()).as_posix(),
            name_prefix=seq.head(),
            name_suffix=seq.tail(),
            start_frame=seq.start(),
            frame_step=1,
            frame_zero_padding=len(max(seq.digits, key=len)),
            rate=rate,
            available_range=available_range
        )

    else:
        # Create ExternalReference
        available_range = otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(
                0, rate
            ),
            duration=otio.opentime.RationalTime(
                duration, rate
            )
        )
        mr = otio.schema.ExternalReference(
            target_url=path.resolve().as_posix(),
            available_range=available_range,
        )
        mr.name = path.name

    return mr


def get_test_metadata_dict(otio_clip, testname):
    aswf_meta = otio_clip.metadata.setdefault('aswf_enctests', {})
    enc_meta = aswf_meta.setdefault(testname, {})

    return enc_meta


def get_source_metadata_dict(source_clip):
    return source_clip.metadata['aswf_enctests']['source_info']