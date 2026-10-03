import asyncio
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import display_core
import main


STOCK_FRAGMENT = Path("/usr/lib/systemd/user/gamescope-session.service")


def make_edid(name="Office", serial=1):
    block = bytearray(128)
    block[:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    block[8:10] = b"\x10\xac"
    block[10:12] = b"\x34\x12"
    block[12:16] = serial.to_bytes(4, "little")
    block[18:20] = b"\x01\x04"
    block[54:59] = b"\x00\x00\x00\xfc\x00"
    block[59:72] = (name.encode("ascii") + b"\n").ljust(13, b" ")[:13]
    block[127] = (-sum(block)) % 256
    return bytes(block)


class SessionModel:
    """Model compositor and manager facts separately, including zero-exit false success."""
    def __init__(self, plugin, stock):
        self.plugin = plugin
        self.stock = stock
        self.argv = [str(stock)]
        self.invocation = "initial-session"
        self.active = "DP-7"
        self.service_active = "active"
        self.target_active = "active"
        self.needs_reload = "no"
        self.restart_outcome = "success"
        self.control_outcome = "success"
        self.calls = []
        self.restart_count = 0
        self.foreign_after_reload = False
        self.entered = None
        self.release = None
        self.before_restart = None

    async def __call__(self, argv, environment, timeout):
        self.calls.append((list(argv), dict(environment), timeout))
        if argv == ["gamescopectl"]:
            if self.control_outcome == "missing":
                raise FileNotFoundError("gamescopectl")
            if self.control_outcome == "failed":
                return subprocess.CompletedProcess(argv, 1, "", "No Gamescope interfaces")
            if self.control_outcome == "protocol-missing":
                output = "gamescope_control info:\n  Features:\n"
            elif self.control_outcome == "duplicate":
                output = "  - Connector Name: DP-7\n  - Connector Name: HDMI-A-12\n"
            else:
                output = f"gamescope_control info:\n  - Connector Name: {self.active}\n  - Display Make: Any Vendor\n"
            return subprocess.CompletedProcess(argv, 0, output, "")
        if argv[:3] == ["systemctl", "--user", "daemon-reload"]:
            self.needs_reload = "no"
            if self.plugin.dropin.exists():
                self.argv = self.plugin._arguments(self.stock)
                if self.foreign_after_reload:
                    self.argv = ["/foreign/session"]
            else:
                self.argv = [str(self.stock)]
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv == ["systemctl", "--user", "restart", main.TARGET]:
            self.restart_count += 1
            if self.before_restart:
                self.before_restart()
            if self.entered:
                self.entered.set()
                await self.release.wait()
            if self.restart_outcome == "command-failed":
                return subprocess.CompletedProcess(argv, 1, "", "restart refused")
            if self.restart_outcome != "unchanged-invocation":
                self.invocation = "new-session"
            if self.restart_outcome == "success":
                selected = display_core.select_display(
                    display_core.discover_displays(self.plugin.drm_root)[0],
                    display_core.load_preference(self.plugin.settings_path),
                )
                self.active = display_core.connector_name(selected["connector"])
            if self.restart_outcome == "unloaded-config":
                self.needs_reload = "yes"
            if self.restart_outcome == "wrong-exec":
                self.argv = ["/foreign/session"]
            if self.restart_outcome == "inactive-service":
                self.service_active = "failed"
            if self.restart_outcome == "inactive-target":
                self.target_active = "inactive"
            if self.restart_outcome == "missing-protocol":
                self.control_outcome = "protocol-missing"
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[:3] == ["systemctl", "--user", "show"]:
            is_target = argv[3] == main.TARGET
            values = {
                "FragmentPath": str(STOCK_FRAGMENT), "LoadState": "loaded",
                "ActiveState": self.target_active if is_target else self.service_active,
                "InvocationID": "" if is_target else self.invocation,
                "NeedDaemonReload": self.needs_reload,
                "ExecStart": "" if is_target else
                    f"{{ path={self.argv[0]} ; argv[]={' '.join(self.argv)} ; ignore_errors=no ; start_time=[] ; pid=1 ; }}",
            }
            return subprocess.CompletedProcess(argv, 0, "\n".join(f"{key}={value}" for key, value in values.items()), "")
        raise AssertionError(f"Unexpected command: {argv}")


class BackendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.drm = self.root / "drm"
        self.drm.mkdir()
        self.plugin_dir = self.root / "plugin"
        (self.plugin_dir / "bin").mkdir(parents=True)
        for member in ("session.py", "display_core.py", "bin/gamescope"):
            (self.plugin_dir / member).write_text("# fixture\n", encoding="utf-8")
        self.stock = self.root / "stock-session"
        self.stock.write_text("#!/bin/bash\nexport OTHER=value\nexec gamescope \\\n -O '*',eDP-1 \\\n -- steam\n", encoding="utf-8")
        self.stock.chmod(0o755)
        self.fragment = "[Service]\nType=notify\nNotifyAccess=all\nExecStart=" + str(self.stock) + "\n"
        self.plugin = main.Plugin(home=self.home, drm_root=self.drm, plugin_dir=self.plugin_dir)
        self.model = SessionModel(self.plugin, self.stock)
        self.plugin.runner = self.model
        self.plugin._verification_seconds = 0
        self.add_display("card0-DP-7", "Office", 1, enabled=True)
        self.add_display("card0-HDMI-A-12", "Projector", 2, enabled=False)
        self.real_read_text = Path.read_text

        def read_text(path, *args, **kwargs):
            if path == STOCK_FRAGMENT:
                return self.fragment
            if path == Path("/run/user/1000/gamescope-environment"):
                if hasattr(self, "session_environment"):
                    return self.session_environment
                raise FileNotFoundError(path)
            return self.real_read_text(path, *args, **kwargs)

        patches = [
            patch("main.os.geteuid", return_value=1000), patch("main.os.getuid", return_value=1000),
            patch("main.pwd.getpwuid", return_value=SimpleNamespace(pw_uid=1000, pw_name="deck")),
            patch("main.pwd.getpwnam", return_value=SimpleNamespace(pw_uid=1000, pw_name="deck")),
            patch("main.shutil.which", side_effect=lambda name, **kwargs: "/usr/bin/" + name),
            patch.object(Path, "read_text", read_text),
        ]
        for mock in patches:
            mock.start()
            self.addCleanup(mock.stop)

    def add_display(self, connector, name, serial, connected=True, enabled=False):
        directory = self.drm / connector
        directory.mkdir()
        (directory / "status").write_text("connected" if connected else "disconnected")
        (directory / "enabled").write_text("enabled" if enabled else "disabled")
        (directory / "modes").write_text("1920x1080\n1280x720\n")
        (directory / "edid").write_bytes(make_edid(name, serial))
        return directory

    def display(self, connector):
        return next(row for row in display_core.discover_displays(self.drm)[0] if row["connector"] == connector)

    async def test_setup_installs_scriptless_integration_without_restarting(self):
        original = self.stock.read_bytes()
        await self.plugin._main()
        snapshot = await self.plugin.get_displays()
        self.assertTrue(snapshot["integration_ready"])
        self.assertEqual(self.model.restart_count, 0)
        self.assertEqual(self.stock.read_bytes(), original)
        self.assertTrue(os.access(self.plugin_dir / "bin/gamescope", os.X_OK))
        self.assertEqual(snapshot["active_connector"], "card0-DP-7")

    async def test_only_gamescope_protocol_marks_active_not_enabled_or_preferred(self):
        await self.plugin._main()
        display_core.save_preference(self.plugin.settings_path, self.display("card0-DP-7"))
        self.model.active = "HDMI-A-12"
        snapshot = await self.plugin.get_displays()
        active = next(row for row in snapshot["displays"] if row["active"])
        preferred = next(row for row in snapshot["displays"] if row["preferred"])
        self.assertEqual(active["connector"], "card0-HDMI-A-12")
        self.assertFalse(active["enabled"])
        self.assertEqual(preferred["connector"], "card0-DP-7")
        self.assertEqual(snapshot["active_source"], "gamescopectl")

    async def test_unknown_output_does_not_change_ready_or_guess_active(self):
        await self.plugin._main()
        for outcome in ("missing", "failed", "protocol-missing", "duplicate"):
            with self.subTest(outcome=outcome):
                self.model.control_outcome = outcome
                snapshot = await self.plugin.get_displays()
                self.assertTrue(snapshot["integration_ready"])
                self.assertIsNone(snapshot["active_connector"])
                self.assertIsNone(snapshot["active_source"])
                self.assertFalse(any(row["active"] for row in snapshot["displays"]))
                self.assertIsNotNone(snapshot["error"])

    async def test_active_connector_must_match_unique_connected_sink(self):
        await self.plugin._main()
        self.add_display("card1-DP-7", "Second GPU", 3)
        snapshot = await self.plugin.get_displays()
        self.assertIsNone(snapshot["active_connector"])
        (self.drm / "card1-DP-7/status").write_text("disconnected")
        snapshot = await self.plugin.get_displays()
        self.assertEqual(snapshot["active_connector"], "card0-DP-7")
        self.model.active = "HDMI-A-99"
        self.assertIsNone((await self.plugin.get_displays())["active_connector"])

    async def test_active_selection_saves_preference_without_restart(self):
        chosen = self.display("card0-DP-7")
        result = await self.plugin.switch_display(chosen["id"])
        self.assertEqual(result, {"ok": True, "error": None})
        self.assertEqual(self.model.restart_count, 0)
        self.assertEqual(display_core.load_preference(self.plugin.settings_path),
                         {key: chosen[key] for key in ("identity", "connector", "name")})

    async def test_arbitrary_monitor_selection_persists_before_verified_restart(self):
        chosen = self.display("card0-HDMI-A-12")
        seen_preferences = []
        self.model.before_restart = lambda: seen_preferences.append(display_core.load_preference(self.plugin.settings_path))
        result = await self.plugin.switch_display(chosen["id"])
        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(self.model.restart_count, 1)
        self.assertEqual(seen_preferences, [{key: chosen[key] for key in ("identity", "connector", "name")}])
        self.assertEqual((await self.plugin.get_displays())["active_connector"], chosen["connector"])

    async def test_stale_disconnected_and_invalid_selection_never_restart_or_persist(self):
        chosen = self.display("card0-HDMI-A-12")
        (self.drm / "card0-HDMI-A-12/edid").write_bytes(make_edid("Replacement", 9))
        self.assertFalse((await self.plugin.switch_display(chosen["id"]))["ok"])
        replacement = self.display("card0-HDMI-A-12")
        (self.drm / "card0-HDMI-A-12/status").write_text("disconnected")
        self.assertFalse((await self.plugin.switch_display(replacement["id"]))["ok"])
        for invalid in ("", None, 17, "not-a-display"):
            self.assertFalse((await self.plugin.switch_display(invalid))["ok"])
        self.assertEqual(self.model.restart_count, 0)
        self.assertFalse(self.plugin.settings_path.exists())

    async def test_selection_revalidated_after_async_setup(self):
        chosen = self.display("card0-HDMI-A-12")
        original_runner = self.model.__call__

        async def runner(argv, environment, timeout):
            output = await original_runner(argv, environment, timeout)
            if argv[:3] == ["systemctl", "--user", "daemon-reload"]:
                (self.drm / "card0-HDMI-A-12/status").write_text("disconnected")
            return output

        self.plugin.runner = runner
        result = await self.plugin.switch_display(chosen["id"])
        self.assertFalse(result["ok"])
        self.assertEqual(self.model.restart_count, 0)
        self.assertFalse(self.plugin.settings_path.exists())

    async def test_foreign_dropin_and_symlink_never_overwritten_or_uninstalled(self):
        self.plugin.dropin.parent.mkdir(parents=True)
        foreign = "[Service]\nEnvironment=USER_CONTENT=preserve\n"
        self.plugin.dropin.write_text(foreign)
        await self.plugin._main()
        self.assertFalse((await self.plugin.get_displays())["integration_ready"])
        await self.plugin._uninstall()
        self.assertEqual(self.plugin.dropin.read_text(), foreign)
        self.plugin.dropin.unlink()
        destination = self.root / "foreign"
        destination.write_text(foreign)
        self.plugin.dropin.symlink_to(destination)
        await self.plugin._main()
        await self.plugin._uninstall()
        self.assertTrue(self.plugin.dropin.is_symlink())
        self.assertEqual(destination.read_text(), foreign)
        self.assertEqual(self.model.restart_count, 0)

    async def test_unload_retains_owned_dropin_uninstall_removes_only_unchanged_owned_file(self):
        other = self.plugin.dropin.parent / "50-user-settings.conf"
        other.parent.mkdir(parents=True)
        other.write_text("[Service]\nEnvironment=USER_OPTION=keep\n")
        await self.plugin._main()
        content = self.plugin.dropin.read_text()
        await self.plugin._unload()
        self.assertEqual(self.plugin.dropin.read_text(), content)
        await self.plugin._uninstall()
        self.assertFalse(self.plugin.dropin.exists())
        self.assertEqual(other.read_text(), "[Service]\nEnvironment=USER_OPTION=keep\n")
        self.assertEqual(self.model.restart_count, 0)

    async def test_modified_owned_file_survives_uninstall(self):
        await self.plugin._main()
        content = self.plugin.dropin.read_text() + "# user modification\n"
        self.plugin.dropin.write_text(content)
        await self.plugin._uninstall()
        self.assertEqual(self.plugin.dropin.read_text(), content)

    async def test_foreign_exec_override_preserved_even_without_managed_dropin(self):
        self.model.argv = ["/foreign/session"]
        await self.plugin._main()
        snapshot = await self.plugin.get_displays()
        self.assertFalse(snapshot["integration_ready"])
        self.assertEqual(snapshot["active_connector"], "card0-DP-7")
        self.assertFalse(self.plugin.dropin.exists())
        self.assertEqual(self.model.argv, ["/foreign/session"])

    async def test_later_override_rejected_after_reload_without_restart(self):
        self.model.foreign_after_reload = True
        result = await self.plugin.switch_display(self.display("card0-HDMI-A-12")["id"])
        self.assertFalse(result["ok"])
        self.assertEqual(self.model.restart_count, 0)

    async def test_unsupported_stock_formats_leave_discovery_available(self):
        unsupported = [
            "[Service]\nExecStart=/bin/bash -c gamescope\n",
            "[Service]\nExecStart=\nExecStart=" + str(self.stock) + "\n",
            "[Service]\nExecStart=%h/session\n",
        ]
        for fragment in unsupported:
            with self.subTest(fragment=fragment):
                self.fragment = fragment
                await self.plugin._main()
                snapshot = await self.plugin.get_displays()
                self.assertFalse(snapshot["integration_ready"])
                self.assertEqual({row["connector"] for row in snapshot["displays"]},
                                 {"card0-DP-7", "card0-HDMI-A-12"})
                self.assertFalse(self.plugin.dropin.exists())
        self.fragment = "[Service]\nExecStart=" + str(self.stock) + "\n"
        for script in ("#!/bin/bash\nexec /usr/bin/gamescope -O '*'\n",
                       "#!/bin/bash\nPATH=/usr/bin\nexec gamescope\n"):
            self.stock.write_text(script)
            await self.plugin._main()
            self.assertFalse((await self.plugin.get_displays())["integration_ready"])
            self.assertFalse(self.plugin.dropin.exists())

    async def test_root_wrong_user_and_unreachable_bus_fail_without_live_changes(self):
        chosen = self.display("card0-HDMI-A-12")["id"]
        with patch("main.os.geteuid", return_value=0):
            result = await self.plugin.switch_display(chosen)
            self.assertFalse(result["ok"])
            snapshot = await self.plugin.get_displays()
            self.assertFalse(snapshot["integration_ready"])
        with patch("main.pwd.getpwuid", return_value=SimpleNamespace(pw_uid=1001, pw_name="other")), \
             patch("main.pwd.getpwnam", return_value=SimpleNamespace(pw_uid=1001, pw_name="other")):
            self.assertFalse((await self.plugin.switch_display(chosen))["ok"])

        async def failed_bus(argv, environment, timeout):
            return subprocess.CompletedProcess(argv, 1, "", "Failed to connect to bus")

        self.plugin.runner = failed_bus
        self.assertFalse((await self.plugin.switch_display(chosen))["ok"])
        self.assertFalse(self.plugin.dropin.exists())
        self.assertEqual(self.model.restart_count, 0)

    async def test_own_user_bus_and_exact_gamescope_environment_key(self):
        self.session_environment = "SECRET=value\nNOT_GAMESCOPE_WAYLAND_DISPLAY=wrong\nexport GAMESCOPE_WAYLAND_DISPLAY='gamescope-3'\n"
        await self.plugin.get_displays()
        environment = next(call[1] for call in self.model.calls if call[0] == ["gamescopectl"])
        self.assertEqual(environment["DBUS_SESSION_BUS_ADDRESS"], "unix:path=/run/user/1000/bus")
        self.assertEqual(environment["XDG_RUNTIME_DIR"], "/run/user/1000")
        self.assertEqual(environment["GAMESCOPE_WAYLAND_DISPLAY"], "gamescope-3")
        self.assertNotIn("SECRET", environment)

    async def test_restart_zero_exit_is_not_success_without_every_runtime_fact(self):
        await self.plugin._main()
        chosen = self.display("card0-HDMI-A-12")
        for outcome in ("unchanged-invocation", "wrong-output", "unloaded-config", "wrong-exec",
                        "inactive-service", "inactive-target", "missing-protocol", "command-failed"):
            with self.subTest(outcome=outcome):
                self.model.argv = self.plugin._arguments(self.stock)
                self.model.invocation = "initial-session"
                self.model.active = "DP-7"
                self.model.needs_reload = "no"
                self.model.service_active = self.model.target_active = "active"
                self.model.control_outcome = "success"
                self.model.restart_outcome = outcome
                result = await self.plugin.switch_display(chosen["id"])
                self.assertFalse(result["ok"], outcome)
                self.assertIsNotNone(result["error"])

    async def test_unknown_current_output_never_causes_blind_restart(self):
        await self.plugin._main()
        self.model.control_outcome = "protocol-missing"
        result = await self.plugin.switch_display(self.display("card0-HDMI-A-12")["id"])
        self.assertFalse(result["ok"])
        self.assertEqual(self.model.restart_count, 0)
        self.assertFalse(self.plugin.settings_path.exists())

    async def test_concurrent_switch_rejected_and_unload_cancels_pending_task(self):
        await self.plugin._main()
        self.model.entered = asyncio.Event()
        self.model.release = asyncio.Event()
        chosen = self.display("card0-HDMI-A-12")["id"]
        task = asyncio.create_task(self.plugin.switch_display(chosen))
        await asyncio.wait_for(self.model.entered.wait(), 1)
        self.assertTrue((await self.plugin.get_displays())["switching"])
        competing = await self.plugin.switch_display(chosen)
        self.assertFalse(competing["ok"])
        await self.plugin._unload()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.model.restart_count, 1)
        self.assertTrue(self.plugin.dropin.exists())
        self.assertFalse((await self.plugin.get_displays())["switching"])
        self.assertFalse((await self.plugin.switch_display(chosen))["ok"])

    async def test_corrupt_preference_is_visible_and_not_a_guessed_preference(self):
        await self.plugin._main()
        self.plugin.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.plugin.settings_path.write_text('{"version": 1, "preferred": "invalid"}')
        snapshot = await self.plugin.get_displays()
        self.assertIsNone(snapshot["preferred"])
        self.assertFalse(any(row["preferred"] for row in snapshot["displays"]))
        self.assertIsNotNone(snapshot["error"])

    async def test_missing_edid_can_persist_connector_fallback(self):
        (self.drm / "card0-DP-7/edid").unlink()
        selected = self.display("card0-DP-7")
        self.assertEqual(selected["identity_source"], "connector")
        result = await self.plugin.switch_display(selected["id"])
        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(display_core.load_preference(self.plugin.settings_path)["identity"], selected["identity"])
        self.assertEqual(self.model.restart_count, 0)

    async def test_missing_capability_or_packaged_file_cannot_install_or_restart(self):
        selected = self.display("card0-HDMI-A-12")["id"]
        with patch("main.shutil.which", side_effect=lambda name, **kwargs: None if name == "gamescope" else "/usr/bin/" + name):
            result = await self.plugin.switch_display(selected)
            self.assertFalse(result["ok"])
        (self.plugin_dir / "session.py").unlink()
        result = await self.plugin.switch_display(selected)
        self.assertFalse(result["ok"])
        self.assertFalse(self.plugin.dropin.exists())
        self.assertEqual(self.model.restart_count, 0)

    async def test_unload_cancels_pending_setup_without_removing_integration(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        original = self.model.__call__

        async def runner(argv, environment, timeout):
            if argv[:3] == ["systemctl", "--user", "daemon-reload"]:
                entered.set()
                await release.wait()
            return await original(argv, environment, timeout)

        self.plugin.runner = runner
        setup = asyncio.create_task(self.plugin._main())
        await asyncio.wait_for(entered.wait(), 1)
        await self.plugin._unload()
        with self.assertRaises(asyncio.CancelledError):
            await setup
        self.assertTrue(self.plugin.dropin.exists())
        self.assertEqual(self.model.restart_count, 0)



if __name__ == "__main__":
    unittest.main()
