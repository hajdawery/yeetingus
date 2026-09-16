#!/usr/bin/env python3
"""
bench.py — measure intermediate-format candidates for YEETingus.

For every (source, strategy) pair this runs one ffmpeg job and records:

  processing  wall time, realtime factor, encoded fps, mean CPU %, mean GPU %
  file        output size, output/source ratio, bitrate
  seeking     latency to decode the first frame after a seek, over a fixed
              pseudo-random schedule of forward / backward / long-jump / nearby
              seeks (median, p95, worst)

Usage:
    py -3.11 tools/bench.py --src DIR --out DIR [--only STRATEGY,...]
                            [--sources NAME,...] [--seeks N] [--ffmpeg PATH]

Writes results.csv and results.md into --out. Strategies live in STRATEGIES
below; each is a small dict, so adding one is a one-liner. Nothing here is
imported by the application — it is a lab tool, kept so a future ffmpeg or
Resolve release can be re-measured against the same schedule.

The seek test spawns one ffmpeg per seek, so its absolute numbers include
process start-up; the "spawn" row for each output measures that overhead so
it can be subtracted. Relative ordering between strategies is what matters.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import shutil
import statistics
import subprocess
import threading
import time

try:
    import psutil
except ImportError:  # pragma: no cover - optional
    psutil = None

# --------------------------------------------------------------------------- #
# Strategies
# --------------------------------------------------------------------------- #
# gop: keyframe interval in SECONDS (converted per source fps), or None for
#      "leave the encoder's default" (remux, intra-only codecs).
# args: ffmpeg output options. {gop} and {fps} are substituted.
# ext: container.
# hwdec: decode the source with CUDA first (frames stay on the GPU for nvenc
#        when hwup is set, otherwise they are copied back to system memory).
# pix: force this pixel format (8-bit only encoders need yuv420p).

STRATEGIES: dict[str, dict] = {
    # ---- A. remux, no re-encode ------------------------------------------ #
    "remux_mkv": {"ext": "mkv", "args": ["-c", "copy"]},
    "remux_mp4": {"ext": "mp4", "args": ["-c", "copy", "-movflags", "+faststart"]},
    "remux_mov": {"ext": "mov", "args": ["-c", "copy", "-movflags", "+faststart"]},

    # ---- B. native MPEG-4 Part 2 ------------------------------------------ #
    # q:v 3 is near-transparent for already-lossy sources; higher = smaller.
    "mpeg4_g250ms":  {"ext": "mp4", "gop": 0.25, "pix": "yuv420p",
                      "args": ["-c:v", "mpeg4", "-q:v", "3", "-bf", "0", "-g", "{gop}",
                               "-threads", "16", "-movflags", "+faststart"]},
    "mpeg4_g500ms":  {"ext": "mp4", "gop": 0.5, "pix": "yuv420p",
                      "args": ["-c:v", "mpeg4", "-q:v", "3", "-bf", "0", "-g", "{gop}",
                               "-threads", "16", "-movflags", "+faststart"]},
    "mpeg4_g1000ms": {"ext": "mp4", "gop": 1.0, "pix": "yuv420p",
                      "args": ["-c:v", "mpeg4", "-q:v", "3", "-bf", "0", "-g", "{gop}",
                               "-threads", "16", "-movflags", "+faststart"]},
    "mpeg4_g500ms_bf2": {"ext": "mp4", "gop": 0.5, "pix": "yuv420p",
                         "args": ["-c:v", "mpeg4", "-q:v", "3", "-bf", "2", "-g", "{gop}",
                                  "-threads", "16", "-movflags", "+faststart"]},
    "mpeg4_g500ms_q5": {"ext": "mp4", "gop": 0.5, "pix": "yuv420p",
                        "args": ["-c:v", "mpeg4", "-q:v", "5", "-bf", "0", "-g", "{gop}",
                                 "-threads", "16", "-movflags", "+faststart"]},
    "mpeg4_g500ms_hwdec": {"ext": "mp4", "gop": 0.5, "pix": "yuv420p", "hwdec": True,
                           "args": ["-c:v", "mpeg4", "-q:v", "3", "-bf", "0", "-g", "{gop}",
                                    "-threads", "16", "-movflags", "+faststart"]},

    # ---- C. hardware AV1 (NVENC) ------------------------------------------ #
    "av1_nvenc_g500ms":  {"ext": "mp4", "gop": 0.5, "hwdec": True, "hwup": True,
                          "args": ["-c:v", "av1_nvenc", "-preset", "p1", "-tune", "ll",
                                   "-rc", "vbr", "-cq", "28", "-b:v", "0", "-bf", "0",
                                   "-g", "{gop}", "-movflags", "+faststart"]},
    "av1_nvenc_g1000ms": {"ext": "mp4", "gop": 1.0, "hwdec": True, "hwup": True,
                          "args": ["-c:v", "av1_nvenc", "-preset", "p1", "-tune", "ll",
                                   "-rc", "vbr", "-cq", "28", "-b:v", "0", "-bf", "0",
                                   "-g", "{gop}", "-movflags", "+faststart"]},
    "av1_nvenc_g500ms_p4": {"ext": "mp4", "gop": 0.5, "hwdec": True, "hwup": True,
                            "args": ["-c:v", "av1_nvenc", "-preset", "p4",
                                     "-rc", "vbr", "-cq", "28", "-b:v", "0", "-bf", "0",
                                     "-g", "{gop}", "-movflags", "+faststart"]},
    "av1_nvenc_g500ms_cpudec": {"ext": "mp4", "gop": 0.5,
                                "args": ["-c:v", "av1_nvenc", "-preset", "p1", "-tune", "ll",
                                         "-rc", "vbr", "-cq", "28", "-b:v", "0", "-bf", "0",
                                         "-g", "{gop}", "-movflags", "+faststart"]},

    # ---- D. VP9 re-encode -------------------------------------------------- #
    "vp9_rt_g500ms": {"ext": "mkv", "gop": 0.5,
                      "args": ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8",
                               "-row-mt", "1", "-threads", "16", "-crf", "30", "-b:v", "0",
                               "-g", "{gop}", "-lag-in-frames", "0"]},

    # ---- E. others --------------------------------------------------------- #
    "svtav1_p12_g500ms": {"ext": "mp4", "gop": 0.5,
                          "args": ["-c:v", "libsvtav1", "-preset", "12", "-crf", "30",
                                   "-g", "{gop}", "-svtav1-params", "lookahead=0",
                                   "-movflags", "+faststart"]},
    "mjpeg_q3":   {"ext": "mov", "pix": "yuvj420p",
                   "args": ["-c:v", "mjpeg", "-q:v", "3", "-threads", "16"]},
    "dnxhr_hq":   {"ext": "mov", "pix": "yuv422p",
                   "args": ["-c:v", "dnxhd", "-profile:v", "dnxhr_hq", "-threads", "16"]},
    "prores_lt":  {"ext": "mov", "pix": "yuv422p10le",
                   "args": ["-c:v", "prores_ks", "-profile:v", "1", "-threads", "16"]},
    "cineform":   {"ext": "mov", "pix": "yuv422p10le",
                   "args": ["-c:v", "cfhd", "-quality", "film3", "-threads", "16"]},
}

# Strategies whose cost scales badly are skipped above this pixel count unless
# --all is given; keeps a full run to an evening rather than a weekend.
HEAVY = {"svtav1_p12_g500ms", "vp9_rt_g500ms", "cineform", "prores_lt", "dnxhr_hq", "mjpeg_q3"}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def run(cmd: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout)


def probe(ffprobe: str, path: str) -> dict:
    p = run([ffprobe, "-v", "error", "-show_entries",
             "format=duration,size,bit_rate:stream=codec_name,codec_type,width,height,"
             "pix_fmt,r_frame_rate,avg_frame_rate,nb_frames",
             "-of", "json", path])
    data = json.loads(p.stdout or "{}")
    fmt = data.get("format", {})
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    num, den = (v.get("r_frame_rate") or "0/1").split("/")
    fps = float(num) / float(den) if float(den) else 0.0
    return {
        "duration": float(fmt.get("duration") or 0),
        "size": int(fmt.get("size") or 0),
        "bitrate": int(fmt.get("bit_rate") or 0),
        "vcodec": v.get("codec_name", "?"),
        "acodec": a.get("codec_name", "-"),
        "width": v.get("width", 0), "height": v.get("height", 0),
        "pix_fmt": v.get("pix_fmt", "?"), "fps": fps,
    }


def count_frames(ffprobe: str, path: str) -> int:
    p = run([ffprobe, "-v", "error", "-select_streams", "v:0", "-count_packets",
             "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", path])
    try:
        return int((p.stdout or "0").strip().split(",")[0])
    except ValueError:
        return 0


class Sampler(threading.Thread):
    """Mean CPU% (whole machine) and GPU% while a job runs."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.cpu: list[float] = []
        self.gpu: list[float] = []
        self._done = threading.Event()
        self.smi = shutil.which("nvidia-smi")

    def run(self) -> None:
        if psutil:
            psutil.cpu_percent(None)
        while not self._done.wait(0.5):
            if psutil:
                self.cpu.append(psutil.cpu_percent(None))
            if self.smi:
                try:
                    out = run([self.smi, "--query-gpu=utilization.gpu,utilization.encoder,"
                               "utilization.decoder", "--format=csv,noheader,nounits"]).stdout
                    parts = [float(x) for x in out.strip().split(",")]
                    self.gpu.append(max(parts))
                except Exception:  # noqa: BLE001
                    pass

    def stop(self) -> tuple[float, float]:
        self._done.set()
        self.join(timeout=2)
        return (statistics.mean(self.cpu) if self.cpu else -1,
                statistics.mean(self.gpu) if self.gpu else -1)


def seek_schedule(duration: float, n: int, seed: int = 1234) -> list[float]:
    """Fixed mixed schedule: random jumps, backward steps, and nearby scrubs."""
    rng = random.Random(seed)
    lo, hi = 0.5, max(1.0, duration - 1.0)
    out: list[float] = []
    t = rng.uniform(lo, hi)
    while len(out) < n:
        kind = rng.random()
        if kind < 0.4:                       # long random jump
            t = rng.uniform(lo, hi)
        elif kind < 0.7:                     # nearby scrub, forward
            t = min(hi, t + rng.uniform(0.05, 1.5))
        else:                                # backward step
            t = max(lo, t - rng.uniform(0.05, 3.0))
        out.append(round(t, 3))
    return out


def seek_bench(ffmpeg: str, path: str, positions: list[float]) -> dict:
    """Time `ffmpeg -ss T -i f -frames:v 1` per position: keyframe seek plus
    decode up to T, which is the work an NLE does on every scrub."""
    lat: list[float] = []
    for t in positions:
        t0 = time.perf_counter()
        run([ffmpeg, "-v", "error", "-nostdin", "-threads", "16", "-ss", f"{t}",
             "-i", path, "-map", "0:v:0", "-frames:v", "1", "-f", "null", "-"])
        lat.append((time.perf_counter() - t0) * 1000)
    # Process spawn/probe overhead: seek to 0 and decode one frame.
    spawn: list[float] = []
    for _ in range(5):
        t0 = time.perf_counter()
        run([ffmpeg, "-v", "error", "-nostdin", "-i", path, "-map", "0:v:0",
             "-frames:v", "1", "-f", "null", "-"])
        spawn.append((time.perf_counter() - t0) * 1000)
    lat.sort()
    return {
        "seek_med_ms": round(statistics.median(lat), 1),
        "seek_p95_ms": round(lat[int(len(lat) * 0.95) - 1], 1),
        "seek_max_ms": round(lat[-1], 1),
        "spawn_ms": round(statistics.median(spawn), 1),
    }


def build_cmd(ffmpeg: str, strat: dict, src: str, dst: str, fps: float) -> list[str]:
    gop = strat.get("gop")
    g = max(1, round(fps * gop)) if gop else 0
    cmd = [ffmpeg, "-y", "-nostdin", "-v", "error"]
    if strat.get("hwdec"):
        cmd += ["-hwaccel", "cuda"]
        if strat.get("hwup"):
            cmd += ["-hwaccel_output_format", "cuda"]
    cmd += ["-i", src]
    args = [a.format(gop=g, fps=fps) for a in strat["args"]]
    cmd += args
    if strat.get("pix"):
        cmd += ["-pix_fmt", strat["pix"]]
    if "-c" not in args:            # every transcode keeps the audio as-is
        cmd += ["-c:a", "copy"]
    # Strict per-frame timestamps so VFR-ish sources don't change duration.
    cmd += ["-map", "0:v:0", "-map", "0:a?", dst]
    return cmd


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

FIELDS = ["source", "strategy", "src_codec", "src_pix", "res", "fps", "src_dur_s",
          "out_codec", "out_pix", "container", "gop_frames", "elapsed_s", "realtime_x",
          "enc_fps", "cpu_pct", "gpu_pct", "src_mb", "out_mb", "size_x", "out_mbps",
          "seek_med_ms", "seek_p95_ms", "seek_max_ms", "spawn_ms", "status"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    ap.add_argument("--only", default="")
    ap.add_argument("--sources", default="")
    ap.add_argument("--seeks", type=int, default=100)
    ap.add_argument("--timeout", type=float, default=900)
    ap.add_argument("--all", action="store_true", help="run heavy strategies on 4K too")
    ap.add_argument("--keep", action="store_true", help="keep output files")
    a = ap.parse_args()

    ffmpeg = a.ffmpeg
    ffprobe = os.path.join(os.path.dirname(ffmpeg), "ffprobe" + (".exe" if os.name == "nt" else ""))
    os.makedirs(a.out, exist_ok=True)
    strategies = [s for s in a.only.split(",") if s] or list(STRATEGIES)
    sources = sorted(f for f in os.listdir(a.src) if f.lower().endswith((".mkv", ".mp4", ".webm")))
    if a.sources:
        wanted = a.sources.split(",")
        sources = [s for s in sources if os.path.splitext(s)[0] in wanted]

    csv_path = os.path.join(a.out, "results.csv")
    done = set()
    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                done.add((row["source"], row["strategy"]))
    fh = open(csv_path, "a", newline="", encoding="utf-8")
    w = csv.DictWriter(fh, fieldnames=FIELDS)
    if not done:
        w.writeheader()

    for src_name in sources:
        src = os.path.join(a.src, src_name)
        stem = os.path.splitext(src_name)[0]
        sp = probe(ffprobe, src)
        pixels = sp["width"] * sp["height"]
        for name in strategies:
            if (stem, name) in done:
                continue
            strat = STRATEGIES[name]
            if name in HEAVY and pixels > 2560 * 1440 and not a.all:
                continue
            dst = os.path.join(a.out, f"{stem}__{name}.{strat['ext']}")
            row = {k: "" for k in FIELDS}
            row.update(source=stem, strategy=name, src_codec=sp["vcodec"], src_pix=sp["pix_fmt"],
                       res=f"{sp['width']}x{sp['height']}", fps=round(sp["fps"], 3),
                       src_dur_s=round(sp["duration"], 2), container=strat["ext"],
                       gop_frames=(max(1, round(sp["fps"] * strat["gop"])) if strat.get("gop") else "-"),
                       src_mb=round(sp["size"] / 1e6, 1))
            cmd = build_cmd(ffmpeg, strat, src, dst, sp["fps"])
            print(f"[{stem}] {name} ...", end=" ", flush=True)
            sampler = Sampler()
            sampler.start()
            t0 = time.perf_counter()
            try:
                p = run(cmd, timeout=a.timeout)
                elapsed = time.perf_counter() - t0
                cpu, gpu = sampler.stop()
                if p.returncode != 0 or not os.path.exists(dst):
                    row["status"] = "FAIL: " + (p.stderr or "").strip().splitlines()[-1:][0][:120] if p.stderr else "FAIL"
                    print(row["status"])
                    w.writerow(row); fh.flush()
                    continue
            except subprocess.TimeoutExpired:
                sampler.stop()
                row["status"] = f"TIMEOUT>{a.timeout}s"
                print(row["status"])
                w.writerow(row); fh.flush()
                continue

            op = probe(ffprobe, dst)
            frames = count_frames(ffprobe, dst)
            row.update(out_codec=op["vcodec"], out_pix=op["pix_fmt"],
                       elapsed_s=round(elapsed, 2),
                       realtime_x=round(sp["duration"] / elapsed, 2) if elapsed else "",
                       enc_fps=round(frames / elapsed, 1) if elapsed else "",
                       cpu_pct=round(cpu, 1), gpu_pct=round(gpu, 1),
                       out_mb=round(op["size"] / 1e6, 1),
                       size_x=round(op["size"] / sp["size"], 3) if sp["size"] else "",
                       out_mbps=round(op["bitrate"] / 1e6, 2))
            print(f"{row['realtime_x']}x rt, {row['out_mb']} MB ({row['size_x']}x)", end=" ", flush=True)
            row.update(seek_bench(ffmpeg, dst, seek_schedule(op["duration"], a.seeks)))
            row["status"] = "ok"
            print(f"seek med {row['seek_med_ms']} p95 {row['seek_p95_ms']} ms")
            w.writerow(row); fh.flush()
            if not a.keep:
                try:
                    os.remove(dst)
                except OSError:
                    pass
    fh.close()
    write_md(csv_path, os.path.join(a.out, "results.md"))


def write_md(csv_path: str, md_path: str) -> None:
    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    cols = ["source", "strategy", "out_codec", "container", "gop_frames", "realtime_x", "enc_fps",
            "elapsed_s", "cpu_pct", "gpu_pct", "out_mb", "size_x", "out_mbps",
            "seek_med_ms", "seek_p95_ms", "seek_max_ms", "status"]
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n")
        for r in rows:
            fh.write("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |\n")


if __name__ == "__main__":
    main()
