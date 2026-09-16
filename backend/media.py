"""
media.py — the one place that decides what happens to a download before it
reaches DaVinci Resolve.

Every download goes:

    yt-dlp output  →  probe()  →  plan()  →  build_command()  →  Resolve

and the decision is made from what actually landed on disk, never from what
was requested — after codec and resolution fallbacks those differ.

The rule (measured on real YouTube downloads and scrubbed by hand in Resolve;
see BENCHMARK.md): every download is re-encoded into an editing intermediate
with a keyframe every 0.5 s and no B-frames, using the fastest encoder that
produces something Resolve plays well:

  a. a hardware AV1 encoder (NVENC / Quick Sync / AMF), when one actually
     initialises — its presence in `ffmpeg -encoders` proves nothing;
  b. ffmpeg's native MPEG-4 Part 2, which every ffmpeg has, encodes at
     several times realtime on any CPU, and decodes everywhere.

Why not hand Resolve the download as-is? Repacking YouTube's AV1 stream into
MP4 is instant and lossless, decodes in hardware, and was the plan — until it
was scrubbed. YouTube's keyframes are ~5 s apart, so every seek decodes up to
300 frames at 4K60, and on the timeline that reads as "very slow" next to the
0.5 s-GOP files, which are instant. Seeking is the point of this tool, so the
keyframe interval is the deciding property, and only a re-encode can set it.
(VP9 is out for a second reason too: Resolve won't decode it inside MP4 and
mis-times MKV audio by 12 s.)

Only the two encoders above are ever used. The previous design re-encoded
with a different codec (explicitly for whole videos, and implicitly for every
clip through yt-dlp's --force-keyframes-at-cuts, which re-encodes with the
container's default encoder); FORBIDDEN_ENCODERS and tests/test_encoder_guard.py
keep that from coming back. Reading such a *source* is fine: it is just another
input to the transcode.

Frame-exact sections: a stream-copied section starts at the keyframe before
the in point (video can only be cut there) but ends where it was asked to, so
the in point sits `duration − requested length` into the file — the "lead",
accurate to a frame. (The audio start would also do for AAC, whose every
packet is a cut point, but Opus arrives aligned to WebM clusters, several
seconds early.) The transcode starts decoding at the keyframe and drops frames
up to the lead, so the output begins exactly at the in point. yt-dlp's MP4
output hides the lead behind an edit list already, in which case the lead
reads as zero and the same trim is a no-op.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from fractions import Fraction

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

# Keyframe interval, in seconds. Benchmarked against 0.25 s and 1 s: 0.5 s
# seeks as well as 0.25 s, and 1 s only saved ~10% of the file while roughly
# doubling worst-case seek latency.
GOP_SECONDS = 0.5

# Hardware AV1 encoders, in the order they are tried. All of them exist in
# stock ffmpeg builds; whether one works here is what probe_capabilities finds
# out. Nothing is required: the CPU path is the universal fallback.
HW_AV1_ENCODERS: dict[str, tuple[str, ...]] = {
    "win32": ("av1_nvenc", "av1_qsv", "av1_amf"),
    "linux": ("av1_nvenc", "av1_qsv", "av1_vaapi"),
    "darwin": (),                    # VideoToolbox has no AV1 encoder
}

# Audio that goes straight into the MP4 unchanged. Anything else (Opus,
# Vorbis) is converted to AAC: Resolve 21 does decode Opus in MP4, but earlier
# builds imported it silently, and a 200x-realtime audio pass is cheap
# insurance. The download preference asks for AAC so this rarely triggers.
COPYABLE_AUDIO = ("aac", "mp3", "pcm_s16le", "pcm_s24le", "alac", "flac")

# Rate-control targets. Checked against the already-lossy YouTube source with
# VMAF and by eye (BENCHMARK.md); the aim is "no visible extra damage", not
# small files.
NVENC_CQ = "28"
MPEG4_QSCALE = "3"

# Encoders this project removed and must never select again, however they are
# spelled. Kept as data in exactly one place so the guard can check for them;
# tests/test_encoder_guard.py scans the repository for the same names.
FORBIDDEN_ENCODERS = ("libx264", "libx264rgb", "libopenh264", "x264")
FORBIDDEN_ENCODER_PREFIXES = ("h264_",)

# Frame rates an NLE expects. A measured rate within 1% of one of these is
# snapped to it when conforming (a 59.74 fps YouTube upload becomes 59.94 with
# one duplicated frame every few hundred); anything further off is kept as
# measured, since it is presumably deliberate.
STANDARD_RATES = (Fraction(24000, 1001), Fraction(24), Fraction(25), Fraction(30000, 1001),
                  Fraction(30), Fraction(48), Fraction(50), Fraction(60000, 1001), Fraction(60),
                  Fraction(120))


# --------------------------------------------------------------------------- #
# Probe
# --------------------------------------------------------------------------- #

@dataclass
class SourceInfo:
    path: str
    container: str = ""                # ffprobe format_name, e.g. "matroska,webm"
    vcodec: str = ""
    acodec: str | None = None          # None when there is no audio stream
    width: int = 0
    height: int = 0
    pix_fmt: str = ""
    fps: Fraction = Fraction(0)        # r_frame_rate; 0 when unknown
    duration: float = 0.0              # container duration, seconds
    video_duration: float | None = None  # video track's own duration, if the container has one
    video_start: float = 0.0           # first video packet pts, seconds
    audio_start: float | None = None   # first audio packet pts, seconds
    rotation: int = 0
    color: dict = field(default_factory=dict)   # primaries / transfer / space / range

    @property
    def bit_depth(self) -> int:
        """8 unless the pixel format says otherwise (yuv420p10le → 10)."""
        digits = "".join(ch for ch in self.pix_fmt.split("p", 1)[-1] if ch.isdigit())
        return int(digits) if digits else 8

    @property
    def is_hdr(self) -> bool:
        return self.color.get("transfer") in ("smpte2084", "arib-std-b67")

    def lead_seconds(self, requested_length: float | None) -> float:
        """How far into the file the requested in point sits (see module doc).

        From the duration when the requested length is known; otherwise from
        the audio start, which is exact for AAC and merely early for Opus.
        Anything implausible (more than 30 s — YouTube keyframes are seconds
        apart) is treated as zero rather than trusted.
        """
        # The video track's duration when the container has one: in MP4 it is
        # the edited duration, so a lead that yt-dlp already hid behind an
        # edit list (its MP4 output does this) correctly reads as zero, and
        # an audio track that runs a packet longer than the video doesn't add
        # a phantom frame. Matroska has no per-track duration; the container's
        # is used, accurate to a frame.
        base = self.video_duration if self.video_duration else self.duration
        if requested_length is not None and requested_length > 0 and base > 0:
            lead = base - requested_length
        elif self.audio_start is not None:
            lead = self.audio_start - self.video_start
        else:
            lead = 0.0
        return lead if 0.0 <= lead <= 30.0 else 0.0

    def describe(self) -> str:
        """'2160p (3840x2160, av1, 60 fps)' — what is actually on disk."""
        label = f"{self.height}p ({self.width}x{self.height}, {self.vcodec or '?'}"
        if self.fps:
            label += f", {float(self.fps):.2f}".rstrip("0").rstrip(".") + " fps"
        if self.bit_depth > 8:
            label += f", {self.bit_depth}-bit"
        if self.is_hdr:
            label += ", HDR"
        return label + ")"


def _run(cmd: list[str], timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _parse_probe(data: dict, path: str) -> SourceInfo:
    """Turn ffprobe's JSON into a SourceInfo. Split out so it can be tested
    without ffprobe."""
    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)

    fps = Fraction(0)
    rate = str(v.get("r_frame_rate") or "0/1")
    try:
        num, den = rate.split("/", 1)
        if int(den):
            fps = Fraction(int(num), int(den))
    except ValueError:
        pass

    rotation = 0
    for sd in v.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                rotation = int(sd["rotation"]) % 360
            except (TypeError, ValueError):
                pass

    def _start(s: dict | None) -> float | None:
        if not s:
            return None
        try:
            return float(s.get("start_time"))
        except (TypeError, ValueError):
            return 0.0

    try:
        video_duration: float | None = float(v.get("duration"))
    except (TypeError, ValueError):
        video_duration = None

    return SourceInfo(
        path=path,
        video_duration=video_duration,
        container=str(fmt.get("format_name") or ""),
        vcodec=str(v.get("codec_name") or ""),
        acodec=str(a.get("codec_name")) if a else None,
        width=int(v.get("width") or 0),
        height=int(v.get("height") or 0),
        pix_fmt=str(v.get("pix_fmt") or ""),
        fps=fps,
        duration=float(fmt.get("duration") or 0.0),
        video_start=_start(v) or 0.0,
        audio_start=_start(a),
        rotation=rotation,
        color={k: v.get(f"color_{k}") for k in ("primaries", "transfer", "space", "range")
               if v.get(f"color_{k}")},
    )


def _first_packets(ffprobe: str, path: str, stream: str, seconds: float) -> list[float]:
    """pts (seconds) of `stream`'s packets within the first `seconds` of the
    file, sorted. Empty if the stream has none there or ffprobe fails."""
    cmd = [ffprobe, "-v", "error", "-select_streams", stream,
           "-read_intervals", f"%+{seconds}", "-show_entries", "packet=pts_time",
           "-of", "csv=p=0", path]
    try:
        proc = _run(cmd, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []
    pts: list[float] = []
    for line in (proc.stdout or "").splitlines():
        try:
            pts.append(float(line.strip().rstrip(",")))
        except ValueError:
            continue
    return sorted(pts)


def nle_rate(fps: Fraction) -> Fraction:
    """`fps` snapped to the nearest STANDARD_RATES entry when within 1% of it,
    else itself. Exact matches stay exact (60 is 60, not 59.94)."""
    if not fps:
        return Fraction(30)
    if fps in STANDARD_RATES:
        return fps
    nearest = min(STANDARD_RATES, key=lambda std: abs(float(fps) - float(std)))
    if abs(float(fps) - float(nearest)) / float(nearest) <= 0.01:
        return nearest
    return fps


def probe(ffprobe: str, path: str) -> SourceInfo | None:
    """What is on disk, or None if ffprobe can't read the file at all."""
    cmd = [ffprobe, "-v", "error", "-show_entries",
           "format=format_name,duration:"
           "stream=codec_name,codec_type,width,height,pix_fmt,r_frame_rate,"
           "start_time,duration,color_primaries,color_transfer,color_space,color_range:"
           "stream_side_data=rotation",
           "-of", "json", path]
    try:
        proc = _run(cmd, timeout=60)
        if proc.returncode != 0:
            return None
        data = json.loads(proc.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    info = _parse_probe(data, path)
    if not info.vcodec:
        return None
    # Stream start times are read from the packets themselves: Matroska's
    # per-stream start_time is unreliable (it reports 0 for an audio track
    # that begins six seconds in). 30 s covers any keyframe lead YouTube
    # produces.
    video = _first_packets(ffprobe, path, "v:0", 30.0)
    if video:
        info.video_start = video[0]
    if info.acodec is not None:
        audio = _first_packets(ffprobe, path, "a:0", 30.0)
        info.audio_start = audio[0] if audio else info.video_start
    return info


# --------------------------------------------------------------------------- #
# Hardware capabilities
# --------------------------------------------------------------------------- #

@dataclass
class Capabilities:
    """What this machine can do, found by trying rather than by asking."""
    av1_encoder: str | None = None     # a hardware AV1 encoder that initialised

    def describe(self) -> str:
        if self.av1_encoder:
            return f"hardware AV1 encoder: {self.av1_encoder}"
        return "no hardware AV1 encoder — converting on the CPU (MPEG-4)"


def _try_encoder(ffmpeg: str, encoder: str, timeout: float = 30) -> bool:
    """Encode eight synthetic frames. Only a clean exit counts — a listed
    encoder fails here whenever the GPU, driver or API is absent."""
    cmd = [ffmpeg, "-v", "error", "-nostdin", "-f", "lavfi",
           "-i", "color=c=gray:s=640x360:r=30", "-frames:v", "8",
           "-c:v", encoder, "-f", "null", "-"]
    try:
        return _run(cmd, timeout=timeout).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def probe_capabilities(ffmpeg: str, platform: str = sys.platform) -> Capabilities:
    """Find a working hardware AV1 encoder. A second or so the first time;
    callers cache the result."""
    caps = Capabilities()
    for enc in HW_AV1_ENCODERS.get(platform, ()):
        if _try_encoder(ffmpeg, enc):
            caps.av1_encoder = enc
            break
    return caps


# --------------------------------------------------------------------------- #
# Plan
# --------------------------------------------------------------------------- #

@dataclass
class Section:
    """The part of the source the user asked for, in seconds of source time.
    None end means "to the end of the file"."""
    start: float = 0.0
    end: float | None = None


@dataclass
class Plan:
    encoder: str                       # "av1_nvenc" | "av1_qsv" | "av1_amf" | "av1_vaapi" | "mpeg4"
    container: str = "mp4"
    gop: int = 0                       # frames
    rate: Fraction = Fraction(30)      # output frame rate
    video_args: list[str] = field(default_factory=list)
    audio_args: list[str] = field(default_factory=list)
    input_args: list[str] = field(default_factory=list)
    trim: tuple[float, float | None] | None = None   # (start, end) in file seconds
    notes: list[str] = field(default_factory=list)

    @property
    def hardware(self) -> bool:
        return self.encoder != "mpeg4"


def gop_frames(fps: Fraction | float, seconds: float = GOP_SECONDS) -> int:
    """Keyframe interval in frames for `fps`: 30 fps → 15, 60 → 30, 24 → 12,
    29.97 → 15. Never below 1."""
    return max(1, round(float(fps) * seconds))


def plan(src: SourceInfo, caps: Capabilities, section: Section | None = None) -> Plan:
    """Decide how to convert `src`. Pure: no I/O, so every branch is testable.

    `section` is the range the user asked for; None (or a zero-start, open-ended
    one) means the whole video, and then no lead is applied even if the audio
    track starts a few milliseconds late, as AAC priming can make it.
    """
    fps = src.fps or Fraction(30)
    section = section or Section()
    sectioned = section.end is not None or section.start > 0
    length = (section.end - section.start) if section.end is not None else None
    lead = src.lead_seconds(length) if sectioned else 0.0
    ten_bit = src.bit_depth > 8

    notes: list[str] = []
    if src.acodec is None or src.acodec in COPYABLE_AUDIO:
        audio_args = ["-c:a", "copy"]
    else:
        audio_args = ["-c:a", "aac", "-b:a", "192k"]
        notes.append(f"audio is {src.acodec}; converting to AAC for compatibility")

    gop = gop_frames(fps)
    p = Plan(encoder=caps.av1_encoder or "mpeg4", gop=gop, audio_args=audio_args, notes=notes)

    if caps.av1_encoder:
        p.video_args = ["-c:v", caps.av1_encoder, "-g", str(gop), "-bf", "0"]
        if caps.av1_encoder == "av1_nvenc":
            p.video_args += ["-preset", "p1", "-tune", "ll", "-rc", "vbr",
                             "-cq", NVENC_CQ, "-b:v", "0"]
            # Decode on the GPU and keep the frames there: 8-bit sources
            # arrive as nv12, 10-bit as p010, and NVENC takes both.
            p.input_args = ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
        elif caps.av1_encoder == "av1_qsv":
            p.video_args += ["-preset", "veryfast", "-global_quality", NVENC_CQ,
                             "-pix_fmt", "p010le" if ten_bit else "nv12"]
        elif caps.av1_encoder == "av1_amf":
            p.video_args += ["-quality", "speed", "-rc", "cqp", "-qp_i", NVENC_CQ,
                             "-qp_p", NVENC_CQ, "-pix_fmt", "p010le" if ten_bit else "nv12"]
        else:                                     # av1_vaapi
            p.video_args += ["-qp", NVENC_CQ]
        if ten_bit:
            notes.append("10-bit source kept at 10-bit")
    else:
        p.video_args = ["-c:v", "mpeg4", "-q:v", MPEG4_QSCALE, "-g", str(gop),
                        "-bf", "0", "-pix_fmt", "yuv420p"]
        if ten_bit or src.is_hdr:
            notes.append("MPEG-4 Part 2 is 8-bit only: HDR/10-bit source converted to "
                         "8-bit. A hardware AV1 encoder would keep it.")

    # Exact trim at the in point: decoding from the keyframe and dropping
    # frames before the target is what re-encoding buys us.
    if sectioned:
        p.trim = (lead, lead + length if length is not None else None)

    p.rate = nle_rate(fps)
    if abs(float(p.rate) - float(fps)) / float(fps) > 0.0005:
        notes.append(f"frame rate {float(fps):.3f} conformed to {float(p.rate):.6g} fps")
    return p


def build_command(ffmpeg: str, src: SourceInfo, p: Plan, output: str) -> list[str]:
    """The ffmpeg invocation for `p`. Progress is written to stdout as
    key=value lines (-progress pipe:1) for the caller's progress bar."""
    cmd = [ffmpeg, "-y", "-nostdin", "-loglevel", "error", "-nostats"]
    cmd += p.input_args
    if p.trim:
        # -ss before -i seeks to the previous keyframe and, with re-encoding,
        # drops frames up to the target: frame-accurate and fast. -t counts
        # from the target, not the keyframe.
        cmd += ["-ss", f"{p.trim[0]:.6f}"]
        if p.trim[1] is not None:
            cmd += ["-t", f"{max(0.0, p.trim[1] - p.trim[0]):.6f}"]
    cmd += ["-i", src.path, "-map", "0:v:0", "-map", "0:a?"]
    cmd += p.video_args + p.audio_args
    # A constant frame grid at the conformed rate: variable-rate sources get
    # frames duplicated or dropped so audio stays in sync.
    cmd += ["-fps_mode", "cfr", "-r", f"{p.rate.numerator}/{p.rate.denominator}"]
    cmd += ["-map_metadata", "0", "-movflags", "+faststart", "-progress", "pipe:1", output]
    return cmd


def output_path_for(src_path: str, p: Plan) -> str:
    """Where the finished file goes: same stem, container from the plan."""
    stem, _ = os.path.splitext(src_path)
    return f"{stem}.{p.container}"


def estimate_seconds(src: SourceInfo, p: Plan, section: Section | None = None) -> float:
    """Rough wall-clock guess for the progress log, from measured rates."""
    length = src.duration
    if section and section.end is not None:
        length = section.end - section.start
    pixels = src.width * src.height or 1920 * 1080
    fps = float(src.fps or 30)
    # Pixels per second each path gets through, from BENCHMARK.md (RTX 5070 Ti:
    # NVENC 5-8x realtime at 4K60; 16-thread CPU: mpeg4 4.5-6x at 4K60, 2.6x
    # for 10-bit HDR) — rounded down so the estimate errs long.
    rate = 2.4e9 if p.hardware else (1.2e9 if src.bit_depth > 8 else 2.0e9)
    return max(1.0, length * pixels * fps / rate)


def is_forbidden_encoder(name: str) -> bool:
    """Regression guard: True for any encoder this project removed."""
    n = name.lower()
    return n in FORBIDDEN_ENCODERS or n.startswith(FORBIDDEN_ENCODER_PREFIXES)


def assert_allowed_encoder(p: Plan) -> None:
    """Raise if a plan would use a removed encoder. Called by tests and,
    cheaply, before every encode."""
    if p.encoder and is_forbidden_encoder(p.encoder):
        raise ValueError(f"plan selects a removed encoder: {p.encoder}")
    for arg in p.video_args:
        if is_forbidden_encoder(arg):
            raise ValueError(f"plan arguments reference a removed encoder: {arg}")
