#!/usr/bin/env python3
"""
quality.py — VMAF / SSIM / PSNR of a prepared file against its source.

    py tools/quality.py --ffmpeg PATH SOURCE OUTPUT [OUTPUT ...] [--seconds 20]

Both files are decoded and compared frame by frame, by frame index (first
--seconds seconds), so the output must have the same frames in the same order
as the source over that span — true for an encode made with
`-fps_mode passthrough`; a conformed (cfr) encode may duplicate or drop a
frame and then everything after it is paired one off, so conform the
reference identically or compare passthrough encodes. Sources
here are already-lossy YouTube streams; the question is whether the
intermediate adds *visible* damage on top, not whether it is transparent to a
pristine master. Rule of thumb: VMAF above ~93 against the source is not
distinguishable in an edit, ~90 is borderline on text and fine gradients.

Also writes a side-by-side crop PNG per output at --crop-at seconds (source
left, output right, 1:1 pixels from the frame centre), for eyeballing text
edges and gradients where a single score misleads.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess


def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                       encoding="utf-8", errors="replace")
    return p.stdout or ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("outputs", nargs="+")
    ap.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--crop-at", type=float, default=5.0)
    ap.add_argument("--crop-size", type=int, default=480)
    ap.add_argument("--out-dir", default=".")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)

    for out in a.outputs:
        name = os.path.splitext(os.path.basename(out))[0]
        # Frames are paired by INDEX, not timestamp: a WebM source carries
        # millisecond timestamps and an MP4 output finer ones, and the filters'
        # timestamp sync would otherwise pair a frame with its neighbour every
        # hundred frames or so, which reads as a 25 dB frame in a 52 dB stream.
        align = "setpts=N/(FRAME_RATE*TB)"
        graph = (f"[0:v]{align}[d];[1:v]{align}[r];"
                 "[d][r]libvmaf=model=version=vmaf_v0.6.1:n_threads=16")
        log = run([a.ffmpeg, "-v", "info", "-nostdin", "-t", str(a.seconds), "-i", out,
                   "-t", str(a.seconds), "-i", a.source, "-lavfi", graph, "-f", "null", "-"])
        vmaf = re.search(r"VMAF score: ([\d.]+)", log)
        # libvmaf prints feature means only in its JSON log; fall back to the
        # plain filters for PSNR/SSIM so the numbers are always there.
        ssim = re.search(r"All:([\d.]+)", run([a.ffmpeg, "-v", "info", "-nostdin", "-t", str(a.seconds),
                                                "-i", out, "-t", str(a.seconds), "-i", a.source,
                                                "-lavfi", f"[0:v]{align}[d];[1:v]{align}[r];[d][r]ssim",
                                                "-f", "null", "-"]))
        psnr = re.search(r"average:([\d.]+)", run([a.ffmpeg, "-v", "info", "-nostdin", "-t", str(a.seconds),
                                                    "-i", out, "-t", str(a.seconds), "-i", a.source,
                                                    "-lavfi", f"[0:v]{align}[d];[1:v]{align}[r];[d][r]psnr",
                                                    "-f", "null", "-"]))
        size = os.path.getsize(out) / 1e6
        print(f"{name}: VMAF {vmaf.group(1) if vmaf else '?'}  SSIM {ssim.group(1) if ssim else '?'}  "
              f"PSNR {psnr.group(1) if psnr else '?'} dB  ({size:.1f} MB)")

        crop = a.crop_size
        png = os.path.join(a.out_dir, f"crop_{name}.png")
        run([a.ffmpeg, "-y", "-v", "error", "-ss", str(a.crop_at), "-i", a.source,
             "-ss", str(a.crop_at), "-i", out, "-lavfi",
             f"[0:v]crop={crop}:{crop}[l];[1:v]crop={crop}:{crop}[r];[l][r]hstack",
             "-frames:v", "1", png])
        print(f"  crop: {png}")


if __name__ == "__main__":
    main()
