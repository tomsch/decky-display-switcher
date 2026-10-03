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
  return pixels ? `${width} × ${height}` : "not reported";
}

function DisplayDetails({ display }: { display: Display }) {
  return (
    <div style={{ fontSize: 12, lineHeight: 1.45, overflowWrap: "anywhere" }}>
      <div>Connector: {display.connector}</div>
      <div>
        {display.connected ? "Connected" : "Disconnected"}
        {" · "}DRM: {display.enabled ? "enabled" : "disabled"}
      </div>
      <div>Detection: {display.identity_source === "edid" ? "EDID" : "Connector (no valid EDID)"}</div>
      <div>Identity: {display.identity}</div>
      {display.preferred && <div>Preferred at next startup</div>}
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
        setRequestError(`Could not load displays: ${errorText(error)}`);
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
      if (!result.ok) failure = result.error ?? "Output switching failed.";
    } catch (error: unknown) {
      failure = `Could not confirm the output switch: ${errorText(error)}`;
    }

    // A session restart can unmount this view before the RPC returns.
    if (isCurrent(epoch)) {
      try {
        await readSnapshot(epoch);
      } catch (error: unknown) {
        const refreshFailure = `Could not refresh the status: ${errorText(error)}`;
        failure = failure ? `${failure} ${refreshFailure}` : refreshFailure;
      }
    }
    switchLock.current = false;
    if (isCurrent(epoch)) {
      setSwitching(false);
      setRequestError(failure);
      if (succeeded) setNotice("Output switch confirmed.");
    }
  };

  const localBusy = loading || switching;
  const switchBusy = localBusy || Boolean(snapshot?.switching);
  const connected = snapshot?.displays.filter((display) => display.connected) ?? [];

  return (
    <>
      <PanelSection title="Displays">
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={localBusy}
            onClick={() => void refresh()}
          >
            {loading ? "Loading…" : "Refresh"}
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
                ? "Switching outputs. Closing Steam and running games…"
                : snapshot?.switching
                  ? "Switching outputs. Refresh the status afterwards."
                  : notice}
            </div>
          </PanelSectionRow>
        )}
      </PanelSection>

      {snapshot && (
        <>
          <PanelSection title="Monitors">
            <PanelSectionRow>
              <div style={{ fontSize: 12, lineHeight: 1.45 }}>
                <strong>“Switch here”</strong> closes Steam and running games
                and immediately restarts the Gaming Mode session.
              </div>
            </PanelSectionRow>
            {connected.length ? connected.map((display) => (
              <PanelSectionRow key={display.id}>
                <ButtonItem
                  layout="below"
                  label={display.name}
                  description={`Max. resolution: ${maximumResolution(display.modes)}`}
                  disabled={switchBusy || !snapshot.integration_ready || display.active}
                  onClick={() => void startSwitch(display)}
                >
                  {display.active ? "Active" : "Switch here"}
                </ButtonItem>
              </PanelSectionRow>
            )) : (
              <PanelSectionRow><div>No connected monitors detected.</div></PanelSectionRow>
            )}
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => setDetailsVisible((visible) => !visible)}>
                {detailsVisible ? "Hide details" : "Show details"}
              </ButtonItem>
            </PanelSectionRow>
          </PanelSection>
          {detailsVisible && (
            <PanelSection title="Technical details">
              <PanelSectionRow>
                <div style={{ fontSize: 12, lineHeight: 1.45, overflowWrap: "anywhere" }}>
                  <div>Gamescope output: {snapshot.active_connector ?? "unknown"}</div>
                  <div>Source: {snapshot.active_source ?? "no reliable output information"}</div>
                  <div>Startup preference: {snapshot.preferred?.name ?? "automatic"}</div>
                  <div>Session integration: {snapshot.integration_ready ? "ready" : "unavailable"}</div>
                  <div>Max. resolution is advertised, not the current or native panel resolution.</div>
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
