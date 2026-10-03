import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import display_core as core


def make_edid(name="Monitor", serial=42, product=7, serial_text=None):
    block = bytearray(128)
    block[:8] = core.EDID_HEADER
    block[8:10] = ((1 << 10) | (2 << 5) | 3).to_bytes(2, "big")
    block[10:12] = product.to_bytes(2, "little")
    block[12:16] = serial.to_bytes(4, "little")
    block[18:20] = bytes((1, 4))
    for offset, kind, text in ((54, 0xFC, name), (72, 0xFF, serial_text)):
        if text is not None:
            block[offset:offset + 5] = bytes((0, 0, 0, kind, 0))
            block[offset + 5:offset + 18] = (text.encode("ascii") + b"\n").ljust(13, b" ")[:13]
    block[127] = -sum(block) % 256
    return bytes(block)


def checksummed(data):
    block = bytearray(data)
    block[127] = 0
    block[127] = -sum(block[:128]) % 256
    return bytes(block)


def make_override_edid(base_count=1, override_count=2):
    base = bytearray(make_edid())
    base[126] = base_count
    cta = bytearray(128)
    cta[:3] = bytes((0x02, 3, 7))
    cta[4:7] = bytes((0xE2, 0x78, override_count))
    return checksummed(base) + checksummed(cta) + bytes(128 * (override_count - 1))


def connector(root, name, edid=b"", connected=True, enabled=False):
    path = root / name
    path.mkdir(exist_ok=True)
    (path / "status").write_text("connected" if connected else "disconnected")
    (path / "enabled").write_text("enabled" if enabled else "disabled")
    (path / "modes").write_text("1920x1080\n1280x720\n1920x1080\n")
    (path / "edid").write_bytes(edid)
    return path


def preference(display):
    return {key: display[key] for key in ("identity", "connector", "name")}


class MonitorSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "drm"
        self.root.mkdir()
        self.settings = Path(self.temporary.name) / "preferences.json"

    def displays(self):
        displays, errors = core.discover_displays(self.root)
        self.assertEqual(errors, [])
        return displays

    def test_preference_follows_monitor_when_ports_swap(self):
        first = connector(self.root, "card0-DP-1", make_edid(serial=42))
        second = connector(self.root, "card0-HDMI-A-1", make_edid(serial=99), enabled=True)
        original = self.displays()[0]
        core.save_preference(self.settings, original)
        first.joinpath("edid").write_bytes(make_edid(serial=99))
        second.joinpath("edid").write_bytes(make_edid(serial=42))
        selected = core.select_display(self.displays(), core.load_preference(self.settings))
        self.assertEqual(selected["connector"], "card0-HDMI-A-1")
        self.assertEqual(selected["identity"], original["identity"])
        self.assertNotEqual(selected["id"], original["id"])

    def test_missing_preferred_monitor_falls_back_then_returns_without_rewriting(self):
        first = connector(self.root, "card0-DP-1", make_edid(serial=42))
        connector(self.root, "card0-HDMI-A-1", make_edid(serial=99), enabled=True)
        original = self.displays()[0]
        core.save_preference(self.settings, original)
        saved = self.settings.read_bytes()
        first.joinpath("status").write_text("disconnected")
        selected = core.select_display(self.displays(), core.load_preference(self.settings))
        self.assertEqual(selected["connector"], "card0-HDMI-A-1")
        self.assertEqual(self.settings.read_bytes(), saved)
        first.joinpath("status").write_text("connected")
        selected = core.select_display(self.displays(), core.load_preference(self.settings))
        self.assertEqual(selected["connector"], "card0-DP-1")
        self.assertEqual(self.settings.read_bytes(), saved)

    def test_no_preference_uses_sole_enabled_sink_then_deterministic_order(self):
        first = connector(self.root, "card1-DP-2", make_edid(serial=42), enabled=True)
        connector(self.root, "card0-HDMI-A-1", make_edid(serial=99))
        self.assertIsNone(core.load_preference(self.settings))
        self.assertEqual(core.select_display(self.displays(), None)["connector"], "card1-DP-2")
        first.joinpath("enabled").write_text("disabled")
        self.assertEqual(core.select_display(list(reversed(self.displays())), None)["connector"], "card0-HDMI-A-1")

    def test_ambiguous_identity_uses_hint_not_arbitrary_identity_match(self):
        connector(self.root, "card0-DP-1", make_edid(serial=42))
        connector(self.root, "card0-DP-2", make_edid(serial=42))
        connector(self.root, "card0-HDMI-A-1", make_edid(serial=99), enabled=True)
        displays = self.displays()
        preferred = preference(displays[1])
        self.assertEqual(core.select_display(displays, preferred)["connector"], "card0-DP-2")
        preferred["connector"] = "card1-DP-3"
        self.assertEqual(core.select_display(displays, preferred)["connector"], "card0-HDMI-A-1")

    def test_no_edid_preference_is_connector_bound(self):
        connector(self.root, "card0-DP-1")
        connector(self.root, "card0-HDMI-A-1", enabled=True)
        display = self.displays()[0]
        self.assertEqual(display["identity_source"], "connector")
        self.assertEqual(display["identity"], "connector:card0-DP-1")
        self.assertEqual(core.select_display(self.displays(), preference(display))["connector"], "card0-DP-1")

    def test_numeric_and_text_serials_are_stable_but_fingerprint_changes(self):
        for serial, text in ((42, None), (0, "UNIT-42")):
            with self.subTest(serial=serial):
                path = connector(self.root, "card0-DP-1", make_edid("Original", serial, serial_text=text))
                original = self.displays()[0]
                path.joinpath("edid").write_bytes(make_edid("New name", serial, serial_text=text))
                changed = self.displays()[0]
                self.assertEqual(changed["identity"], original["identity"])
                self.assertNotEqual(changed["id"], original["id"])
                self.assertEqual(changed["name"], "New name")

    def test_no_usable_serial_uses_whole_edid_hash(self):
        path = connector(self.root, "card0-DP-1", make_edid(serial=0))
        original = self.displays()[0]
        self.assertTrue(original["identity"].startswith("edid:sha256:"))
        path.joinpath("edid").write_bytes(make_edid("Changed", serial=0))
        self.assertNotEqual(self.displays()[0]["identity"], original["identity"])
        path.joinpath("edid").write_bytes(make_edid(serial=0, serial_text="000000"))
        self.assertTrue(self.displays()[0]["identity"].startswith("edid:sha256:"))

    def test_serial_identity_includes_product(self):
        connector(self.root, "card0-DP-1", make_edid(product=1))
        connector(self.root, "card0-DP-2", make_edid(product=2))
        first, second = self.displays()
        self.assertNotEqual(first["identity"], second["identity"])

    def test_hdmi_override_preserves_monitor_name_and_identity_with_larger_or_smaller_count(self):
        path = connector(self.root, "card0-DP-1", make_edid())
        original = self.displays()[0]
        core.save_preference(self.settings, original)
        for base_count, override_count in ((1, 2), (2, 1)):
            with self.subTest(base=base_count, override=override_count):
                path.joinpath("edid").write_bytes(make_override_edid(base_count, override_count))
                selected = core.select_display(self.displays(), core.load_preference(self.settings))
                self.assertEqual(selected["identity"], original["identity"])
                self.assertEqual(selected["name"], original["name"])

    def test_hdmi_override_cannot_hide_missing_corrupt_or_malformed_blocks(self):
        valid = make_override_edid()
        corrupt = bytearray(valid)
        corrupt[-1] ^= 1
        invalid_edids = [valid[:-128], valid + bytes(128), bytes(corrupt)]
        for offset, value in ((0, 0x70), (1, 2), (2, 6), (4, 0xE1), (5, 0x79), (6, 0)):
            cta = bytearray(valid[128:256])
            cta[offset] = value
            invalid_edids.append(valid[:128] + checksummed(cta) + valid[256:])
        for invalid in invalid_edids:
            with self.subTest(edid=invalid[128:135]):
                connector(self.root, "card0-DP-1", invalid)
                displays, _ = core.discover_displays(self.root)
                self.assertEqual(displays[0]["identity_source"], "connector")
                self.assertEqual(displays[0]["name"], "card0-DP-1")

    def test_corrupt_edids_never_provide_monitor_identity_or_name(self):
        valid = make_edid()
        checksum_bad = bytearray(valid)
        checksum_bad[12] ^= 1
        manufacturer_bad = bytearray(valid)
        manufacturer_bad[8:10] = b"\x00\x00"
        extension_missing = bytearray(valid)
        extension_missing[126] = 1
        extension_bad = checksummed(extension_missing) + bytes([1]) + bytes(127)
        for invalid in (valid[:127], bytes(checksum_bad), checksummed(manufacturer_bad),
                        checksummed(extension_missing), extension_bad, b"not an EDID"):
            with self.subTest(edid=invalid[:16]):
                connector(self.root, "card0-DP-1", invalid)
                displays, errors = core.discover_displays(self.root)
                self.assertEqual(displays[0]["identity_source"], "connector")
                self.assertEqual(displays[0]["name"], "card0-DP-1")

    def test_disconnected_and_writeback_never_become_selected(self):
        connector(self.root, "card0-DP-1", make_edid(), connected=False, enabled=True)
        connector(self.root, "card0-Writeback-1", make_edid(), enabled=True)
        displays = self.displays()
        self.assertEqual([display["connector"] for display in displays], ["card0-DP-1"])
        self.assertEqual(displays[0]["modes"], ["1920x1080", "1280x720"])
        self.assertIsNone(core.select_display(displays, preference(displays[0])))

    def test_corrupt_preferences_are_explicit_errors(self):
        for invalid in ('{', 'null', '[]', '{"version":2,"preferred":{}}',
                        '{"version":true,"preferred":{}}',
                        '{"version":1,"preferred":null}',
                        '{"version":1,"preferred":{"identity":12,"connector":"card0-DP-1","name":"Monitor"}}',
                        '{"version":1,"preferred":{"identity":"x","connector":"--bad","name":"Monitor"}}'):
            with self.subTest(settings=invalid):
                self.settings.write_text(invalid)
                with self.assertRaises(ValueError):
                    core.load_preference(self.settings)

    def test_failed_atomic_replacement_preserves_last_preference(self):
        connector(self.root, "card0-DP-1", make_edid(serial=42))
        connector(self.root, "card0-DP-2", make_edid(serial=99))
        first, second = self.displays()
        core.save_preference(self.settings, first)
        with patch.object(core.os, "replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                core.save_preference(self.settings, second)
        self.assertEqual(core.load_preference(self.settings), preference(first))
        self.assertEqual(list(self.settings.parent.glob(".preferences.json.*")), [])
        self.assertEqual(json.loads(self.settings.read_text())["version"], 1)


class GamescopeArgumentsTests(unittest.TestCase):
    def test_all_preference_forms_are_replaced_and_child_arguments_are_untouched(self):
        original = ["-e", "-O", "DP-1", "-OHDMI-A-1", "--prefer-output", "DP-2",
                    "--prefer-output=DP-3", "--hdr-enabled", "--", "game", "-O", "child",
                    "--prefer-output=child-value", "--", "-Ochild"]
        self.assertEqual(core.gamescope_arguments(original, {"connector": "card12-HDMI-A-2"}),
                         ["-e", "--hdr-enabled", "-O", "HDMI-A-2,*,eDP-1", "--", "game",
                          "-O", "child", "--prefer-output=child-value", "--", "-Ochild"])

    def test_no_selected_monitor_uses_stock_wildcard_preference(self):
        self.assertEqual(core.gamescope_arguments(["-W", "1920"], None), ["-W", "1920", "-O", "*,eDP-1"])
        self.assertEqual(core.gamescope_arguments(["--", "game"], None), ["-O", "*,eDP-1", "--", "game"])

    def test_option_values_are_not_misinterpreted_as_output_flags(self):
        self.assertEqual(core.gamescope_arguments(["--cursor", "-Office", "-T", "--prefer-output=file"], None),
                         ["--cursor", "-Office", "-T", "--prefer-output=file", "-O", "*,eDP-1"])

    def test_separator_used_as_an_option_value_does_not_start_child_arguments(self):
        self.assertEqual(
            core.gamescope_arguments(["--cursor", "--", "-O", "DP-1", "--", "game", "-O", "child"], None),
            ["--cursor", "--", "-O", "*,eDP-1", "--", "game", "-O", "child"],
        )

    def test_missing_or_empty_output_values_are_errors(self):
        for arguments in (["-O"], ["--prefer-output"], ["-O", "--", "game"],
                          ["--prefer-output="], ["-O", ""], ["-O", "--hdr-enabled"]):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                core.gamescope_arguments(arguments, None)

    def test_invalid_selected_connector_cannot_enter_preference_list(self):
        for connector in ("DP-1", "card0-DP-1,DP-2", "card0-DP-1\n", "card0-Writeback-1"):
            with self.subTest(connector=connector), self.assertRaises(ValueError):
                core.gamescope_arguments([], {"connector": connector})


if __name__ == "__main__":
    unittest.main()
