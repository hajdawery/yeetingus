#!/usr/bin/env python3
"""
resolve_check.py — measure how DaVinci Resolve itself handles candidate files.

ffmpeg can decode almost anything; that says nothing about how a clip behaves
on a Resolve timeline. This drives the real application through its scripting
API and records, per file:

  import      whether Resolve accepts it and what it reads back (codec, fps,
              frame count, audio codec, bit depth)
  seek        wall time for SetCurrentTimecode + GrabStill over a mixed
              schedule of jumps and nearby scrubs — a still cannot be grabbed
              without decoding the frame under the playhead, so this is
              Resolve's own seek-and-decode latency (median / p95 / worst)
  render      fps of a full timeline render to DNxHR LB, which for these
              sources is decode-bound and so measures Resolve's decoder

Usage (Resolve running, a scratch project open, Python 3.13 on this machine):

    py -3.13 tools/resolve_check.py FILE [FILE ...] [--seeks 40] [--render]

Stills are grabbed into the gallery and deleted again; a timeline is created
per file in the current project and deleted afterwards. Nothing else in the
project is touched.
"""

from __future__ import annotations

import argparse
import os
import random
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
import resolve_bridge as rb  # noqa: E402

PROPS = ("Video Codec", "Audio Codec", "Resolution", "FPS", "Frames", "Duration",
         "Bit Depth", "Data Level", "Format", "Audio Ch")


def tc(frame: int, fps: float) -> str:
    f = int(round(fps))
    ss, ff = divmod(frame, f)
    mm, ss = divmod(ss, 60)
    hh, mm = divmod(mm, 60)
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def seek_schedule(frames: int, n: int, seed: int = 99) -> list[int]:
    rng = random.Random(seed)
    lo, hi = 5, max(6, frames - 5)
    out, t = [], rng.randint(lo, hi)
    while len(out) < n:
        k = rng.random()
        if k < 0.4:
            t = rng.randint(lo, hi)
        elif k < 0.7:
            t = min(hi, t + rng.randint(1, 45))
        else:
            t = max(lo, t - rng.randint(1, 90))
        out.append(t)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--seeks", type=int, default=40)
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--render-dir", default=os.path.join(os.environ.get("TEMP", "."), "yeet_resolve_check"))
    a = ap.parse_args()

    app = rb.connect()
    project = app.GetProjectManager().GetCurrentProject()
    pool = project.GetMediaPool()
    storage = app.GetMediaStorage()
    gallery = project.GetGallery()
    print(f"Resolve {app.GetVersionString()}, project '{project.GetName()}'")
    print()

    for path in a.files:
        path = os.path.abspath(path)
        name = os.path.basename(path)
        print(f"=== {name}")
        t0 = time.perf_counter()
        items = storage.AddItemListToMediaPool([path])
        if not items:
            print("  IMPORT FAILED — Resolve refused the file")
            continue
        item = items[0]
        print(f"  import {1000 * (time.perf_counter() - t0):.0f} ms")
        props = {k: item.GetClipProperty(k) for k in PROPS}
        print("  " + ", ".join(f"{k}={v}" for k, v in props.items() if v not in ("", None)))
        try:
            frames = int(float(props.get("Frames") or 0))
            fps = float(props.get("FPS") or 0)
        except ValueError:
            frames, fps = 0, 0.0
        if not frames or not fps:
            print("  no frames/fps reported — skipping seek/render")
            pool.DeleteClips([item])
            continue

        # An empty timeline first: fps/resolution can only be changed while it
        # holds no clips, and the project default (24p 1080) would otherwise
        # make Resolve skip frames and scale, hiding the decoder cost.
        w_px, h_px = (str(props.get("Resolution") or "1920x1080").split("x") + ["1080"])[:2]
        # The project default is what a new timeline inherits; the per-timeline
        # setter is ignored on some versions, so set both.
        project.SetSetting("timelineFrameRate", str(int(fps)) if fps == int(fps) else str(fps))
        project.SetSetting("timelineResolutionWidth", w_px)
        project.SetSetting("timelineResolutionHeight", h_px)
        tl = pool.CreateEmptyTimeline(f"bench {name}")
        if not tl:
            print("  could not create a timeline")
            pool.DeleteClips([item])
            continue
        project.SetCurrentTimeline(tl)
        tl.SetSetting("useCustomSettings", "1")
        tl.SetSetting("timelineFrameRate", str(fps))
        tl.SetSetting("timelineResolutionWidth", w_px)
        tl.SetSetting("timelineResolutionHeight", h_px)
        if not pool.AppendToTimeline([{"mediaPoolItem": item}]):
            print("  could not place it on the timeline")
            pool.DeleteTimelines([tl]); pool.DeleteClips([item])
            continue
        print(f"  timeline fps {tl.GetSetting('timelineFrameRate')}, "
              f"{tl.GetSetting('timelineResolutionWidth')}x{tl.GetSetting('timelineResolutionHeight')}")
        tl_fps = float(tl.GetSetting("timelineFrameRate") or fps)
        start = tl.GetStartFrame()
        album = gallery.GetCurrentStillAlbum()

        # Warm-up seek so the first-open cost isn't charged to the schedule.
        tl.SetCurrentTimecode(tc(start + 1, tl_fps))
        s = tl.GrabStill()
        if s:
            album.DeleteStills([s])

        lat: list[float] = []
        failed = 0
        for f in seek_schedule(frames, a.seeks):
            t1 = time.perf_counter()
            tl.SetCurrentTimecode(tc(start + f, tl_fps))
            still = tl.GrabStill()
            lat.append((time.perf_counter() - t1) * 1000)
            if still:
                album.DeleteStills([still])
            else:
                failed += 1
        lat.sort()
        print(f"  seek+decode ({a.seeks}): median {statistics.median(lat):.0f} ms, "
              f"p95 {lat[int(len(lat) * 0.95) - 1]:.0f} ms, worst {lat[-1]:.0f} ms"
              + (f", {failed} grabs FAILED" if failed else ""))

        if a.render:
            os.makedirs(a.render_dir, exist_ok=True)
            project.SetRenderSettings({
                "SelectAllFrames": True,
                "ExportVideo": True, "ExportAudio": True,
                "TargetDir": a.render_dir,
                "CustomName": f"bench_{name.replace('.', '_')}",
                "FormatWidth": int(str(props.get("Resolution", "1920x1080")).split("x")[0]),
                "FormatHeight": int(str(props.get("Resolution", "1920x1080")).split("x")[1]),
            })
            if not project.SetCurrentRenderFormatAndCodec("mov", "DNxHRLB"):
                print("  WARNING: could not select DNxHR LB, rendering with the current codec")
            job = project.AddRenderJob()
            t2 = time.perf_counter()
            project.StartRendering(job)
            while project.IsRenderingInProgress():
                time.sleep(0.25)
            el = time.perf_counter() - t2
            status = project.GetRenderJobStatus(job)
            print(f"  render DNxHR LB: {el:.1f} s -> {frames / el:.0f} fps "
                  f"({frames / el / fps:.2f}x realtime) [{status.get('JobStatus')}"
                  f"{', ' + str(status.get('Error')) if status.get('Error') else ''}]")
            project.DeleteRenderJob(job)
            out = os.path.join(a.render_dir, f"bench_{name.replace('.', '_')}.mov")
            if os.path.exists(out):
                print(f"  rendered file: {out}")

        pool.DeleteTimelines([tl])
        pool.DeleteClips([item])
        print()


if __name__ == "__main__":
    main()
