import unittest

from foldershortcuts.models import FolderShortcut, default_shortcut_name


class FolderShortcutTests(unittest.TestCase):
    def test_default_name_for_unc_path(self) -> None:
        self.assertEqual(default_shortcut_name(r"\\SERVER\Jobs\Citadel Sign"), "Citadel Sign")

    def test_invalid_dictionary_is_ignored(self) -> None:
        self.assertIsNone(FolderShortcut.from_dict({"name": "Missing path"}))

    def test_existing_json_defaults_to_active(self) -> None:
        shortcut = FolderShortcut.from_dict({"name": "Old entry", "path": r"C:\Work"})
        self.assertIsNotNone(shortcut)
        self.assertFalse(shortcut.archived)

    def test_archive_state_round_trips(self) -> None:
        shortcut = FolderShortcut("Archived", r"C:\Old", archived=True)
        self.assertEqual(FolderShortcut.from_dict(shortcut.to_dict()), shortcut)

    def test_client_state_round_trips(self) -> None:
        shortcut = FolderShortcut("Client", r"C:\Clients\Example", tab="Clients")
        self.assertEqual(FolderShortcut.from_dict(shortcut.to_dict()), shortcut)

    def test_legacy_client_flag_migrates_to_named_tab(self) -> None:
        shortcut = FolderShortcut.from_dict(
            {"name": "Client", "path": r"C:\Clients\Example", "client": True}
        )
        self.assertIsNotNone(shortcut)
        self.assertEqual(shortcut.tab, "Clients")


if __name__ == "__main__":
    unittest.main()
