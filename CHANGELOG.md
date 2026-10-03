# Changelog

## 2.0.3 — 2026-10-04

- Include third-party licenses and Font Awesome attribution in releases.
- Ship matching Decky API and plugin sources for rebuilding with a modified library.
- Add an English README with a SteamOS screenshot.

## 2.0.2 — 2026-10-03

- Move the restart warning into the monitor section and name “Hierher wechseln” explicitly.

## 2.0.1 — 2026-10-03

- Restore the system library path when launching external commands from Decky.
- Handle HDMI HF-EEODB extension-count overrides when validating EDID.

## 2.0.0 — 2026-10-03

- Replace fixed Samsung/TV profiles with generic DRM monitor selection.
- Save EDID-based monitor preferences, with a connector fallback when EDID is unavailable.
- Use a connected output at startup if the preferred monitor is missing, without changing the saved preference.
- Detect Gamescope's active output and disable its switch button.
- Add collapsible technical details.
- Manage session startup through a user-service drop-in; preserve external overrides during setup and uninstall.
- Check the new session and requested output after switching.

## 1.1.0 — 2026-10-03

- Show the maximum advertised resolution instead of a mode list.
- Switch immediately without a confirmation dialog; retain the restart warning.

## 1.0.0 — 2026-10-03

- Switch between existing Samsung/TV Gamescope profiles from Decky.
- Show DRM connectors, EDID names, connection state and advertised resolutions.
- Ask for confirmation before restarting the gaming session.
- Reject stale selections, disconnected displays and concurrent switches.
- Package the plugin as a Decky-installable ZIP.
