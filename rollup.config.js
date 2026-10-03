import deckyPlugin from "@decky/rollup";
import { fileURLToPath } from "node:url";

const apiSource = fileURLToPath(
  new URL("./third_party/decky-api/src/index.ts", import.meta.url),
);
const config = deckyPlugin();

// Compile the supplied LGPL source so users can modify it and rebuild.
config.plugins.unshift({
  name: "decky-api-source",
  resolveId(source) {
    return source === "@decky/api" ? apiSource : null;
  },
});
config.output.banner = `/*
 * Display Switcher: own code MIT.
 * Includes @decky/api (LGPL-2.1), React Icons (MIT) and Font Awesome (CC BY 4.0).
 * Attribution and full terms: docs/third-party-notices.md and licenses/.
 * Matching sources and rebuild instructions are included in sources.zip.
 */`;

export default config;
