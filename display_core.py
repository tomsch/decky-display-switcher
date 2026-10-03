"""Monitor discovery, saved preferences and Gamescope startup."""

import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path


CONNECTOR = re.compile(r"card\d+-([A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+)")
EDID_HEADER = b"\x00\xff\xff\xff\xff\xff\xff\x00"


def _valid_edid(data: bytes) -> bool:
    if len(data) < 128 or data[:8] != EDID_HEADER or data[18] != 1:
        return False
    extensions = data[126]
    if extensions and len(data) >= 256:
        cta = data[128:256]
        # HF-EEODB overrides the base extension count, as in Linux DRM.
        if (
            cta[0] == 0x02
            and cta[1] >= 3
            and 7 <= cta[2] <= 127
            and cta[4] >> 5 == 7
            and (cta[4] & 0x1F) >= 2
            and cta[5] == 0x78
            and cta[6]
        ):
            extensions = cta[6]
    length = 128 * (1 + extensions)
    if len(data) != length or any(sum(data[n:n + 128]) % 256 for n in range(0, length, 128)):
        return False
    manufacturer = int.from_bytes(data[8:10], "big")
    return not manufacturer & 0x8000 and all(
        1 <= (manufacturer >> shift) & 31 <= 26 for shift in (10, 5, 0)
    )


def _descriptor_text(data: bytes, kind: int) -> str | None:
    for offset in (54, 72, 90, 108):
        descriptor = data[offset:offset + 18]
        if descriptor[:5] != bytes((0, 0, 0, kind, 0)):
            continue
        text = descriptor[5:].split(b"\n", 1)[0].split(b"\x00", 1)[0].strip()
        if text and all(32 <= byte <= 126 for byte in text):
            return text.decode("ascii")
    return None


def edid_name(data: bytes) -> str | None:
    """Read the monitor-name descriptor from a valid EDID."""
    return _descriptor_text(data, 0xFC) if _valid_edid(data) else None


def _identity(data: bytes, connector: str) -> tuple[str, str]:
    if not _valid_edid(data):
        return f"connector:{connector}", "connector"
    # The base serial survives port and EDID extension changes.
    model = data[8:12].hex()
    serial = int.from_bytes(data[12:16], "little")
    if serial not in (0, 0xFFFFFFFF):
        return f"edid:serial:{model}:{serial:08x}", "edid"
    text = _descriptor_text(data, 0xFF)
    if (
        text
        and text.casefold() not in {"unknown", "none", "n/a", "serial number"}
        and text.strip("0 ")
    ):
        digest = hashlib.sha256(text.encode("ascii")).hexdigest()
        return f"edid:serial-text:{model}:{digest}", "edid"
    return f"edid:sha256:{hashlib.sha256(data).hexdigest()}", "edid"


def connector_name(full_name: str) -> str:
    """Convert a DRM sysfs name to the name understood by Gamescope."""
    return re.sub(r"^card\d+-", "", full_name)


def discover_displays(drm_root: Path = Path("/sys/class/drm")) -> tuple[list[dict], list[str]]:
    displays = []
    errors = []
    try:
        entries = sorted(drm_root.iterdir())
    except OSError as exc:
        return [], [f"Cannot read DRM connectors: {exc}"]
    for entry in entries:
        match = CONNECTOR.fullmatch(entry.name)
        if not match or not entry.is_dir() or match.group(1).startswith("Writeback-"):
            continue

        def read_text(filename: str) -> str:
            try:
                return (entry / filename).read_text(encoding="ascii").strip()
            except (OSError, UnicodeError) as exc:
                errors.append(f"{entry.name}/{filename} cannot be read: {exc}")
                return ""

        status = read_text("status")
        enabled = read_text("enabled")
        modes = list(dict.fromkeys(read_text("modes").splitlines()))
        try:
            edid = (entry / "edid").read_bytes()
        except OSError as exc:
            edid = b""
            errors.append(f"{entry.name}/edid cannot be read: {exc}")
        if edid and not _valid_edid(edid):
            errors.append(f"Invalid EDID for {entry.name}; monitor identity is connector-based")
        identity, source = _identity(edid, entry.name)
        displays.append({
            "id": f"{entry.name}:{hashlib.sha256(edid).hexdigest()}",
            "identity": identity, "identity_source": source, "connector": entry.name,
            "name": edid_name(edid) or entry.name, "connected": status == "connected",
            "enabled": enabled == "enabled", "modes": modes,
        })
    return displays, errors


def _preference_fields(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {"identity", "connector", "name"}:
        raise ValueError("Invalid display preference fields")
    if any(not isinstance(value[key], str) or not value[key].strip() or "\x00" in value[key]
           for key in ("identity", "connector", "name")):
        raise ValueError("Display preference fields must be nonempty strings")
    if not CONNECTOR.fullmatch(value["connector"]):
        raise ValueError("Invalid display preference connector")
    return dict(value)


def load_preference(settings_path: Path) -> dict | None:
    try:
        with settings_path.open(encoding="utf-8") as stream:
            settings = json.load(stream)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError(f"Cannot parse display preference: {exc}") from exc
    if (
        not isinstance(settings, dict)
        or set(settings) != {"version", "preferred"}
        or type(settings["version"]) is not int
        or settings["version"] != 1
    ):
        raise ValueError("Unsupported or invalid display preference format")
    return _preference_fields(settings["preferred"])


def save_preference(settings_path: Path, display: dict) -> None:
    preferred = _preference_fields({key: display[key] for key in ("identity", "connector", "name")})
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=settings_path.parent,
                                         prefix=f".{settings_path.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({"version": 1, "preferred": preferred}, stream, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, settings_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def select_display(displays: list[dict], preference: dict | None) -> dict | None:
    connected = sorted((display for display in displays if display["connected"]),
                       key=lambda display: display["connector"])
    if preference:
        matches = [display for display in connected if display["identity"] == preference["identity"]]
        if len(matches) == 1:
            return matches[0]
        hinted = [display for display in matches if display["connector"] == preference["connector"]]
        if len(hinted) == 1:
            return hinted[0]
    enabled = [display for display in connected if display["enabled"]]
    if len(enabled) == 1:
        return enabled[0]
    return connected[0] if connected else None


# Value-taking options from Gamescope main.cpp. Values such as --cursor -Office
# must not be interpreted as output flags.
_LONG_VALUES = frozenset("""
    nested-width nested-height nested-refresh max-scale scaler filter output-width
    output-height sharpness fsr-sharpness prefer-vk-device mouse-sensitivity backend
    nested-unfocused-refresh display-index default-touch-mode generate-drm-mode
    framerate-limit vr-overlay-key vr-app-overlay-key vr-overlay-explicit-name
    vr-overlay-default-name vr-overlay-icon vr-overlay-physical-width
    vr-overlay-physical-curvature vr-overlay-physical-pre-curve-pitch
    xwayland-count cursor cursor-hotspot cursor-scale-height virtual-connector-strategy
    ready-fd stats-path hide-cursor-delay fade-out-duration force-orientation
    sdr-gamut-wideness hdr-sdr-content-nits hdr-itm-sdr-nits hdr-itm-target-nits
    reshade-effect reshade-technique-idx mura-map
""".split())
_SHORT_VALUES = frozenset("whrmSFWHsoRTC")


def gamescope_arguments(argv: list[str], selected: dict | None) -> list[str]:
    """Set output preference without changing child arguments."""
    boundary = len(argv)
    result = []
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--":
            boundary = index
            break
        if argument in ("-O", "--prefer-output"):
            if index + 1 >= len(argv) or not argv[index + 1] or argv[index + 1].startswith("-"):
                raise ValueError(f"Missing connector list after {argument}")
            index += 2
            continue
        if argument.startswith("-O") and len(argument) > 2:
            index += 1
            continue
        if argument.startswith("--prefer-output="):
            if not argument.split("=", 1)[1]:
                raise ValueError("Empty --prefer-output connector list")
            index += 1
            continue
        result.append(argument)
        takes_value = (argument.startswith("--") and argument[2:] in _LONG_VALUES) or (
            len(argument) == 2 and argument[0] == "-" and argument[1] in _SHORT_VALUES)
        if takes_value and index + 1 < len(argv):
            index += 1
            result.append(argv[index])
        index += 1
    output = "*,eDP-1"
    if selected is not None:
        full_name = selected["connector"]
        if not CONNECTOR.fullmatch(full_name) or connector_name(full_name).startswith("Writeback-"):
            raise ValueError("Invalid selected display connector")
        output = f"{connector_name(full_name)},*,eDP-1"
    return result + ["-O", output] + argv[boundary:]


def _real_gamescope() -> tuple[Path, str]:
    shim_directory = (Path(__file__).resolve().parent / "bin").resolve()
    shim = (shim_directory / "gamescope").resolve()
    paths = []
    for item in os.environ.get("PATH", os.defpath).split(os.pathsep):
        directory = Path(item or ".")
        candidate = directory / "gamescope"
        if directory.resolve() == shim_directory:
            continue
        if candidate.is_file() and (candidate.resolve() == shim or candidate.samefile(shim)):
            continue
        paths.append(item)
    for directory in paths:
        candidate = Path(directory or ".") / "gamescope"
        if candidate.is_file() and os.access(candidate, os.X_OK) and candidate.resolve() != shim:
            return candidate.resolve(), os.pathsep.join(paths)
    raise FileNotFoundError("Real Gamescope executable not found in PATH outside the plugin shim")


def gamescope_main(argv: list[str] | None = None) -> int:
    try:
        settings = os.environ.get("DISPLAY_SWITCHER_SETTINGS")
        if not settings:
            raise ValueError("DISPLAY_SWITCHER_SETTINGS is not set")
        preference = load_preference(Path(settings))
        displays, errors = discover_displays()
        for error in errors:
            print(f"Display Switcher: {error}", file=sys.stderr)
        selected = select_display(displays, preference)
        arguments = gamescope_arguments(list(sys.argv[1:] if argv is None else argv), selected)
        executable, path = _real_gamescope()
        environment = dict(os.environ, PATH=path)
        os.execve(executable, [str(executable), *arguments], environment)
    except (OSError, ValueError, KeyError) as exc:
        print(f"Display Switcher: {exc}", file=sys.stderr)
        return 1
