"""
Tests for backend/media.py — the codec decision engine.

Everything here is pure: no ffmpeg, no network. The probe parser is fed
ffprobe-shaped dicts, capability detection is fed fake results, and the plans
and commands are checked as data.

Run:  py -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import sys
import unittest
from fractions import Fraction
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

import media  # noqa: E402

FF = "ffmpeg"


def src(vcodec="av1", acodec="aac", container="mov,mp4,m4a,3gp,3g2,mj2", fps=Fraction(60),
        pix_fmt="yuv420p", duration=20.0, video_duration=None, audio_start=None,
        color=None, width=3840, height=2160) -> media.SourceInfo:
    return media.SourceInfo(
        path="C:/clips/x.src.mp4", container=container, vcodec=vcodec, acodec=acodec,
        width=width, height=height, pix_fmt=pix_fmt, fps=fps, duration=duration,
        video_duration=video_duration, video_start=0.0, audio_start=audio_start,
        color=color or {})


HW = media.Capabilities(av1_encoder="av1_nvenc")
NONE = media.Capabilities()


# --------------------------------------------------------------------------- #
# Probe parsing
# --------------------------------------------------------------------------- #

class ParseProbe(unittest.TestCase):
    def test_basic_fields(self):
        data = {
            "format": {"format_name": "matroska,webm", "duration": "66.034000"},
            "streams": [
                {"codec_type": "video", "codec_name": "av1", "width": 3840, "height": 2160,
                 "pix_fmt": "yuv420p10le", "r_frame_rate": "60/1", "start_time": "0.000000",
                 "color_primaries": "bt2020", "color_transfer": "smpte2084",
                 "color_space": "bt2020nc", "color_range": "tv"},
                {"codec_type": "audio", "codec_name": "opus", "start_time": "6.011000"},
            ],
        }
        i = media._parse_probe(data, "x.mkv")
        self.assertEqual(i.vcodec, "av1")
        self.assertEqual(i.acodec, "opus")
        self.assertEqual(i.fps, Fraction(60))
        self.assertEqual(i.bit_depth, 10)
        self.assertTrue(i.is_hdr)
        self.assertAlmostEqual(i.duration, 66.034)
        self.assertIsNone(i.video_duration)
        self.assertIn("10-bit", i.describe())
        self.assertIn("HDR", i.describe())

    def test_no_audio_and_odd_rate(self):
        data = {"format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "10"},
                "streams": [{"codec_type": "video", "codec_name": "vp9", "width": 1920,
                             "height": 1080, "pix_fmt": "yuv420p", "r_frame_rate": "20371/341",
                             "duration": "10.0"}]}
        i = media._parse_probe(data, "x.mp4")
        self.assertIsNone(i.acodec)
        self.assertEqual(i.fps, Fraction(20371, 341))
        self.assertEqual(i.bit_depth, 8)
        self.assertEqual(i.video_duration, 10.0)

    def test_rotation_side_data(self):
        data = {"format": {}, "streams": [{"codec_type": "video", "codec_name": "hevc",
                                            "r_frame_rate": "30/1",
                                            "side_data_list": [{"rotation": -90}]}]}
        self.assertEqual(media._parse_probe(data, "x").rotation, 270)

    def test_unreadable_rate(self):
        data = {"format": {}, "streams": [{"codec_type": "video", "codec_name": "vp9",
                                            "r_frame_rate": "0/0"}]}
        self.assertEqual(media._parse_probe(data, "x").fps, Fraction(0))


class Rates(unittest.TestCase):
    def test_gop_from_rate(self):
        self.assertEqual(media.gop_frames(Fraction(30)), 15)
        self.assertEqual(media.gop_frames(Fraction(60)), 30)
        self.assertEqual(media.gop_frames(Fraction(24)), 12)
        self.assertEqual(media.gop_frames(Fraction(25)), 12)     # 12.5 rounds to even
        self.assertEqual(media.gop_frames(Fraction(30000, 1001)), 15)
        self.assertEqual(media.gop_frames(Fraction(20371, 341)), 30)
        self.assertEqual(media.gop_frames(Fraction(1)), 1)       # never zero

    def test_nle_rate_snapping(self):
        self.assertEqual(media.nle_rate(Fraction(60)), Fraction(60))
        self.assertEqual(media.nle_rate(Fraction(60000, 1001)), Fraction(60000, 1001))
        self.assertEqual(media.nle_rate(Fraction(19001, 317)), Fraction(60000, 1001))
        self.assertEqual(media.nle_rate(Fraction(20371, 341)), Fraction(60000, 1001))
        self.assertEqual(media.nle_rate(Fraction(15)), Fraction(15))       # too far: kept
        self.assertEqual(media.nle_rate(Fraction(0)), Fraction(30))


class Lead(unittest.TestCase):
    def test_edit_listed_mp4_has_no_lead(self):
        # yt-dlp's MP4 output hides the keyframe lead behind an edit list: the
        # video track reads 20.0 s while the audio runs a packet longer.
        s = src(duration=20.017, video_duration=20.0)
        self.assertEqual(s.lead_seconds(20.0), 0.0)

    def test_matroska_lead_from_duration(self):
        s = src(container="matroska,webm", duration=66.034)
        self.assertAlmostEqual(s.lead_seconds(60.0), 6.034)

    def test_audio_anchor_when_length_unknown(self):
        s = src(container="matroska,webm", duration=66.0, audio_start=6.011)
        self.assertAlmostEqual(s.lead_seconds(None), 6.011)

    def test_implausible_lead_is_ignored(self):
        s = src(duration=100.0)
        self.assertEqual(s.lead_seconds(20.0), 0.0)        # 80 s lead: nonsense


# --------------------------------------------------------------------------- #
# Plans
# --------------------------------------------------------------------------- #

class Plans(unittest.TestCase):
    def test_everything_is_transcoded(self):
        # No source is handed over as-is: YouTube's ~5 s keyframes seek badly.
        for vc in ("av1", "vp9", "vp8", "hevc", "prores"):
            for caps in (HW, NONE):
                p = media.plan(src(vcodec=vc), caps)
                self.assertIn(p.encoder, ("av1_nvenc", "mpeg4"))
                self.assertEqual(p.gop, 30)
                self.assertEqual(p.container, "mp4")

    def test_hardware_av1_preferred(self):
        p = media.plan(src(vcodec="vp9"), HW, media.Section(100, 160))
        self.assertEqual(p.encoder, "av1_nvenc")
        self.assertTrue(p.hardware)
        self.assertEqual(p.video_args[p.video_args.index("-g") + 1], "30")
        self.assertEqual(p.video_args[p.video_args.index("-bf") + 1], "0")
        self.assertEqual(p.input_args, ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"])
        self.assertEqual(p.trim, (0.0, 60.0))

    def test_cpu_fallback_is_mpeg4(self):
        p = media.plan(src(vcodec="vp9", fps=Fraction(30)), NONE, media.Section(0, 30))
        self.assertEqual(p.encoder, "mpeg4")
        self.assertFalse(p.hardware)
        self.assertEqual(p.gop, 15)
        self.assertEqual(p.video_args[p.video_args.index("-pix_fmt") + 1], "yuv420p")
        self.assertEqual(p.input_args, [])

    def test_other_hw_encoders(self):
        for enc in ("av1_qsv", "av1_amf", "av1_vaapi"):
            p = media.plan(src(vcodec="vp9"), media.Capabilities(av1_encoder=enc))
            self.assertEqual(p.encoder, enc)
            self.assertEqual(p.video_args[:2], ["-c:v", enc])
            self.assertIn("-g", p.video_args)

    def test_ten_bit_hdr_kept_on_hardware_and_flagged_on_cpu(self):
        hdr = src(vcodec="vp9", pix_fmt="yuv420p10le",
                  color={"transfer": "smpte2084", "primaries": "bt2020"})
        p = media.plan(hdr, HW)
        self.assertTrue(any("10-bit" in n for n in p.notes))
        self.assertNotIn("yuv420p", p.video_args)
        p = media.plan(hdr, NONE)
        self.assertEqual(p.encoder, "mpeg4")
        self.assertTrue(any("8-bit" in n for n in p.notes))

    def test_whole_video_applies_no_trim(self):
        # AAC priming can make the audio start a few ms late; not a lead.
        p = media.plan(src(duration=600, audio_start=0.023), HW, None)
        self.assertIsNone(p.trim)

    def test_lead_becomes_the_trim(self):
        s = src(vcodec="vp9", container="matroska,webm", duration=66.034)
        p = media.plan(s, HW, media.Section(180, 240))
        self.assertAlmostEqual(p.trim[0], 6.034)
        self.assertAlmostEqual(p.trim[1], 66.034)

    def test_edit_listed_section_trims_from_zero(self):
        s = src(duration=20.017, video_duration=20.0)
        p = media.plan(s, HW, media.Section(180, 200))
        self.assertEqual(p.trim, (0.0, 20.0))

    def test_opus_audio_is_converted(self):
        p = media.plan(src(acodec="opus"), HW)
        self.assertEqual(p.audio_args[:2], ["-c:a", "aac"])
        self.assertTrue(any("opus" in n for n in p.notes))

    def test_aac_is_copied_and_no_audio_is_fine(self):
        self.assertEqual(media.plan(src(acodec="aac"), HW).audio_args, ["-c:a", "copy"])
        self.assertEqual(media.plan(src(acodec=None), HW).audio_args, ["-c:a", "copy"])

    def test_odd_rate_is_conformed(self):
        p = media.plan(src(vcodec="vp9", fps=Fraction(20371, 341)), HW)
        self.assertEqual(p.rate, Fraction(60000, 1001))
        self.assertTrue(any("conformed" in n for n in p.notes))

    def test_standard_rate_is_kept_quietly(self):
        p = media.plan(src(fps=Fraction(60)), HW)
        self.assertEqual(p.rate, Fraction(60))
        self.assertFalse(any("conformed" in n for n in p.notes))

    def test_unknown_rate_defaults(self):
        p = media.plan(src(vcodec="vp9", fps=Fraction(0)), NONE)
        self.assertEqual(p.gop, 15)          # 30 fps assumed
        self.assertEqual(p.rate, Fraction(30))


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

class Commands(unittest.TestCase):
    def test_transcode_command_trims_and_conforms(self):
        s = src(vcodec="vp9", container="matroska,webm", duration=66.034)
        p = media.plan(s, HW, media.Section(180, 240))
        cmd = media.build_command(FF, s, p, "out.mp4")
        self.assertEqual(cmd[0], FF)
        i = cmd.index("-i")
        # hwaccel and the seek both precede -i
        self.assertLess(cmd.index("-hwaccel"), i)
        self.assertLess(cmd.index("-ss"), i)
        self.assertEqual(cmd[cmd.index("-ss") + 1], "6.034000")
        self.assertEqual(cmd[cmd.index("-t") + 1], "60.000000")
        self.assertEqual(cmd[cmd.index("-fps_mode") + 1], "cfr")
        self.assertEqual(cmd[cmd.index("-r") + 1], "60/1")
        self.assertIn("av1_nvenc", cmd)
        self.assertIn("+faststart", cmd)
        self.assertIn("-progress", cmd)
        self.assertEqual(cmd[-1], "out.mp4")

    def test_whole_video_command_has_no_seek(self):
        s = src(duration=600)
        cmd = media.build_command(FF, s, media.plan(s, HW), "out.mp4")
        self.assertNotIn("-ss", cmd)
        self.assertNotIn("-t", cmd)

    def test_cpu_transcode_command(self):
        s = src(vcodec="vp9", fps=Fraction(30000, 1001), duration=30)
        p = media.plan(s, NONE, media.Section(0, 30))
        cmd = media.build_command(FF, s, p, "out.mp4")
        self.assertNotIn("-hwaccel", cmd)
        self.assertEqual(cmd[cmd.index("-c:v") + 1], "mpeg4")
        self.assertEqual(cmd[cmd.index("-g") + 1], "15")
        self.assertEqual(cmd[cmd.index("-r") + 1], "30000/1001")

    def test_output_path(self):
        p = media.plan(src(), HW)
        self.assertEqual(media.output_path_for("C:/clips/a-c001.mp4", p), "C:/clips/a-c001.mp4")
        self.assertEqual(media.output_path_for("C:/clips/a-full.webm", p), "C:/clips/a-full.mp4")

    def test_estimate_is_positive_and_hardware_is_faster(self):
        s = src(vcodec="vp9", duration=60)
        hw = media.estimate_seconds(s, media.plan(s, HW))
        cpu = media.estimate_seconds(s, media.plan(s, NONE))
        self.assertGreater(hw, 0)
        self.assertLess(hw, cpu)


# --------------------------------------------------------------------------- #
# Hardware detection (ffmpeg mocked)
# --------------------------------------------------------------------------- #

class Capabilities(unittest.TestCase):
    def test_first_working_encoder_wins(self):
        with mock.patch.object(media, "_try_encoder", side_effect=lambda ff, enc: enc == "av1_qsv"):
            caps = media.probe_capabilities(FF, platform="win32")
        self.assertEqual(caps.av1_encoder, "av1_qsv")

    def test_order_is_nvenc_first_on_windows(self):
        with mock.patch.object(media, "_try_encoder", return_value=True):
            caps = media.probe_capabilities(FF, platform="win32")
        self.assertEqual(caps.av1_encoder, "av1_nvenc")

    def test_absent_hardware(self):
        with mock.patch.object(media, "_try_encoder", return_value=False):
            caps = media.probe_capabilities(FF, platform="win32")
        self.assertIsNone(caps.av1_encoder)
        self.assertEqual(media.plan(src(vcodec="vp9"), caps).encoder, "mpeg4")
        self.assertEqual(media.plan(src(vcodec="av1"), caps).encoder, "mpeg4")
        self.assertIn("CPU", caps.describe())

    def test_macos_has_no_hw_av1_encoder(self):
        with mock.patch.object(media, "_try_encoder", return_value=True) as enc:
            caps = media.probe_capabilities(FF, platform="darwin")
        enc.assert_not_called()
        self.assertIsNone(caps.av1_encoder)

    def test_failed_encoder_init_is_a_clean_false(self):
        # subprocess raising (missing binary, timeout) must read as "no".
        with mock.patch.object(media, "_run", side_effect=OSError("no ffmpeg")):
            self.assertFalse(media._try_encoder(FF, "av1_nvenc"))

    def test_nonzero_exit_is_false(self):
        proc = mock.Mock(returncode=1)
        with mock.patch.object(media, "_run", return_value=proc):
            self.assertFalse(media._try_encoder(FF, "av1_nvenc"))


# --------------------------------------------------------------------------- #
# The encoder guard
# --------------------------------------------------------------------------- #

class OnlyAllowedEncoders(unittest.TestCase):
    """No combination of source and hardware may ever choose a removed encoder."""

    SOURCES = [
        src(), src(vcodec="vp9"), src(vcodec="vp8"), src(vcodec="hevc"),
        src(vcodec="av1", container="matroska,webm"), src(vcodec="vp9", pix_fmt="yuv420p10le"),
        src(vcodec="prores"), src(vcodec="", fps=Fraction(0)), src(acodec="opus"),
    ]
    CAPS = [HW, NONE,
            media.Capabilities(av1_encoder="av1_qsv"),
            media.Capabilities(av1_encoder="av1_amf"),
            media.Capabilities(av1_encoder="av1_vaapi")]

    def test_every_branch(self):
        for s in self.SOURCES:
            for caps in self.CAPS:
                for section in (None, media.Section(0, 10), media.Section(100, 160)):
                    p = media.plan(s, caps, section)
                    media.assert_allowed_encoder(p)        # raises on a removed one
                    self.assertIn(p.encoder, ("av1_nvenc", "av1_qsv", "av1_amf",
                                              "av1_vaapi", "mpeg4"))
                    for arg in media.build_command(FF, s, p, "o.mp4"):
                        self.assertFalse(media.is_forbidden_encoder(arg), arg)

    def test_guard_catches_a_bad_plan(self):
        bad = media.FORBIDDEN_ENCODERS[0]
        p = media.Plan(encoder=bad)
        with self.assertRaises(ValueError):
            media.assert_allowed_encoder(p)
        p = media.Plan(encoder="mpeg4", video_args=["-c:v", media.FORBIDDEN_ENCODER_PREFIXES[0] + "nvenc"])
        with self.assertRaises(ValueError):
            media.assert_allowed_encoder(p)
        for name in media.FORBIDDEN_ENCODERS + tuple(pfx + "x" for pfx in media.FORBIDDEN_ENCODER_PREFIXES):
            self.assertTrue(media.is_forbidden_encoder(name))
            self.assertTrue(media.is_forbidden_encoder(name.upper()))
        for name in ("av1_nvenc", "mpeg4", "libsvtav1", "copy"):
            self.assertFalse(media.is_forbidden_encoder(name))


if __name__ == "__main__":
    unittest.main()
