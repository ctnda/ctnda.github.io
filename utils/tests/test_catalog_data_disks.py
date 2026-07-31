import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.catalog_data_disks import (
    catalogue_filename,
    ffprobe_metadata,
    render_html,
    resolve_disk_id,
    scan_disc,
)


class CatalogDataDisksTests(unittest.TestCase):
    def test_custom_identifier_is_preserved_and_filename_is_safe(self):
        disk_id = "CTNdA#015 / Edizione speciale"

        self.assertEqual(resolve_disk_id(disk_id, "/dev/sr0"), disk_id)
        filename = catalogue_filename(disk_id)
        self.assertTrue(filename.endswith(".json"))
        self.assertNotIn("/", filename)
        self.assertNotIn("#", filename)

    @patch("utils.catalog_data_disks.filesystem_label", return_value="ARCHIVIO_2026")
    def test_identifier_defaults_to_filesystem_label(self, filesystem_label):
        self.assertEqual(resolve_disk_id(None, "/dev/sr0"), "ARCHIVIO_2026")
        filesystem_label.assert_called_once_with("/dev/sr0")

    @patch("utils.catalog_data_disks.run_command")
    def test_ffprobe_extracts_only_requested_metadata(self, run_command):
        payload = {
            "format": {
                "duration": "3723.8",
                "format_name": "matroska,webm",
                "format_long_name": "Matroska / WebM",
                "bit_rate": "2500000",
            },
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "width": 1920,
                    "height": 1080,
                    "display_aspect_ratio": "16:9",
                    "avg_frame_rate": "24000/1001",
                },
                {"codec_type": "audio", "bit_rate": "192000"},
                {"codec_type": "subtitle", "tags": {"language": "ita"}},
                {"codec_type": "subtitle", "tags": {"language": "eng"}},
            ],
        }
        run_command.return_value = subprocess.CompletedProcess(
            ["ffprobe"], 0, json.dumps(payload), ""
        )

        metadata = ffprobe_metadata(Path("movie.mkv"), "ffprobe")

        self.assertEqual(metadata["duration_seconds"], 3723.8)
        self.assertEqual(metadata["duration_hms"], "01:02:03")
        self.assertEqual(metadata["container"], "Matroska / WebM")
        self.assertEqual(metadata["overall_bitrate_bps"], 2_500_000)
        self.assertEqual(metadata["video_codec"], "hevc")
        self.assertEqual((metadata["width"], metadata["height"]), (1920, 1080))
        self.assertEqual(metadata["aspect_ratio"], "16:9")
        self.assertAlmostEqual(metadata["frame_rate"], 23.976, places=3)
        self.assertEqual(metadata["audio_bitrates_bps"], [192_000])
        self.assertEqual(metadata["subtitle_count"], 2)
        self.assertEqual(metadata["subtitle_languages"], ["ita", "eng"])

    @patch("utils.catalog_data_disks.ffprobe_metadata")
    def test_scan_counts_files_and_keeps_relative_paths(self, ffprobe_metadata_mock):
        ffprobe_metadata_mock.return_value = {
            "duration_seconds": 10.0,
            "duration_hms": "00:00:10",
            "container": "AVI",
            "overall_bitrate_bps": 1000,
            "video_codec": "mpeg4",
            "width": 640,
            "height": 480,
            "aspect_ratio": "4:3",
            "frame_rate": 25.0,
            "audio_bitrates_bps": [128000],
            "subtitle_count": 0,
            "subtitle_languages": [],
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "folder").mkdir()
            (root / "folder" / "movie.avi").write_bytes(b"video")
            (root / "song.flac").write_bytes(b"audio")
            (root / "cover.jpg").write_bytes(b"image")
            (root / "notes.txt").write_bytes(b"text")

            catalog = scan_disc(root, "DISC-A", "Archivio", "ffprobe")

        self.assertEqual(
            catalog["disk"],
            {
                "id": "DISC-A",
                "label": "Archivio",
                "total_files": 4,
                "video_files": 1,
                "audio_files": 1,
                "image_files": 1,
                "other_files": 1,
            },
        )
        self.assertEqual(
            {record["path"] for record in catalog["files"]},
            {"folder/movie.avi", "song.flac", "cover.jpg", "notes.txt"},
        )
        self.assertEqual(ffprobe_metadata_mock.call_count, 2)

    def test_render_uses_datatables_and_escapes_catalog_values(self):
        catalog = {
            "schema_version": 1,
            "disk": {
                "id": "DISC<1>",
                "label": "Cinema & TV",
                "total_files": 0,
                "video_files": 0,
                "audio_files": 0,
                "image_files": 0,
                "other_files": 0,
            },
            "files": [],
        }

        document = render_html([catalog])

        self.assertIn("jquery-3.7.1.min.js", document)
        self.assertIn("jquery.dataTables.min.js", document)
        self.assertIn("DISC&lt;1&gt;", document)
        self.assertIn("Cinema &amp; TV", document)
        self.assertNotIn("DISC<1>", document)
        self.assertNotIn("<th>Modificato</th>", document)


if __name__ == "__main__":
    unittest.main()
