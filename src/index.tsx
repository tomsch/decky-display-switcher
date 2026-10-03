import { callable, definePlugin } from "@decky/api";
import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  staticClasses,
} from "@decky/ui";
import { useCallback, useEffect, useRef, useState } from "react";
import { FaDesktop } from "react-icons/fa";
import type { Display, Snapshot, SwitchResult } from "./types";

const getDisplays = callable<[], Snapshot>("get_displays");
const switchDisplay = callable<[display_id: string], SwitchResult>("switch_display");

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function maximumResolution(modes: readonly string[]): string {
  let width = 0;
  let height = 0;
  let pixels = 0;
  for (const mode of modes) {
    const match = /^(\d+)x(\d+)i?$/.exec(mode);
    if (!match) continue;
    const nextWidth = Number(match[1]);
    const nextHeight = Number(match[2]);
    const nextPixels = nextWidth * nextHeight;
    if (nextPixels > pixels || (nextPixels === pixels && nextWidth > width)) {
      width = nextWidth;
      height = nextHeight;
      pixels = nextPixels;
    }
  }
  return pixels ? `${width} × ${height}` : "nicht gemeldet";
}

function DisplayDetails({ display }: { display: Display }) {
  return (
    <div style={{ fontSize: 12, lineHeight: 1.45, overflowWrap: "anywhere" }}>
      <div>Anschluss: {display.connector}</div>
      <div>
        {display.connected ? "Verbunden" : "Nicht verbunden"}
        {" · "}DRM: {display.enabled ? "aktiviert" : "deaktiviert"}
      </div>
      <div>Erkennung: {display.identity_source === "edid" ? "EDID" : "Anschluss (keine gültige EDID)"}</div>
      <div>Identität: {display.identity}</div>
      {display.preferred && <div>Bevorzugt beim nächsten Start</div>}
    </div>
  );
}

function Content() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [switching, setSwitching] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [detailsVisible, setDetailsVisible] = useState(false);
  const mounted = useRef(false);
  const lifetime = useRef(0);
  const pendingSnapshot = useRef<Promise<Snapshot> | null>(null);
  const switchLock = useRef(false);

  const isCurrent = useCallback(
    (epoch: number) => mounted.current && lifetime.current === epoch,
    [],
  );

  // Reuse in-flight reads; only the current mount may apply the result.
  const readSnapshot = useCallback(
    async (epoch: number) => {
      const request = pendingSnapshot.current ?? getDisplays();
      pendingSnapshot.current = request;
      try {
        const next = await request;
        if (isCurrent(epoch)) setSnapshot(next);
        return next;
      } finally {
        if (pendingSnapshot.current === request) pendingSnapshot.current = null;
      }
    },
    [isCurrent],
  );

  const refresh = useCallback(async () => {
    if (!mounted.current || switchLock.current) return;
    const epoch = lifetime.current;
    setLoading(true);
    setRequestError(null);
    setNotice(null);
    try {
      await readSnapshot(epoch);
    } catch (error: unknown) {
      if (isCurrent(epoch)) {
        setRequestError(`Anzeigen konnten nicht geladen werden: ${errorText(error)}`);
      }
    } finally {
      if (isCurrent(epoch)) setLoading(false);
    }
  }, [isCurrent, readSnapshot]);

  useEffect(() => {
    mounted.current = true;
    lifetime.current += 1;
    void refresh();
    return () => {
      mounted.current = false;
      lifetime.current += 1;
    };
  }, [refresh]);

  const startSwitch = async (display: Display) => {
    if (
      !display.connected ||
      display.active ||
      !snapshot?.integration_ready ||
      loading ||
      !mounted.current ||
      switchLock.current ||
      pendingSnapshot.current ||
      snapshot?.switching
    ) return;

    const epoch = lifetime.current;
    switchLock.current = true;
    setSwitching(true);
    setRequestError(null);
    setNotice(null);
    let failure: string | null = null;
    let succeeded = false;
    try {
      const result = await switchDisplay(display.id);
      succeeded = result.ok;
      if (!result.ok) failure = result.error ?? "Der Ausgangswechsel ist fehlgeschlagen.";
    } catch (error: unknown) {
      failure = `Ausgangswechsel konnte nicht bestätigt werden: ${errorText(error)}`;
    }

    // A session restart can unmount this view before the RPC returns.
    if (isCurrent(epoch)) {
      try {
        await readSnapshot(epoch);
      } catch (error: unknown) {
        const refreshFailure = `Status konnte nicht neu geladen werden: ${errorText(error)}`;
        failure = failure ? `${failure} ${refreshFailure}` : refreshFailure;
      }
    }
    switchLock.current = false;
    if (isCurrent(epoch)) {
      setSwitching(false);
      setRequestError(failure);
      if (succeeded) setNotice("Ausgangswechsel bestätigt.");
    }
  };

  const localBusy = loading || switching;
  const switchBusy = localBusy || Boolean(snapshot?.switching);
  const connected = snapshot?.displays.filter((display) => display.connected) ?? [];

  return (
    <>
      <PanelSection title="Anzeigen">
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={localBusy}
            onClick={() => void refresh()}
          >
            {loading ? "Wird geladen…" : "Aktualisieren"}
          </ButtonItem>
        </PanelSectionRow>
        {(requestError || snapshot?.error) && (
          <PanelSectionRow>
            <div role="alert" style={{ fontSize: 12, overflowWrap: "anywhere" }}>
              {requestError && <div>{requestError}</div>}
              {snapshot?.error && snapshot.error !== requestError && <div>{snapshot.error}</div>}
            </div>
          </PanelSectionRow>
        )}
        {(switching || snapshot?.switching || notice) && (
          <PanelSectionRow>
            <div role="status" style={{ fontSize: 12 }}>
              {switching
                ? "Ausgangswechsel läuft. Steam und laufende Spiele werden beendet…"
                : snapshot?.switching
                  ? "Ausgangswechsel läuft. Danach den Status aktualisieren."
                  : notice}
            </div>
          </PanelSectionRow>
        )}
      </PanelSection>

      {snapshot && (
        <>
          <PanelSection title="Monitore">
            <PanelSectionRow>
              <div style={{ fontSize: 12, lineHeight: 1.45 }}>
                <strong>„Hierher wechseln“</strong> beendet Steam und laufende Spiele
                und startet die Gaming-Sitzung sofort neu.
              </div>
            </PanelSectionRow>
            {connected.length ? connected.map((display) => (
              <PanelSectionRow key={display.id}>
                <ButtonItem
                  layout="below"
                  label={display.name}
                  description={`Max. Auflösung: ${maximumResolution(display.modes)}`}
                  disabled={switchBusy || !snapshot.integration_ready || display.active}
                  onClick={() => void startSwitch(display)}
                >
                  {display.active ? "Aktiv" : "Hierher wechseln"}
                </ButtonItem>
              </PanelSectionRow>
            )) : (
              <PanelSectionRow><div>Keine verbundenen Monitore erkannt.</div></PanelSectionRow>
            )}
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => setDetailsVisible((visible) => !visible)}>
                {detailsVisible ? "Details ausblenden" : "Details anzeigen"}
              </ButtonItem>
            </PanelSectionRow>
          </PanelSection>
          {detailsVisible && (
            <PanelSection title="Technische Details">
              <PanelSectionRow>
                <div style={{ fontSize: 12, lineHeight: 1.45, overflowWrap: "anywhere" }}>
                  <div>Gamescope-Ausgang: {snapshot.active_connector ?? "nicht ermittelbar"}</div>
                  <div>Quelle: {snapshot.active_source ?? "keine verlässliche Ausgabeinformation"}</div>
                  <div>Bevorzugt beim Start: {snapshot.preferred?.name ?? "automatisch"}</div>
                  <div>Session-Anbindung: {snapshot.integration_ready ? "eingerichtet" : "nicht verfügbar"}</div>
                  <div>Max. Auflösung ist gemeldet, nicht die aktuelle oder native Panelauflösung.</div>
                </div>
              </PanelSectionRow>
              {snapshot.displays.map((display) => (
                <PanelSectionRow key={display.id}>
                  <div>
                    <strong>{display.name}</strong>
                    <DisplayDetails display={display} />
                  </div>
                </PanelSectionRow>
              ))}
            </PanelSection>
          )}
        </>
      )}
    </>
  );
}

export default definePlugin(() => ({
  name: "Display Switcher",
  titleView: <div className={staticClasses.Title}>Display Switcher</div>,
  content: <Content />,
  icon: <FaDesktop />,
}));
