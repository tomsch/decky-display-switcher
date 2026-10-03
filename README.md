# Display Switcher

Decky-Plugin zum direkten Wechsel zwischen verbundenen Monitoren in der
SteamOS-Gaming-Sitzung. Keine Samsung-/TV-Profile, keine vorher eingerichteten
Umschaltskripte, keine Änderungen an `/usr` und kein Root-Plugin.

Quellcode: [GitHub](https://github.com/tomsch/decky-display-switcher) ·
[Forgejo](https://git.sch.at/tom/decky-display-switcher).
Installierbare ZIPs: [Releases](https://github.com/tomsch/decky-display-switcher/releases).

## Voraussetzungen

- Decky Loader mit Plugin-API 1 und modernen `@decky/api`/`@decky/ui`-APIs.
- Gamescope-Gaming-Sitzung mit `gamescope-session.service` und
  `gamescope-session.target` im systemd-Benutzermanager.
- Stock-Sitzungsdienst unter `/usr/lib` oder `/lib` mit einem einzelnen absoluten
  `ExecStart`-Skriptpfad. Das Shell-Skript muss Gamescope genau einmal über
  unqualifiziertes `exec gamescope` starten und darf `PATH` nicht überschreiben.
- `gamescope`, `gamescopectl`, `systemctl` und Python 3.10+ im Suchpfad.
  Gamescope muss aktive Displayinformationen über das Control-Protokoll melden.

Das Plugin ist monitorunabhängig, aber kein Adapter für beliebige Linux-
Sitzungsmanager. Unbekannte Stock-Formate und fremde `ExecStart`-Overrides werden
nicht überschrieben. Die Displayliste bleibt mit einer Diagnose verfügbar.
Es ist kein Auflösungs- oder Bildwiederholratenmanager.

## Bedienung

Decky → **Display Switcher** → beim gewünschten Monitor **Hierher wechseln**.
**Der Wechsel startet sofort, ohne Bestätigungsdialog. Er beendet Steam und laufende
Spiele und startet die Gaming-Sitzung neu.** Ungespeicherter Spielfortschritt kann
verloren gehen. Während des Neustarts kann das Bild schwarz sein.

Der tatsächlich von Gamescope verwendete Ausgang wird über den lesenden Aufruf
`gamescopectl` erkannt. Sein Button zeigt **Aktiv** und ist deaktiviert. DRM-
Encoderstatus und gespeicherte Präferenz werden nicht als Aktivitätsnachweis
verwendet. Ohne eindeutige aktive Gamescope-Auskunft wird kein blinder Neustart
zugelassen.

Die kompakte Ansicht zeigt nur verbundene Monitore, jeweils mit **Max. Auflösung**.
**Details anzeigen** klappt Anschlüsse, DRM-Status, Monitoridentität, Startpräferenz
und Session-Anbindung auf. Der Neustarthinweis steht im Bereich **Monitore** und
nennt ausdrücklich **Hierher wechseln**. **Aktualisieren** liest den Zustand nach
Hotplug oder Kabelwechsel erneut ein; dieser Button startet die Sitzung nicht neu.

„Max. Auflösung“ ist die vom Anschluss gemeldete Auflösung mit der höchsten
Pixelzahl, nicht die aktuelle oder native Panelauflösung. Hz werden aus den
Sysfs-Modinamen nicht abgeleitet. DRM-Writeback-Ziele sind keine Monitoroptionen.

## Startpräferenz und Rückfall

Ein Wechsel speichert die bevorzugte Monitoridentität atomar als versioniertes
JSON im Decky-Einstellungsverzeichnis. Eine brauchbare EDID-Seriennummer verbindet
die Präferenz mit dem Monitor statt mit seinem Port. Ohne Seriennummer wird der
vollständige gültige EDID-Hash verwendet; ohne gültige EDID bleibt die Präferenz
anschlussgebunden. Identische EDIDs lassen sich ohne weitere Geräteinformationen
nicht eindeutig unterscheiden; dann hilft der gespeicherte Anschluss.
HDMI-Extension-Count-Overrides werden berücksichtigt; die vollständige deklarierte
EDID-Länge und die Prüfsummen aller Blöcke bleiben Pflicht.

Bei jedem Sitzungsstart prüft der Gamescope-Shim die aktuell verbundenen Monitore.
Fehlt der bevorzugte Monitor, verwendet er den einzigen DRM-aktivierten verbundenen
Ausgang, andernfalls den ersten verbundenen Ausgang in stabiler Anschlussreihenfolge.
Die gespeicherte Präferenz wird dabei **nicht** überschrieben: Sobald der bevorzugte
Monitor wieder vorhanden ist, wird er beim nächsten Sitzungsstart erneut bevorzugt.
Ohne verbundenen Ausgang bleibt Gamescopes Stock-Wildcard-Priorität erhalten.
Das ist ein Start-Rückfall, kein eigener Hotplug-Neustartdienst.

## Installation und Deinstallation

Das ZIP über Deckys Funktion **Installieren von URL** oder den ZIP-Dateiauswahldialog
installieren. Für eine URL muss das Paket vom SteamOS-PC aus erreichbar sein.
Decky übernimmt Installation, Besitzrechte und Laden des Plugins.

Beim Laden richtet das Plugin diesen benutzereigenen Drop-in ein:

```text
~/.config/systemd/user/gamescope-session.service.d/90-display-switcher.conf
```

Er startet den unveränderten Stock-Sitzungsablauf über `session.py`. Ein temporärer
PATH-Shim setzt nur Gamescopes Ausgangspriorität und entfernt sich vor dem Start
des echten Gamescope wieder aus dem Suchpfad. Argumente des gestarteten Spiels
bleiben unverändert. Einrichtung und `daemon-reload` starten die laufende Sitzung
**nicht** neu; die Anbindung gilt für kommende Starts beziehungsweise einen
bewusst ausgelösten Ausgangswechsel.
Systemprogramme verwenden den ursprünglichen Bibliothekssuchpfad statt Deckys
gebündelter Laufzeitbibliotheken. Die Umgebung von Decky selbst bleibt unverändert.

Das Plugin läuft als Deckys normaler Benutzer und verwendet dessen systemd-Bus.
Es enthält keine Passwörter oder SSH-Zugänge. Deinstallation entfernt ausschließlich
den unverändert pluginverwalteten Drop-in und lädt systemd neu, ohne die laufende
Sitzung neu zu starten. Fremde oder nachträglich veränderte Konfiguration bleibt
unberührt. Ein normaler Plugin-Reload behält die Session-Anbindung.

## Entwicklung

Node.js, Python 3.10+ und pnpm 9 verwenden. React und die Decky-Oberfläche stellt
Steam/Decky zur Laufzeit bereit; sie werden nicht ins Plugin gebündelt.

Die Tests prüfen Monitorauswahl, Präferenzen und Session-Verwaltung. Auf SteamOS
sind Ausgangserkennung und Oberfläche geprüft. Live-Wechsel und Start-Rückfall
mit echtem Session-Neustart wurden noch nicht auf Hardware getestet.

```sh
corepack pnpm install --frozen-lockfile --ignore-scripts
corepack pnpm test
corepack pnpm package
```

Alternativ ohne Corepack:

```sh
npm exec --yes --package=pnpm@9.15.9 -- pnpm install --frozen-lockfile --ignore-scripts
npm exec --yes --package=pnpm@9.15.9 -- pnpm test
npm exec --yes --package=pnpm@9.15.9 -- pnpm package
```

`pnpm package` erzeugt zwei Dateien:

- `release/display-switcher-2.0.3.zip`: installierbares Decky-Plugin mit
  Lizenztexten, Fremdkomponenten-Hinweisen und einem eingebetteten `sources.zip`.
- `release/display-switcher-2.0.3-source.zip`: vollständige Plugin-Quellen,
  Build-Konfiguration, Lockfile und der passende Decky-API-Quellstand.

Das eingebettete `sources.zip` ist dieselbe Quell-ZIP-Datei. Zum Neubauen diese
entpacken und im Verzeichnis `display-switcher-2.0.3-source` die obigen
Installations- und Build-Befehle ausführen. Der Build benötigt keinen Steam-Client.

`@decky/api` wird direkt aus `third_party/decky-api/src/index.ts` kompiliert,
nicht aus einem vorgebauten npm-Paket. Um eine geänderte Bibliothek zu verwenden,
die Dateien in `third_party/decky-api/src/` bearbeiten und erneut `pnpm package`
ausführen. Rollup und TypeScript verwenden beide diesen Quellpfad. Die
Provenanzdatei `third_party/decky-api-source.json` beschreibt den ursprünglichen
Upstreamstand. Änderungen an der Bibliothek mit Datum kennzeichnen und die
Fremdkomponenten-Hinweise entsprechend aktualisieren; ihre LGPL-Lizenz bleibt
erhalten.

## Lizenz

Der eigene Code steht unter [MIT](LICENSE). Enthaltene Fremdkomponenten behalten
ihre jeweiligen Lizenzen. Die [Fremdkomponenten-Hinweise](docs/third-party-notices.md)
dokumentieren Decky API, React Icons, Font Awesome und die Template-Anteile.
Lizenztexte liegen in `licenses/` und werden mit jedem Release ausgeliefert.
Die passenden LGPL-Quellen und Unterlagen zum Neubauen liegen im Quellarchiv und
sind auch im Plugin-ZIP enthalten.

## Fehlerdiagnose

Veraltete Auswahl, abgezogene Monitore, unlesbare Präferenzen, nicht unterstützte
Session-Formate und systemd-Fehler werden angezeigt. Nach Hotplug aktualisieren.
Ein erfolgreicher Neustart verlangt eine neue Session-Invocation, geladene eigene
Konfiguration, aktiven Dienst und Target sowie den von Gamescope bestätigten
angeforderten Ausgang; ein Exitcode allein genügt nicht. Ist der Neustart bereits
angefordert, kann eine spätere Fehleranzeige nicht garantieren, dass die Sitzung
unverändert geblieben ist.

```sh
systemctl --user show gamescope-session.service -p ExecStart -p ActiveState
systemctl --user cat gamescope-session.service
gamescopectl
journalctl --user -u gamescope-session.service
journalctl -u plugin_loader.service
```

Dokumentation: [offizielle Quellen](docs/references.md), [Änderungen](CHANGELOG.md),
[Fremdkomponenten und Lizenzen](docs/third-party-notices.md).
