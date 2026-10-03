export interface Preference {
  identity: string;
  connector: string;
  name: string;
}

export interface Display {
  /** Connector and full EDID fingerprint; guards against stale selections. */
  id: string;
  /** Stable EDID identity, or connector identity when EDID is unavailable. */
  identity: string;
  identity_source: "edid" | "connector";
  connector: string;
  name: string;
  connected: boolean;
  /** Kernel encoder assignment; not itself proof of Gamescope activity. */
  enabled: boolean;
  modes: string[];
  /** True only for the unambiguous output reported by Gamescope itself. */
  active: boolean;
  preferred: boolean;
}

export interface Snapshot {
  displays: Display[];
  preferred: Preference | null;
  active_connector: string | null;
  active_source: "gamescopectl" | null;
  integration_ready: boolean;
  switching: boolean;
  error: string | null;
}

export interface SwitchResult {
  ok: boolean;
  error: string | null;
}
