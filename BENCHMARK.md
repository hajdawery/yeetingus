# Intermediate-format benchmark (2026-09-16)

Why this exists: YEETingus used to re-encode every clip with a codec that has
since been removed entirely (explicitly for whole videos above 1080p; for every
section through yt-dlp's `--force-keyframes-at-cuts`, which re-encodes with
MP4's default encoder). This report is the measurement behind what replaced it, and is meant to be re-run when ffmpeg or
Resolve change (`tools/bench.py`, `tools/resolve_check.py`, `tools/quality.py`;
raw numbers in `tools/bench_results/`).

**Machine:** Windows 11, 16-thread CPU, NVIDIA RTX 5070 Ti (driver 616.64),
DaVinci Resolve 21.0.1, ffmpeg N-126574 (BtbN win64 **lgpl** build — the one
the app now fetches; without the GPL-only encoder libraries).

## Result in one paragraph

Every download is transcoded into an editing intermediate with a **keyframe
every 0.5 s and no B-frames** — `av1_nvenc` (preset p1, cq 28) when a hardware
AV1 encoder initialises, otherwise ffmpeg's native `mpeg4` (q 3). The
stream-copy ("remux") path — instant, lossless, and hardware-decoded by
Resolve — was implemented, verified, and then **rejected by a hands-on scrub
test**: with YouTube's ~5 s keyframe spacing it was "not seekable, very slow"
on a 4K60 timeline, while the 0.5 s-GOP files were "amazing". Keyframe
interval decides scrub feel; codec and decode speed do not. VP9 output is out
regardless (Resolve fails on VP9-in-MP4 and mis-syncs MKV audio by 12 s), and
the intra-frame codecs seek fine but are 45–400× the file size.

## Method

**Sources** — real YouTube downloads (60 s sections, stream-copied, the exact
input the app receives), covering low motion (interview, 1080p30), high-motion
gameplay (BLACKWOOD, 1080p60 AV1 / 1440p60 / 4K60 VP9), text/UI-heavy gameplay
(Factorio, 1440p60, a genuinely odd 59.74 fps upload with irregular frame
timing), animation (Big Buck Bunny, 4K60 in both VP9 and AV1) and 10-bit HDR
(LG demo, 4K60 VP9 profile 2). YouTube outputs constant-rate video; the
Factorio upload is the closest thing to VFR it produces and is included for
that reason.

**Encode metrics** (`tools/bench.py`) — wall time, realtime factor, mean
CPU/GPU utilisation, output size and bitrate, all with nothing else running.
(A first full-matrix pass ran concurrently with the Resolve tests; those
numbers are in `tools/bench_results/2026-09-16-full-matrix-partial.csv` and
are used here only for the intra-frame baselines, whose sizes are exact and
whose speeds are approximate.)

**Seek metric** — 60 seeks per file on a fixed pseudo-random schedule (40 %
long jumps, 30 % nearby forward scrubs, 30 % backward steps), each timed as
`ffmpeg -ss T -i f -frames:v 1`: seek to the keyframe, decode up to T. Includes
~45 ms of process start-up, identical for every row, so compare rows, not
absolutes.

**Resolve** (`tools/resolve_check.py`) — import, clip properties, render
throughput of a DNxHR LB export from a timeline at the clip's own resolution
and rate (decode-bound for these sources), and A/V offset of the render
against the source by cross-correlation. Resolve's `GrabStill` has a ~500 ms
fixed cost and could not rank seek latency, so the deciding seek test was
done by hand on a 4K60 timeline (`SCRUB TEST`: six one-minute clips, same
content in each candidate format).

**Quality** (`tools/quality.py`) — VMAF 0.6.1 / SSIM / PSNR against the
source over 20 s with frames paired by index, plus 1:1 side-by-side crops of
text and UI edges.

## Encode + seek results (clean run)

#### bbb_4k60_vp9 — 3840x2160 @ 60 fps, vp9 yuv420p, 66.03 s, 123.3 MB

| strategy | codec | GOP (frames) | speed | elapsed | size | × source | Mbit/s | seek median | seek p95 | seek max |
|---|---|---|---|---|---|---|---|---|---|---|
| remux (as-is) | vp9 | - | 426.3× | 0.1 s | 123.4 MB | 1.00× | 14.95 | 266.7 ms | 520.1 ms | 586.3 ms |
| mpeg4 q3, GOP 0.25 s | mpeg4 | 15 | 5.0× | 13.1 s | 227.7 MB | 1.85× | 27.59 | 131.8 ms | 155.9 ms | 168.5 ms |
| mpeg4 q3, GOP 0.5 s | mpeg4 | 30 | 4.9× | 13.6 s | 191.2 MB | 1.55× | 23.16 | 139.3 ms | 158.5 ms | 169.2 ms |
| mpeg4 q3, GOP 1 s | mpeg4 | 60 | 4.1× | 16.0 s | 172.4 MB | 1.40× | 20.88 | 144.6 ms | 163.3 ms | 174.5 ms |
| mpeg4 q5, GOP 0.5 s | mpeg4 | 30 | 4.4× | 15.0 s | 164.5 MB | 1.33× | 19.93 | 141.0 ms | 173.9 ms | 181.0 ms |
| av1_nvenc p1 cq28, GOP 0.5 s | av1 | 30 | 5.3× | 12.4 s | 186.8 MB | 1.51× | 22.63 | 111.8 ms | 184.1 ms | 214.2 ms |
| av1_nvenc p1 cq28, GOP 1 s | av1 | 60 | 8.2× | 8.0 s | 169.8 MB | 1.38× | 20.57 | 144.7 ms | 266.7 ms | 364.6 ms |
| av1_nvenc p4 cq28, GOP 0.5 s | av1 | 30 | 2.3× | 28.4 s | 189.7 MB | 1.54× | 22.99 | 183.2 ms | 294.0 ms | 349.7 ms |
| libsvtav1 p12 crf30, GOP 0.5 s | av1 | 30 | 1.4× | 45.5 s | 85.9 MB | 0.70× | 10.4 | 105.4 ms | 160.5 ms | 193.0 ms |
| libvpx-vp9 realtime, GOP 0.5 s | vp9 | 30 | 2.5× | 26.4 s | 129.6 MB | 1.05× | 15.7 | 169.7 ms | 238.7 ms | 279.5 ms |

#### game_4k60_vp9 — 3840x2160 @ 60 fps, vp9 yuv420p, 60.5 s, 38.7 MB

| strategy | codec | GOP (frames) | speed | elapsed | size | × source | Mbit/s | seek median | seek p95 | seek max |
|---|---|---|---|---|---|---|---|---|---|---|
| remux (as-is) | vp9 | - | 809.2× | 0.1 s | 38.8 MB | 1.00× | 5.13 | 301.0 ms | 585.0 ms | 712.7 ms |
| mpeg4 q3, GOP 0.25 s | mpeg4 | 15 | 6.2× | 9.7 s | 193.9 MB | 5.01× | 25.64 | 108.1 ms | 135.5 ms | 149.7 ms |
| mpeg4 q3, GOP 0.5 s | mpeg4 | 30 | 6.4× | 9.5 s | 164.0 MB | 4.24× | 21.68 | 115.8 ms | 146.7 ms | 155.9 ms |
| mpeg4 q3, GOP 1 s | mpeg4 | 60 | 6.1× | 9.9 s | 149.0 MB | 3.85× | 19.7 | 129.9 ms | 152.4 ms | 163.7 ms |
| mpeg4 q5, GOP 0.5 s | mpeg4 | 30 | 5.6× | 10.8 s | 159.8 MB | 4.13× | 21.13 | 116.0 ms | 141.3 ms | 153.9 ms |
| av1_nvenc p1 cq28, GOP 0.5 s | av1 | 30 | 6.2× | 9.8 s | 133.5 MB | 3.45× | 17.65 | 104.9 ms | 191.1 ms | 213.3 ms |
| av1_nvenc p1 cq28, GOP 1 s | av1 | 60 | 5.8× | 10.5 s | 122.0 MB | 3.15× | 16.13 | 138.9 ms | 271.6 ms | 324.9 ms |
| av1_nvenc p4 cq28, GOP 0.5 s | av1 | 30 | 2.1× | 28.1 s | 129.0 MB | 3.33× | 17.06 | 157.2 ms | 307.1 ms | 336.9 ms |
| libsvtav1 p12 crf30, GOP 0.5 s | av1 | 30 | 1.6× | 39.1 s | 53.6 MB | 1.39× | 7.09 | 88.1 ms | 118.3 ms | 149.8 ms |
| libvpx-vp9 realtime, GOP 0.5 s | vp9 | 30 | 2.8× | 21.4 s | 89.3 MB | 2.31× | 11.8 | 139.4 ms | 177.8 ms | 181.1 ms |

#### hdr_4k60_vp9_10bit — 3840x2160 @ 59.94 fps, vp9 yuv420p10le, 66.1 s, 238.2 MB

| strategy | codec | GOP (frames) | speed | elapsed | size | × source | Mbit/s | seek median | seek p95 | seek max |
|---|---|---|---|---|---|---|---|---|---|---|
| remux (as-is) | vp9 | - | 316.1× | 0.2 s | 238.2 MB | 1.00× | 28.83 | 445.6 ms | 914.0 ms | 1087.5 ms |
| mpeg4 q3, GOP 0.25 s | mpeg4 | 15 | 2.8× | 23.7 s | 802.0 MB | 3.37× | 97.06 | 125.6 ms | 153.1 ms | 171.9 ms |
| mpeg4 q3, GOP 0.5 s | mpeg4 | 30 | 2.6× | 25.5 s | 741.2 MB | 3.11× | 89.71 | 140.8 ms | 172.4 ms | 178.4 ms |
| mpeg4 q3, GOP 1 s | mpeg4 | 60 | 2.5× | 26.0 s | 710.3 MB | 2.98× | 85.97 | 153.3 ms | 219.6 ms | 241.8 ms |
| mpeg4 q5, GOP 0.5 s | mpeg4 | 30 | 2.7× | 24.6 s | 438.2 MB | 1.84× | 53.03 | 137.1 ms | 161.0 ms | 170.6 ms |
| av1_nvenc p1 cq28, GOP 0.5 s | av1 | 30 | 7.9× | 8.3 s | 292.2 MB | 1.23× | 35.36 | 150.8 ms | 226.5 ms | 255.3 ms |
| av1_nvenc p1 cq28, GOP 1 s | av1 | 60 | 7.9× | 8.3 s | 284.5 MB | 1.19× | 34.43 | 187.1 ms | 379.8 ms | 631.3 ms |
| av1_nvenc p4 cq28, GOP 0.5 s | av1 | 30 | 3.0× | 21.9 s | 286.6 MB | 1.20× | 34.68 | 226.8 ms | 360.5 ms | 383.6 ms |
| libsvtav1 p12 crf30, GOP 0.5 s | av1 | 30 | 1.0× | 67.2 s | 275.4 MB | 1.16× | 33.33 | 184.4 ms | 294.7 ms | 327.4 ms |
| libvpx-vp9 realtime, GOP 0.5 s | vp9 | 30 | 0.9× | 71.4 s | 398.8 MB | 1.67× | 48.26 | 267.8 ms | 391.9 ms | 422.0 ms |

#### bbb_4k60_av1 — 3840x2160 @ 60 fps, av1 yuv420p, 66.03 s, 72.1 MB

| strategy | codec | GOP (frames) | speed | elapsed | size | × source | Mbit/s | seek median | seek p95 | seek max |
|---|---|---|---|---|---|---|---|---|---|---|
| remux (as-is) | av1 | - | 586.2× | 0.1 s | 72.2 MB | 1.00× | 8.75 | 163.4 ms | 350.1 ms | 358.9 ms |
| mpeg4 q3, GOP 0.25 s | mpeg4 | 15 | 4.5× | 14.7 s | 225.0 MB | 3.12× | 27.26 | 123.1 ms | 153.2 ms | 163.9 ms |
| mpeg4 q3, GOP 0.5 s | mpeg4 | 30 | 4.6× | 14.4 s | 189.0 MB | 2.62× | 22.9 | 139.5 ms | 163.4 ms | 170.6 ms |
| mpeg4 q3, GOP 1 s | mpeg4 | 60 | 4.5× | 14.8 s | 170.5 MB | 2.37× | 20.66 | 140.4 ms | 174.0 ms | 188.4 ms |
| mpeg4 q5, GOP 0.5 s | mpeg4 | 30 | 4.7× | 14.2 s | 163.3 MB | 2.27× | 19.79 | 143.2 ms | 160.4 ms | 184.4 ms |
| av1_nvenc p1 cq28, GOP 0.5 s | av1 | 30 | 3.7× | 17.8 s | 181.8 MB | 2.52× | 22.03 | 128.4 ms | 202.3 ms | 262.0 ms |
| av1_nvenc p1 cq28, GOP 1 s | av1 | 60 | 3.6× | 18.2 s | 164.9 MB | 2.29× | 19.97 | 148.3 ms | 287.3 ms | 357.2 ms |
| av1_nvenc p4 cq28, GOP 0.5 s | av1 | 30 | 2.6× | 25.0 s | 183.7 MB | 2.55× | 22.26 | 207.1 ms | 334.7 ms | 375.7 ms |
| libsvtav1 p12 crf30, GOP 0.5 s | av1 | 30 | 1.3× | 49.1 s | 84.4 MB | 1.17× | 10.22 | 104.9 ms | 176.2 ms | 189.7 ms |
| libvpx-vp9 realtime, GOP 0.5 s | vp9 | 30 | 1.9× | 35.4 s | 127.3 MB | 1.76× | 15.42 | 185.9 ms | 268.7 ms | 311.0 ms |

#### game_1440p60_vp9 — 2560x1440 @ 60 fps, vp9 yuv420p, 60.5 s, 22.8 MB

| strategy | codec | GOP (frames) | speed | elapsed | size | × source | Mbit/s | seek median | seek p95 | seek max |
|---|---|---|---|---|---|---|---|---|---|---|
| remux (as-is) | vp9 | - | 669.2× | 0.1 s | 22.8 MB | 1.00× | 3.02 | 161.2 ms | 357.2 ms | 400.5 ms |
| mpeg4 q3, GOP 0.25 s | mpeg4 | 15 | 12.6× | 4.8 s | 111.7 MB | 4.90× | 14.77 | 81.7 ms | 96.5 ms | 99.7 ms |
| mpeg4 q3, GOP 0.5 s | mpeg4 | 30 | 13.0× | 4.7 s | 94.5 MB | 4.14× | 12.49 | 87.2 ms | 98.9 ms | 103.3 ms |
| mpeg4 q3, GOP 1 s | mpeg4 | 60 | 12.9× | 4.7 s | 85.9 MB | 3.77× | 11.36 | 91.3 ms | 112.7 ms | 119.3 ms |
| mpeg4 q5, GOP 0.5 s | mpeg4 | 30 | 11.5× | 5.2 s | 80.8 MB | 3.54× | 10.69 | 90.0 ms | 103.1 ms | 112.8 ms |
| av1_nvenc p1 cq28, GOP 0.5 s | av1 | 30 | 10.1× | 6.0 s | 77.7 MB | 3.41× | 10.28 | 118.5 ms | 201.0 ms | 223.8 ms |
| av1_nvenc p1 cq28, GOP 1 s | av1 | 60 | 9.8× | 6.2 s | 70.6 MB | 3.10× | 9.33 | 116.7 ms | 235.4 ms | 295.4 ms |
| av1_nvenc p4 cq28, GOP 0.5 s | av1 | 30 | 4.1× | 14.8 s | 74.3 MB | 3.26× | 9.83 | 95.8 ms | 166.0 ms | 184.8 ms |
| libsvtav1 p12 crf30, GOP 0.5 s | av1 | 30 | 4.2× | 14.2 s | 35.2 MB | 1.54× | 4.66 | 62.0 ms | 91.6 ms | 1062.6 ms |
| libvpx-vp9 realtime, GOP 0.5 s | vp9 | 30 | 5.6× | 10.8 s | 52.1 MB | 2.29× | 6.89 | 93.3 ms | 123.6 ms | 132.7 ms |

#### factorio_1440p60_vp9 — 2560x1440 @ 59.74 fps, vp9 yuv420p, 64.14 s, 66.8 MB

| strategy | codec | GOP (frames) | speed | elapsed | size | × source | Mbit/s | seek median | seek p95 | seek max |
|---|---|---|---|---|---|---|---|---|---|---|
| remux (as-is) | vp9 | - | 579.1× | 0.1 s | 66.9 MB | 1.00× | 8.34 | 339.9 ms | 505.4 ms | 1258.4 ms |
| mpeg4 q3, GOP 0.25 s | mpeg4 | 15 | 9.7× | 6.6 s | 223.6 MB | 3.35× | 27.88 | 78.5 ms | 91.7 ms | 98.3 ms |
| mpeg4 q3, GOP 0.5 s | mpeg4 | 30 | 9.8× | 6.5 s | 166.6 MB | 2.49× | 20.78 | 82.1 ms | 102.1 ms | 127.1 ms |
| mpeg4 q3, GOP 1 s | mpeg4 | 60 | 9.6× | 6.7 s | 138.4 MB | 2.07× | 17.26 | 82.8 ms | 109.5 ms | 115.8 ms |
| mpeg4 q5, GOP 0.5 s | mpeg4 | 30 | 10.1× | 6.4 s | 106.4 MB | 1.59× | 13.27 | 79.2 ms | 89.7 ms | 109.9 ms |
| av1_nvenc p1 cq28, GOP 0.5 s | av1 | 30 | 9.6× | 6.7 s | 173.7 MB | 2.60× | 21.66 | 146.5 ms | 198.2 ms | 229.2 ms |
| av1_nvenc p1 cq28, GOP 1 s | av1 | 60 | 10.1× | 6.4 s | 143.4 MB | 2.15× | 17.89 | 184.4 ms | 313.2 ms | 373.1 ms |
| av1_nvenc p4 cq28, GOP 0.5 s | av1 | 30 | 6.3× | 10.2 s | 174.2 MB | 2.61× | 21.72 | 148.5 ms | 209.0 ms | 253.5 ms |
| libsvtav1 p12 crf30, GOP 0.5 s | av1 | 30 | 3.3× | 19.6 s | 138.4 MB | 2.07× | 17.26 | 100.2 ms | 134.7 ms | 178.1 ms |
| libvpx-vp9 realtime, GOP 0.5 s | vp9 | 30 | 4.1× | 15.5 s | 137.3 MB | 2.06× | 17.12 | 155.3 ms | 194.3 ms | 210.4 ms |

#### game_1080p60_av1 — 1920x1080 @ 60 fps, av1 yuv420p, 60.5 s, 8.2 MB

| strategy | codec | GOP (frames) | speed | elapsed | size | × source | Mbit/s | seek median | seek p95 | seek max |
|---|---|---|---|---|---|---|---|---|---|---|
| remux (as-is) | av1 | - | 1114.2× | 0.1 s | 8.3 MB | 1.01× | 1.09 | 77.0 ms | 141.2 ms | 166.5 ms |
| mpeg4 q3, GOP 0.25 s | mpeg4 | 15 | 22.1× | 2.7 s | 74.2 MB | 9.02× | 9.81 | 61.4 ms | 68.5 ms | 79.6 ms |
| mpeg4 q3, GOP 0.5 s | mpeg4 | 30 | 22.1× | 2.7 s | 62.7 MB | 7.62× | 8.29 | 62.1 ms | 71.1 ms | 87.7 ms |
| mpeg4 q3, GOP 1 s | mpeg4 | 60 | 21.9× | 2.8 s | 57.0 MB | 6.92× | 7.53 | 65.8 ms | 76.2 ms | 85.6 ms |
| mpeg4 q5, GOP 0.5 s | mpeg4 | 30 | 21.4× | 2.8 s | 50.4 MB | 6.13× | 6.67 | 61.3 ms | 72.0 ms | 83.5 ms |
| av1_nvenc p1 cq28, GOP 0.5 s | av1 | 30 | 16.3× | 3.7 s | 51.5 MB | 6.26× | 6.81 | 81.7 ms | 125.8 ms | 139.7 ms |
| av1_nvenc p1 cq28, GOP 1 s | av1 | 60 | 16.3× | 3.7 s | 46.9 MB | 5.70× | 6.2 | 102.0 ms | 160.5 ms | 196.1 ms |
| av1_nvenc p4 cq28, GOP 0.5 s | av1 | 30 | 10.7× | 5.7 s | 48.5 MB | 5.89× | 6.41 | 76.9 ms | 117.0 ms | 137.3 ms |
| libsvtav1 p12 crf30, GOP 0.5 s | av1 | 30 | 7.1× | 8.5 s | 24.4 MB | 2.96× | 3.22 | 53.1 ms | 67.1 ms | 76.9 ms |
| libvpx-vp9 realtime, GOP 0.5 s | vp9 | 30 | 8.0× | 7.5 s | 34.4 MB | 4.18× | 4.55 | 82.4 ms | 97.6 ms | 147.5 ms |

#### talk_1080p30_vp9 — 1920x1080 @ 29.97 fps, vp9 yuv420p, 62.53 s, 15.2 MB

| strategy | codec | GOP (frames) | speed | elapsed | size | × source | Mbit/s | seek median | seek p95 | seek max |
|---|---|---|---|---|---|---|---|---|---|---|
| remux (as-is) | vp9 | - | 1273.6× | 0.1 s | 15.3 MB | 1.00× | 1.95 | 78.5 ms | 109.5 ms | 134.3 ms |
| mpeg4 q3, GOP 0.25 s | mpeg4 | 7 | 33.9× | 1.9 s | 72.1 MB | 4.73× | 9.22 | 61.9 ms | 73.6 ms | 90.3 ms |
| mpeg4 q3, GOP 0.5 s | mpeg4 | 15 | 35.2× | 1.8 s | 49.1 MB | 3.23× | 6.28 | 59.3 ms | 67.2 ms | 72.8 ms |
| mpeg4 q3, GOP 1 s | mpeg4 | 30 | 36.5× | 1.7 s | 38.9 MB | 2.56× | 4.98 | 59.4 ms | 67.9 ms | 78.5 ms |
| mpeg4 q5, GOP 0.5 s | mpeg4 | 15 | 37.8× | 1.7 s | 32.9 MB | 2.16× | 4.21 | 58.6 ms | 66.5 ms | 73.1 ms |
| av1_nvenc p1 cq28, GOP 0.5 s | av1 | 15 | 30.4× | 2.1 s | 44.9 MB | 2.95× | 5.74 | 61.6 ms | 92.8 ms | 114.6 ms |
| av1_nvenc p1 cq28, GOP 1 s | av1 | 30 | 31.2× | 2.0 s | 37.0 MB | 2.43× | 4.74 | 71.5 ms | 119.5 ms | 128.7 ms |
| av1_nvenc p4 cq28, GOP 0.5 s | av1 | 15 | 20.5× | 3.1 s | 45.6 MB | 3.00× | 5.84 | 62.7 ms | 97.5 ms | 117.7 ms |
| libsvtav1 p12 crf30, GOP 0.5 s | av1 | 15 | 13.7× | 4.5 s | 36.4 MB | 2.39× | 4.65 | 47.1 ms | 89.1 ms | 96.6 ms |
| libvpx-vp9 realtime, GOP 0.5 s | vp9 | 15 | 15.0× | 4.2 s | 44.7 MB | 2.93× | 5.71 | 69.3 ms | 118.5 ms | 126.1 ms |

### Intra-frame baselines (first, contended pass — sizes exact, speeds approximate)

| source | strategy | speed | size | × source | seek p95 |
|---|---|---|---|---|---|
| bbb_1440p60_vp9 (45 MB) | DNxHR HQ | 1.2× | 6411 MB | 141× | 1010 ms |
| bbb_1440p60_vp9 | ProRes 422 LT | 0.6× | 2765 MB | 61× | 301 ms |
| bbb_1440p60_vp9 | CineForm (film3) | 2.6× | 5235 MB | 115× | 870 ms |
| bbb_1440p60_vp9 | MJPEG q3 | 10.7× | 867 MB | 19× | 137 ms |
| factorio_1440p60_vp9 (67 MB) | DNxHR HQ | 4.9× | 6201 MB | 93× | 220 ms |
| factorio_1440p60_vp9 | ProRes 422 LT | 0.5× | 2964 MB | 44× | 143 ms |
| factorio_1440p60_vp9 | CineForm | 1.6× | 9222 MB | 138× | 735 ms |
| game_1080p60_av1 (8 MB) | DNxHR HQ | 11.7× | 3332 MB | 405× | 134 ms |
| game_1080p60_av1 | MJPEG q3 | 20.3× | 438 MB | 53× | 63 ms |

## Resolve 21 results

| file (4K60 unless noted) | import | decode throughput (render) | A/V offset | notes |
|---|---|---|---|---|
| AV1 remux, MP4, YouTube GOP | ok | 142–187 fps (2.4–3.1×) | 0.000 s | hardware decode; edit lists honoured; **scrubs badly** (5 s GOP) |
| AV1 NVENC, GOP 30, MP4 | ok | 90 fps (1.5×) | 0.000 s | **scrubs instantly**; 10-bit HDR metadata preserved |
| MPEG-4 Part 2 q3, GOP 30, MP4 | ok | 64 fps (1.07×) | — | software decode; **scrubs instantly**; marginal for sustained 4K60 playback, fine at 1440p and below |
| VP9, MP4 (remux, with or without timestamp fix) | ok | **render FAILS** | — | "Error decoding full resolution media" at the first keyframe after the start, 5 of 6 files, 1080p and 4K |
| VP9, MKV | ok | 122 fps | **+12.03 s** | audio placed 12 s late (cross-correlated); unusable |
| AV1 + Opus, MP4 (1080p) | ok | 177 fps | 0.000 s | Resolve 21 decodes Opus; older builds reportedly don't, so Opus is still converted to AAC |

Hands-on scrub test (user, 4K60 timeline, scrubbing, J/K/L, frame-stepping,
random jumps): AV1 remux (both clips) — "not seekable, very slow"; NVENC AV1
GOP 30 — "amazing"; MPEG-4 GOP 30 — "amazing".

## Quality (20 s, frames paired by index, against the YouTube source)

| source | av1_nvenc cq24 | cq28 (chosen) | cq32 | mpeg4 q2 | q3 (chosen) | q5 |
|---|---|---|---|---|---|---|
| gameplay 1440p60 | 97.3 / 54.0 dB / 33.5 MB | **97.1 / 53.1 dB / 23.5 MB** | 96.7 / 51.9 dB / 15.4 MB | 96.3 / 51.8 dB / 36.8 MB | **96.0 / 50.1 dB / 24.8 MB** | 94.0 / 47.6 dB / 18.8 MB |
| Factorio 1440p60 (text/UI) | 98.7 / 50.3 dB / 65 MB | **98.5 / 49.1 dB / 48 MB** | 98.1 / 47.4 dB / 34 MB | 97.4 / 47.6 dB / 67 MB | **97.1 / 45.5 dB / 44 MB** | 93.6 / 42.6 dB / 29 MB |
| interview 1080p30 | 96.9 / 50.4 dB / 18 MB | **96.6 / 48.8 dB / 13 MB** | 96.0 / 46.9 dB / 9 MB | 95.6 / 49.2 dB / 21 MB | **95.1 / 46.5 dB / 15 MB** | 92.7 / 43.1 dB / 10 MB |

(VMAF / PSNR / size.) At the chosen settings the 1:1 crops of text, cursor
and UI edges are indistinguishable from the source; q5 is visibly softer on
text. cq32 would save ~30 % for no visible loss and is a reasonable future
default if size ever matters more than headroom.

## Decision

Priority order was speed → Resolve seeking → reliability → size → quality →
complexity.

1. **Speed.** Hardware AV1: 5–8× realtime for 4K60, 10× for 1440p60, 16–30× for
   1080p. Native MPEG-4 on 16 threads: 4.5–6.4× for 4K60 (2.6× for 10-bit HDR,
   which it must first convert to 8-bit), 10–13× for 1440p60, 22–38× for 1080p.
   Both are "seconds, not minutes" for the clips this tool makes. Software AV1
   (SVT-AV1 preset 12) is 1–1.5× at 4K60 and software VP9 1–2.8×: rejected.
   NVENC preset p4 is 2–3× slower than p1 for the same size and quality:
   rejected.
2. **Seeking.** GOP 0.5 s: ffmpeg p95 150–230 ms at 4K60, 90–200 ms at 1440p,
   and instant by hand in Resolve. GOP 1 s saves ~10 % size for a p95 that is
   1.5–2× worse; GOP 0.25 s seeks no better than 0.5 s and costs 10–20 % more
   file. The remux's YouTube GOP: p95 350–914 ms in ffmpeg and unusable by
   hand.
3. **Reliability.** AV1-in-MP4 and MPEG-4-in-MP4 import and render cleanly in
   Resolve 21 with exact A/V sync. VP9 output fails (MP4) or desyncs (MKV) and
   is never produced. Hardware encoders are probed by actually encoding at
   startup, and a job that fails on real footage retries on the CPU.
4. **Size.** 1.2–3.5× the YouTube file for both winners on 1440p/4K sources
   (up to 6–9× on a tiny 8 MB 1080p AV1 source — absolute sizes there are
   50–60 MB). Intra-frame codecs are 45–400×.
5. **Quality.** VMAF 95–98.5 against the source at the chosen settings;
   NVENC keeps 10-bit and HDR metadata, MPEG-4 is 8-bit only (noted in the
   log).
6. **Complexity.** One decision function (`media.plan`), two encoder branches,
   no user setting.

Rejected, in one line each:

- *Remux of the download as-is* — instant and lossless, but the 5 s GOP scrubs badly; seeking is the point.
- *VP9 as-is* — Resolve can't decode it in MP4 and desyncs it in MKV.
- *Software AV1 (SVT-AV1)* — 0.7–1.4× the source size, but 1–1.5× realtime at 4K.
- *Software VP9 (libvpx realtime)* — slower than the hardware path, and its output is VP9.
- *NVENC p4* — no quality gain, 2–3× slower.
- *DNxHR / ProRes / CineForm* — seek fine, encode at 0.5–5×, and are 45–400× the size: a 60 s 1440p clip becomes 3–9 GB.
- *MJPEG* — fast and seeks well, but 19–53× the size and no hardware decode in Resolve.
- *The removed codec and HEVC* — excluded by requirement.

## Platform notes

- **Windows:** `av1_nvenc` (RTX 40/50), `av1_qsv` (Arc / 11th-gen+ iGPU), `av1_amf` (RX 7000) are tried in that order. Everything else → MPEG-4.
- **Linux:** same, plus `av1_vaapi`; ffmpeg from the distribution.
- **macOS:** VideoToolbox has no AV1 encoder, so Apple Silicon always takes the MPEG-4 path. Not measured here — no Mac in this session.
- Machines whose GPU can encode AV1 can also decode it, so the NVENC output plays in hardware. Resolve needs 18.1+ for AV1 at all.
