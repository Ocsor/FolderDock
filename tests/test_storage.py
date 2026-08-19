import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from foldershortcuts.models import FolderShortcut
from foldershortcuts.storage import Storage


class StorageTests(unittest.TestCase):
    def test_round_trip_shortcuts_and_settings(self) -> None:
        with TemporaryDirectory() as directory:
            storage = Storage(Path(directory))
            expected = [FolderShortcut("Job", r"\\SERVER\Jobs\123")]
            storage.save_shortcuts(expected)
            storage.save_settings({"geometry": "680x520", "always_on_top": True})
            self.assertEqual(storage.load_shortcuts(), expected)
            self.assertTrue(storage.load_settings()["always_on_top"])

    def test_malformed_json_returns_empty_list(self) -> None:
        with TemporaryDirectory() as directory:
            storage = Storage(Path(directory))
            storage.shortcuts_file.write_text("not json", encoding="utf-8")
            self.assertEqual(storage.load_shortcuts(), [])
            self.assertEqual(storage.shortcuts_file.read_text(encoding="utf-8"), "not json")

    def test_invalid_records_are_skipped(self) -> None:
        with TemporaryDirectory() as directory:
            storage = Storage(Path(directory))
            storage.shortcuts_file.write_text(
                json.dumps([{"name": "Good", "path": "C:/Work"}, {"bad": True}]),
                encoding="utf-8",
            )
            self.assertEqual(storage.load_shortcuts(), [FolderShortcut("Good", "C:/Work")])


if __name__ == "__main__":
    unittest.main()
