# Official references

- [Decky plugin template](https://github.com/SteamDeckHomebrew/decky-plugin-template): modern callable API, plugin manifest, Rollup configuration and distribution ZIP layout.
- [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader): user installation and plugin lifecycle.
- [Decky backend runtime constants](https://github.com/SteamDeckHomebrew/decky-loader/blob/main/backend/decky_loader/plugin/imports/decky.py): `DECKY_USER_HOME`, `DECKY_USER`, plugin settings and runtime paths.
- [Decky sandbox](https://github.com/SteamDeckHomebrew/decky-loader/blob/main/backend/decky_loader/plugin/sandboxed_plugin.py): API 1 instance lifecycle and unprivileged execution.
- [Decky installer](https://github.com/SteamDeckHomebrew/decky-loader/blob/main/backend/decky_loader/browser.py): ZIP installation, ownership and confirmation.
- [Decky UI](https://github.com/SteamDeckHomebrew/decky-frontend-lib): native QAM components and controller navigation.
- [Linux DRM sysfs implementation](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/drm_sysfs.c): `status`, `enabled`, `edid` and advertised `modes` semantics.
- [Linux DRM EDID parser](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/drm_edid.c): HDMI HF-EEODB in the first CTA extension overrides the base extension count, including smaller counts.
- [Gamescope command-line source](https://github.com/ValveSoftware/gamescope/blob/master/src/main.cpp): `-O` / `--prefer-output` orders connector preferences; it is not itself a live output-change API.
- [Gamescope control protocol](https://github.com/ValveSoftware/gamescope/blob/master/protocol/gamescope-control.xml): authoritative `active_display_info` event, available since protocol version 2.
- [gamescopectl source](https://github.com/ValveSoftware/gamescope/blob/master/src/Apps/gamescopectl.cpp): invoke without arguments for read-only active-output information; arguments execute compositor commands and must not be used for discovery.
- [systemctl manual](https://www.freedesktop.org/software/systemd/man/latest/systemctl.html): user manager, machine-readable properties, daemon reload and target restart.
- [systemd execution environment](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html): service execution and environment.
- [systemd service execution](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html#ExecStart=): `ExecStart` replacement, argument quoting and notification behavior.
- [Python on Unix](https://docs.python.org/3/using/unix.html#miscellaneous): executable scripts and portable `#!/usr/bin/env python3` shebang.
- [PyInstaller external-program guidance](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#launching-external-programs-from-the-frozen-application): restore `LD_LIBRARY_PATH_ORIG` or clear bundled library paths for system subprocesses without modifying the frozen parent's environment.
- [LGPL 2.1, sections 4–6](https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html): matching source, license notices and rebuilding with a modified library.
- [Decky API 1.1.3 source](https://github.com/SteamDeckHomebrew/loader-api/tree/d1b7f16070777a0ada939cbacd3606eeba0574f5): vendored matching library source and upstream build inputs.
- [Decky template BSD notice](https://github.com/SteamDeckHomebrew/decky-plugin-template/blob/4ab713585dbe77baefa83c3a2fa57cb1872be1f4/LICENSE): retained original copyright and redistribution terms.
- [React Icons 5.3.0](https://github.com/react-icons/react-icons/tree/6188fc096b4d2b4d80d1701aa694889ce7aa71f6): icon helpers, licenses and icon-pack revision manifest.
- [Font Awesome icon source and license](https://github.com/FortAwesome/Font-Awesome/tree/afecf2af5d897b763e5e8e28d46aad2f710ccad6): matching desktop icon geometry and attribution.
- [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/legalcode.en): attribution and indication of changes for the icon.
- [Rollup resolveId](https://rollupjs.org/plugin-development/#resolveid): resolve the API import to the supplied TypeScript source.
- [TypeScript paths](https://www.typescriptlang.org/tsconfig/paths.html): use the same API source for type checking.
- [TypeScript rootDir](https://www.typescriptlang.org/tsconfig/rootDir.html): compile application and vendored API source with one explicit source root.
- [pnpm install](https://pnpm.io/cli/install): frozen lockfiles and installation without lifecycle scripts.

The installed stock SteamOS session script and stock user service were inspected
before implementation. The supported adapter retains that session script and
intercepts its unqualified `exec gamescope` using a PATH shim. It does not modify
`/usr` or guess support for unrelated session managers.

