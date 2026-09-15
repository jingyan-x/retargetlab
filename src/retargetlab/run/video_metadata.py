"""Read a selected episode's actual video dimensions without changing media."""

from __future__ import annotations

from pathlib import Path


def probe_video(path: Path, start_s: float, fps: float) -> dict:
    import av

    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        if start_s > 0:
            container.seek(int(start_s / stream.time_base), stream=stream, backward=True)
        for frame in container.decode(stream):
            if frame.time is not None and float(frame.time) >= start_s - 0.5 / fps:
                return {
                    "shape_hwc": [frame.height, frame.width, 3],
                    "decoded_timestamp_s": float(frame.time),
                    "decoder": stream.codec_context.name,
                    "pixel_format": frame.format.name,
                    "average_rate": float(stream.average_rate) if stream.average_rate else None,
                    "start_timestamp_s": start_s,
                }
    raise ValueError(f"no video frame at the selected episode start: {path.name}")
