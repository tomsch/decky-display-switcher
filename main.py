"""Decky backend for monitor selection and session restarts."""

import asyncio
import hashlib
import os
import pwd
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Awaitable, Callable

# Decky loads main.py by file location; it does not add the plugin root to sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import display_core

try:
    import decky
except ModuleNotFoundError as exc:
    if exc.name != "decky":
        raise
    decky = None


Runner = Callable[[list[str], dict[str, str], float], Awaitable[subprocess.CompletedProcess]]
SERVICE = "gamescope-session.service"
TARGET = "gamescope-session.target"
MARKER = "# Managed by Decky Display Switcher; do not edit.\n"
PROPERTIES = "FragmentPath,ExecStart,ActiveState,InvocationID,NeedDaemonReload,LoadState"


async def run_command(argv: list[str], environment: dict[str, str], timeout: float):
    process = await asyncio.create_subprocess_exec(
        *argv, env=environment, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.communicate()
        raise
    return subprocess.CompletedProcess(
        argv, process.returncode, stdout.decode("utf-8", "replace"),
        stderr.decode("utf-8", "replace"),
    )


def systemd_argument(value: str) -> str:
    """Escape systemd's quoting, specifier and variable expansion."""
    if not value or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("Ungültiger Pfad für die systemd-Integration.")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + escaped.replace("%", "%%").replace("$", "$$") + '"'


class Plugin:
    def __init__(self, home: Path | None = None, drm_root: Path | None = None,
                 runner: Runner | None = None, settings_path: Path | None = None,
                 plugin_dir: Path | None = None):
        def configured(name: str) -> str:
            return os.environ.get(name) or (getattr(decky, name, "") if decky else "")

        self.home = Path(home or configured("DECKY_USER_HOME") or Path.home()).absolute()
        settings_dir = configured("DECKY_PLUGIN_SETTINGS_DIR")
        default_settings = (Path(settings_dir) if settings_dir else self.home / ".config/display-switcher")
        self.settings_path = Path(settings_path or default_settings / "preferences.json").absolute()
        self.plugin_dir = Path(plugin_dir or configured("DECKY_PLUGIN_DIR") or Path(__file__).parent).absolute()
        self.drm_root = Path(drm_root or "/sys/class/drm")
        self.runner = runner or run_command
        self.dropin = self.home / ".config/systemd/user/gamescope-session.service.d/90-display-switcher.conf"
        owner = f"{self.plugin_dir}\0{self.settings_path}"
        self._owner = hashlib.sha256(owner.encode("utf-8")).hexdigest()
        self._lock = asyncio.Lock()
        self._closed = False
        self._switch_task = None
        self._setup_task = None
        self._verification_seconds = 20.0
        self._poll_seconds = 0.5

    def _environment(self) -> dict[str, str]:
        username = os.environ.get("DECKY_USER") or (getattr(decky, "DECKY_USER", "") if decky else "")
        account = pwd.getpwnam(username) if username else pwd.getpwuid(os.geteuid())
        if os.geteuid() == 0 or account.pw_uid == 0:
            raise PermissionError("Display Switcher darf nicht als root laufen (Decky-Flags müssen leer sein).")
        if os.geteuid() != account.pw_uid or os.getuid() != account.pw_uid:
            raise PermissionError("Decky läuft nicht als der Benutzer der Gaming-Sitzung.")
        environment = dict(os.environ)
        # Decky's frozen runtime prepends bundled libraries; system tools need the original path.
        original_library_path = environment.pop("LD_LIBRARY_PATH_ORIG", None)
        if original_library_path:
            environment["LD_LIBRARY_PATH"] = original_library_path
        else:
            environment.pop("LD_LIBRARY_PATH", None)
        runtime = f"/run/user/{account.pw_uid}"
        environment.update({
            "HOME": str(self.home), "USER": account.pw_name, "LOGNAME": account.pw_name,
            "XDG_RUNTIME_DIR": runtime, "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime}/bus",
            "GAMESCOPE_WAYLAND_DISPLAY": "gamescope-0",
            "LC_ALL": "C", "SYSTEMD_COLORS": "0", "SYSTEMD_PAGER": "",
        })
        try:
            lines = (Path(runtime) / "gamescope-environment").read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            lines = []
        for line in lines:
            match = re.fullmatch(r"(?:export\s+)?GAMESCOPE_WAYLAND_DISPLAY=(.*)", line)
            if match:
                values = shlex.split(match.group(1))
                if len(values) != 1 or not re.fullmatch(r"[A-Za-z0-9_./-]+", values[0]):
                    raise ValueError("Gamescope-Socket in der Sitzungsumgebung ist ungültig.")
                environment["GAMESCOPE_WAYLAND_DISPLAY"] = values[0]
        return environment

    async def _command(self, argv, environment, timeout=3.0):
        try:
            result = await asyncio.wait_for(self.runner(argv, environment, timeout), timeout)
        except asyncio.TimeoutError as exc:
            raise RuntimeError(f"Zeitlimit bei {Path(argv[0]).name} überschritten.") from exc
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"{Path(argv[0]).name} fehlgeschlagen: {detail or result.returncode}")
        return result.stdout

    async def _service(self, environment, unit=SERVICE):
        text = await self._command([
            "systemctl", "--user", "show", unit, "--all", "--property=" + PROPERTIES,
        ], environment)
        state = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
        if state.get("LoadState") != "loaded":
            raise RuntimeError(f"Benutzerdienst {unit} ist nicht geladen.")
        return state

    def _stock_session(self, state) -> Path:
        fragment = Path(state.get("FragmentPath", ""))
        if not fragment.is_absolute() or not any(
            fragment.is_relative_to(root) for root in (Path("/usr/lib"), Path("/lib"))
        ):
            raise RuntimeError("Kein unterstützter systemweiter Gamescope-Sitzungsdienst gefunden.")
        section = ""
        commands = []
        for raw in fragment.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith(("#", ";")):
                continue
            if line.startswith("["):
                section = line
            elif section == "[Service]" and line.startswith("ExecStart="):
                commands.append(line[len("ExecStart="):].strip())
        if len(commands) != 1 or not re.fullmatch(r"/[A-Za-z0-9_./-]+", commands[0]):
            raise RuntimeError("Nicht unterstütztes Stock-ExecStart: ein einzelner literaler Skriptpfad ist erforderlich.")
        session = Path(commands[0])
        if not session.is_file() or not os.access(session, os.X_OK):
            raise RuntimeError("Das Stock-Sitzungsskript fehlt oder ist nicht ausführbar.")
        content = session.read_text(encoding="utf-8")
        if not re.match(r"#![^\n]*(?:/|\s)(?:ba|da)?sh(?:\s|$)", content):
            raise RuntimeError("Das Stock-Sitzungsskript ist kein unterstütztes Shell-Skript.")
        launches = re.findall(r"(?m)^[ \t]*exec[ \t]+gamescope(?=[ \t\\\n]|$)", content)
        if len(launches) != 1 or re.search(r"(?m)^[ \t]*(?:export[ \t]+)?PATH=", content):
            raise RuntimeError("Stock-Sitzung nicht unterstützt: unqualifiziertes exec gamescope ohne PATH-Überschreibung erforderlich.")
        if re.search(r"(?m)^[ \t]*exec[ \t]+(?:[\"']?)/[^\n]*gamescope(?:[\"']?)(?=[ \t\\\n]|$)", content):
            raise RuntimeError("Absolute Gamescope-Aufrufe können nicht abgefangen werden.")
        return session

    def _arguments(self, session: Path) -> list[str]:
        interpreter = shutil.which("python3")
        if not interpreter:
            raise RuntimeError("Erforderliches Programm fehlt: python3.")
        return [interpreter, str(self.plugin_dir / "session.py"), "--session", str(session),
                "--settings", str(self.settings_path)]

    def _dropin_content(self, session: Path) -> str:
        command = " ".join(map(systemd_argument, self._arguments(session)))
        body = f"[Service]\nExecStart=\nExecStart={command}\n"
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        return MARKER + f"# Owner: {self._owner}\n# Content-SHA256: {digest}\n" + body

    def _owned_content(self, content: str) -> bool:
        prefix = MARKER + f"# Owner: {self._owner}\n# Content-SHA256: "
        if not content.startswith(prefix):
            return False
        checksum, separator, body = content[len(prefix):].partition("\n")
        return bool(
            separator
            and hashlib.sha256(body.encode("utf-8")).hexdigest() == checksum
            and body.startswith("[Service]\nExecStart=\nExecStart=")
            and body.count("\n") == 3
        )

    def _read_dropin(self) -> str | None:
        if self.dropin.is_symlink():
            raise RuntimeError("Der Display-Switcher-Drop-in ist ein fremder symbolischer Link; er bleibt unverändert.")
        try:
            return self.dropin.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def _exec_matches(self, state, argv) -> bool:
        # systemctl flattens argv; a script-path substring is not enough.
        value = state.get("ExecStart", "")
        matches = re.findall(r"\{ path=(.*?) ; argv\[\]=(.*?) ; ignore_errors=no ;", value)
        if len(matches) != 1 or value.count("{ path=") != 1:
            return False
        return matches[0] == (argv[0], " ".join(argv))

    def _integration(self, state, session) -> tuple[bool, str | None]:
        content = self._read_dropin()
        if content is None:
            return False, "Die Integration für kommende Gaming-Sitzungen ist noch nicht installiert."
        if not self._owned_content(content) or content != self._dropin_content(session):
            return False, "Der Display-Switcher-Drop-in enthält fremde oder veränderte Konfiguration; sie bleibt unverändert."
        if state.get("NeedDaemonReload") != "no":
            return False, "Die Gamescope-Konfiguration wurde noch nicht neu geladen."
        if not self._exec_matches(state, self._arguments(session)):
            return False, "Ein anderer Override bestimmt den Gamescope-Sitzungsstart; er bleibt unverändert."
        shim = self.plugin_dir / "bin/gamescope"
        if not shim.is_file() or not os.access(shim, os.X_OK):
            return False, "Der verpackte Gamescope-Shim fehlt oder ist nicht ausführbar."
        for member in ("session.py", "display_core.py"):
            if not (self.plugin_dir / member).is_file():
                return False, f"Plugin-Datei fehlt: {member}."
        return True, None

    async def _ensure_integration(self, environment):
        state = await self._service(environment)
        session = self._stock_session(state)
        for executable in ("systemctl", "gamescope", "gamescopectl", "python3"):
            if not shutil.which(executable, path=environment.get("PATH")):
                raise RuntimeError(f"Erforderliches Programm fehlt: {executable}.")
        for member in ("session.py", "display_core.py", "bin/gamescope"):
            if not (self.plugin_dir / member).is_file():
                raise RuntimeError(f"Plugin-Datei fehlt: {member}.")
        argv = self._arguments(session)
        if any(any(character in value for character in ";{}") for value in argv):
            raise RuntimeError("Die Installationspfade enthalten nicht verifizierbare systemd-Feldtrenner.")
        content = self._read_dropin()
        expected = self._dropin_content(session)
        if content is not None and not self._owned_content(content):
            raise RuntimeError("Der Display-Switcher-Drop-in ist fremd oder verändert; er bleibt unverändert.")
        if not self._exec_matches(state, [str(session)]) and not self._exec_matches(state, argv):
            raise RuntimeError("Ein fremder ExecStart-Override ist aktiv; er bleibt unverändert.")
        shim = self.plugin_dir / "bin/gamescope"
        shim.chmod(shim.stat().st_mode | 0o111)
        if content != expected:
            self.dropin.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.dropin.parent,
                                                 prefix=".display-switcher-", delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(expected)
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.chmod(0o644)
                # Recheck ownership before replacing the file.
                if self._read_dropin() != content:
                    raise RuntimeError("Der Gamescope-Drop-in wurde während der Einrichtung geändert.")
                os.replace(temporary, self.dropin)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        if content != expected or state.get("NeedDaemonReload") != "no":
            await self._command(["systemctl", "--user", "daemon-reload"], environment)
        loaded = await self._service(environment)
        ready, error = self._integration(loaded, session)
        if not ready:
            raise RuntimeError(error)
        return loaded, session

    async def _active(self, environment, displays):
        try:
            text = await self._command(["gamescopectl"], environment)
        except (OSError, RuntimeError) as exc:
            return None, None, f"Aktiver Gamescope-Ausgang unbekannt: {exc}"
        reported = re.findall(r"(?m)^\s*- Connector Name:\s*([^\r\n]+?)\s*$", text)
        if len(reported) != 1:
            return None, None, "Gamescope meldet keinen eindeutigen aktiven Ausgang (Display-Info-Protokoll fehlt)."
        matches = [row for row in displays if row["connected"]
                   and display_core.connector_name(row["connector"]) == reported[0]]
        if len(matches) != 1:
            return None, None, "Der von Gamescope gemeldete aktive Ausgang ist nicht eindeutig einem verbundenen Display zuordenbar."
        return matches[0]["connector"], "gamescopectl", None

    async def _main(self):
        self._closed = False
        self._setup_task = asyncio.current_task()
        try:
            async with self._lock:
                await self._ensure_integration(self._environment())
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            if decky:
                decky.logger.error("Display Switcher: %s", exc)
        finally:
            self._setup_task = None

    async def _unload(self):
        self._closed = True
        for task in (self._switch_task, self._setup_task):
            if task is not None and task is not asyncio.current_task():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def _uninstall(self):
        await self._unload()
        environment = self._environment()
        if self.dropin.is_symlink():
            return
        content = self._read_dropin()
        if content is not None and self._owned_content(content):
            self.dropin.unlink()
            await self._command(["systemctl", "--user", "daemon-reload"], environment)

    async def get_displays(self) -> dict:
        displays, errors = display_core.discover_displays(self.drm_root)
        preferred = None
        try:
            preferred = display_core.load_preference(self.settings_path)
        except (OSError, ValueError) as exc:
            errors.append(f"Display-Präferenz nicht lesbar: {exc}")
        active = source = None
        ready = False
        try:
            environment = self._environment()
            state = await self._service(environment)
            session = self._stock_session(state)
            ready, error = self._integration(state, session)
            if error:
                errors.append(error)
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            errors.append(str(exc))
            environment = None
        # Active output discovery still works if startup integration is unavailable.
        if environment is None:
            try:
                environment = self._environment()
            except (OSError, ValueError, KeyError) as exc:
                errors.append(str(exc))
        if environment is not None:
            active, source, error = await self._active(environment, displays)
            if error:
                errors.append(error)
        preferred_rows = [
            row for row in displays
            if preferred and row["identity"] == preferred["identity"]
        ]
        if len(preferred_rows) > 1:
            preferred_rows = [row for row in preferred_rows if row["connector"] == preferred["connector"]]
        preferred_ids = {row["id"] for row in preferred_rows} if len(preferred_rows) == 1 else set()
        return {
            "displays": [
                dict(row, active=row["connector"] == active, preferred=row["id"] in preferred_ids)
                for row in displays
            ],
            "preferred": preferred, "active_connector": active, "active_source": source,
            "integration_ready": ready, "switching": self._switch_task is not None,
            "error": "\n".join(dict.fromkeys(errors)) or None,
        }

    def _selected(self, display_id):
        displays, errors = display_core.discover_displays(self.drm_root)
        selected = next((row for row in displays if row["id"] == display_id), None)
        if selected is None:
            raise ValueError("Display-Auswahl ist veraltet. Bitte die Anschlussliste aktualisieren.")
        if not selected["connected"]:
            raise ValueError("Das ausgewählte Display ist nicht mehr verbunden.")
        # An unavailable EDID falls back to connector identity.
        selected_errors = [error for error in errors
                           if error.startswith(selected["connector"] + "/")
                           and not error.startswith(selected["connector"] + "/edid")]
        if selected_errors:
            raise ValueError("\n".join(selected_errors))
        return selected, displays

    async def switch_display(self, display_id: str) -> dict:
        if not isinstance(display_id, str) or not display_id:
            return {"ok": False, "error": "Ungültige Display-Auswahl."}
        if self._closed:
            return {"ok": False, "error": "Display Switcher wird beendet."}
        if self._lock.locked():
            return {"ok": False, "error": "Eine Display-Einrichtung oder ein Wechsel läuft bereits."}
        async with self._lock:
            self._switch_task = asyncio.current_task()
            restart_requested = False
            try:
                self._selected(display_id)
                environment = self._environment()
                before, session = await self._ensure_integration(environment)
                selected, displays = self._selected(display_id)
                active, _, error = await self._active(environment, displays)
                if error:
                    raise RuntimeError(error)
                selected, _ = self._selected(display_id)
                display_core.save_preference(self.settings_path, selected)
                if active == selected["connector"]:
                    return {"ok": True, "error": None}
                old_invocation = before.get("InvocationID")
                if not old_invocation:
                    raise RuntimeError("Die bisherige Gamescope-Sitzung hat keine verifizierbare InvocationID.")
                restart_requested = True
                await self._command(["systemctl", "--user", "restart", TARGET], environment, 45.0)
                deadline = asyncio.get_running_loop().time() + self._verification_seconds
                diagnostic = "Der Gamescope-Neustart konnte nicht bestätigt werden."
                while True:
                    try:
                        state = await self._service(environment)
                        target = await self._service(environment, TARGET)
                        ready, integration_error = self._integration(state, session)
                        displays, _ = display_core.discover_displays(self.drm_root)
                        active, _, active_error = await self._active(environment, displays)
                        if not ready:
                            diagnostic = integration_error
                        elif state.get("ActiveState") != "active" or target.get("ActiveState") != "active":
                            diagnostic = "Gamescope-Dienst oder Gaming-Ziel ist nicht aktiv."
                        elif not state.get("InvocationID") or state["InvocationID"] == old_invocation:
                            diagnostic = "Der Neustart der Gamescope-Sitzung wurde nicht bestätigt."
                        elif active != selected["connector"]:
                            diagnostic = active_error or "Gamescope hat nicht den angeforderten Ausgang aktiviert."
                        else:
                            return {"ok": True, "error": None}
                    except (OSError, ValueError, RuntimeError) as exc:
                        diagnostic = str(exc)
                    if asyncio.get_running_loop().time() >= deadline:
                        raise RuntimeError(diagnostic)
                    await asyncio.sleep(self._poll_seconds)
            except (OSError, ValueError, KeyError, RuntimeError) as exc:
                suffix = " Der Gaming-Modus wurde möglicherweise bereits neu gestartet." if restart_requested else ""
                return {"ok": False, "error": str(exc) + suffix}
            finally:
                self._switch_task = None
