"""Check warning preservation, offline process boundaries, and real media output."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

from igw_google_voice import cast_media


def reports():
    return {
        "status": {"status": "fresh", "text": "Battery is 74 percent. Solar is 1200 watts."},
        "battery": {"status": "fresh", "text": "Battery is 74 percent."},
        "solar": {"status": "fresh", "text": "Solar power is 1200 watts."},
        "solar_today": {"status": "unavailable", "text": "Solar energy today is unavailable."},
        "alarms": {"status": "stale", "text": "Alarm information is stale. Check the gateway."},
    }


def write_silence(path, duration=0.2):
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(22050)
        audio.writeframes(b"\0\0" * int(22050 * duration))


class CastLayoutTests(unittest.TestCase):
    def test_four_cards_preserve_central_missing_data_and_stale_warnings(self):
        pages = cast_media._layout_pages("status", reports())
        self.assertEqual(len(pages), 1)
        self.assertEqual([card.key for card in pages[0]], list(cast_media.OVERVIEW_KEYS))
        for card in pages[0]:
            self.assertEqual(" ".join(card.lines), reports()[card.key]["text"])
            self.assertEqual(card.status, reports()[card.key]["status"])

    def test_long_warnings_continue_without_truncation(self):
        data = reports()
        text = ("Measurements are unavailable. Check the gateway connection. " * 20).strip()
        data["solar_today"]["text"] = text
        pages = cast_media._layout_pages("status", data)
        self.assertGreater(len(pages), 1)
        continuation = [next(card for card in page if card.key == "solar_today") for page in pages]
        self.assertEqual(" ".join(line for card in continuation for line in card.lines), text)
        self.assertTrue(all(card.status == "unavailable" for card in continuation))

    def test_single_long_token_is_wrapped_with_no_characters_lost(self):
        font = cast_media._font(22)
        text = "A" * 1200
        lines = cast_media._wrap_text(text, font, 520)
        self.assertEqual("".join(lines), text)
        self.assertTrue(all(font.getlength(line) <= 520 for line in lines))

    def test_individual_report_has_only_requested_card_and_fixed_resolution(self):
        pages = cast_media._layout_pages("alarms", reports())
        self.assertEqual([card.key for card in pages[0]], ["alarms"])
        frame = cast_media._draw_page("alarms", "stale", pages[0], 1, 1, "2000-01-01 00:00 UTC")
        self.assertEqual(frame.size, (1280, 720))
        self.assertEqual(frame.mode, "RGB")

    def test_invalid_reports_fail_before_process_launch(self):
        bad_inputs = [("unknown", reports()), ("status", {}), ("status", [])]
        for status in ("unknown", ["fresh"], None):
            data = reports()
            data["battery"]["status"] = status
            bad_inputs.append(("status", data))
        for text in ("", " " * 2, "X" * 1201, None, "bad\0text"):
            data = reports()
            data["battery"]["text"] = text
            bad_inputs.append(("status", data))
        with patch.object(cast_media.subprocess, "run") as run:
            for key, data in bad_inputs:
                with self.subTest(key=key, data=data), self.assertRaises(ValueError):
                    cast_media.render_report_video(key, data, Path("unused.mp4"))
            run.assert_not_called()


class CastProcessTests(unittest.TestCase):
    def test_speech_is_exact_stdin_and_never_a_command_argument(self):
        text = "Solar unavailable; $(echo private) <break/> -f /tmp/example."
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "speech.wav"

            def synthesize(command, **kwargs):
                self.assertNotIn(text, command)
                self.assertEqual(kwargs["input_bytes"], text.encode("utf-8"))
                self.assertIn("--stdin", command)
                self.assertNotIn("-m", command)
                write_silence(output)

            with patch.object(cast_media, "_run", side_effect=synthesize):
                self.assertAlmostEqual(cast_media._synthesize_speech(text, output, "espeak-ng"), 0.2)

    def test_speech_over_limit_is_rejected_not_cut_off(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "speech.wav"
            with patch.object(cast_media, "_run", side_effect=lambda *args, **kwargs: write_silence(output, 116)):
                with self.assertRaisesRegex(ValueError, "duration limit"):
                    cast_media._synthesize_speech("Unusually long speech.", output, "espeak-ng")

    def test_process_failures_do_not_expose_stderr(self):
        failure = subprocess.CompletedProcess(["example"], 1, stderr=b"private report text")
        with patch.object(cast_media.subprocess, "run", return_value=failure) as run:
            with self.assertRaises(RuntimeError) as error:
                cast_media._run(["example"], timeout=3)
            self.assertNotIn("private", str(error.exception))
            self.assertNotIn("shell", run.call_args.kwargs)
            self.assertEqual(run.call_args.kwargs["timeout"], 3)

    def test_failed_generation_preserves_previous_output_and_removes_work_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report.mp4"
            output.write_bytes(b"existing")
            with patch.object(cast_media.shutil, "which", return_value="tool"), \
                 patch.object(cast_media, "_synthesize_speech", side_effect=RuntimeError("Failed")):
                with self.assertRaises(RuntimeError):
                    cast_media.render_report_video("status", reports(), output)
            self.assertEqual(output.read_bytes(), b"existing")
            self.assertEqual(list(Path(temporary).iterdir()), [output])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe not installed")
    def test_real_encoder_outputs_bounded_cast_compatible_snapshot(self):
        actual_which = shutil.which

        def find_tool(name):
            return "mock-espeak-ng" if name == "espeak-ng" else actual_which(name)

        def synthesize(text, path, executable):
            self.assertEqual(text, "Short central summary with warnings.")
            write_silence(path)
            return 0.2

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report.mp4"
            with patch.object(cast_media.shutil, "which", side_effect=find_tool), \
                 patch.object(cast_media, "_synthesize_speech", side_effect=synthesize):
                data = reports()
                data["status"]["brief_text"] = "Short central summary with warnings."
                result = cast_media.render_report_video("status", data, output)
            probe = subprocess.run([actual_which("ffprobe"), "-v", "error", "-show_streams",
                                    "-show_format", "-of", "json", str(output)],
                                   capture_output=True, check=True, timeout=15)
            metadata = json.loads(probe.stdout)
            video = next(stream for stream in metadata["streams"] if stream["codec_type"] == "video")
            audio = next(stream for stream in metadata["streams"] if stream["codec_type"] == "audio")
            self.assertEqual((video["codec_name"], video["width"], video["height"], video["pix_fmt"]),
                             ("h264", 1280, 720, "yuv420p"))
            self.assertEqual(audio["codec_name"], "aac")
            self.assertAlmostEqual(float(metadata["format"]["duration"]), result["duration_seconds"], delta=0.1)
            self.assertLessEqual(result["duration_seconds"], 120)
            payload = output.read_bytes()
            self.assertLess(payload.index(b"moov"), payload.index(b"mdat"))
            self.assertEqual(list(Path(temporary).iterdir()), [output])

    @unittest.skipUnless(shutil.which("espeak-ng") and shutil.which("ffmpeg"), "espeak-ng/ffmpeg not installed")
    def test_real_offline_speech_and_video(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report.mp4"
            result = cast_media.render_report_video("battery", reports(), output)
            self.assertGreater(result["duration_seconds"], 5)
            self.assertGreater(output.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
