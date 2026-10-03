# Third-party notices

Display Switcher's own code is licensed under the [MIT license](../LICENSE). This does not relicense third-party material: the original licenses below continue to apply, including within `dist/index.js` and the release ZIP.

Release ZIPs include these notices, the license texts and `sources.zip`. Extract
that archive for the complete plugin and Decky API sources; the source link below
points to their location in the repository or extracted source tree.

## Included material

| Material | Version / provenance | License and retained notice |
| --- | --- | --- |
| Decky API code bundled in `dist/index.js` | `@decky/api` **1.1.3**, SteamDeckHomebrew Team; [upstream source](https://github.com/SteamDeckHomebrew/loader-api/tree/d1b7f16070777a0ada939cbacd3606eeba0574f5) (npm release `gitHead`) | **LGPL-2.1**; [complete license](../licenses/LGPL-2.1.txt), [corresponding source](../third_party/decky-api/) |
| React icon helpers, including `IconBase` / `GenIcon`, bundled in `dist/index.js` | `react-icons` **5.3.0**; [upstream release source](https://github.com/react-icons/react-icons/tree/6188fc096b4d2b4d80d1701aa694889ce7aa71f6) | **MIT** for the helpers, Copyright 2018 kamijin_fanta; [verbatim installed package license](../licenses/react-icons.txt) |
| Desktop icon geometry, bundled as `FaDesktop` from `react-icons/fa` | Font Awesome Free **5.15.4**, by **@fontawesome**; icon-pack revision **5.15.4-3-gafecf2a**, as recorded in the [react-icons 5.3.0 version manifest](https://github.com/react-icons/react-icons/blob/6188fc096b4d2b4d80d1701aa694889ce7aa71f6/packages/react-icons/VERSIONS) | **CC BY 4.0**, not the helpers' MIT license; [original attribution, upstream license notice and complete CC BY 4.0 text](../licenses/font-awesome.txt) |
| Retained Decky plugin template material | Steam Deck Homebrew; [original upstream BSD notice](https://github.com/SteamDeckHomebrew/decky-plugin-template/blob/4ab713585dbe77baefa83c3a2fa57cb1872be1f4/LICENSE) | **BSD-3-Clause**; [retained original notice](../licenses/decky-template.txt) |

**Icon credit:** [Font Awesome](https://fontawesome.com/), `desktop` (solid), by @fontawesome, licensed under [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/). The [original SVG](https://github.com/FortAwesome/Font-Awesome/blob/afecf2af5d897b763e5e8e28d46aad2f710ccad6/svgs/solid/desktop.svg) is wrapped as a React component by react-icons; its viewBox and path geometry are unmodified. The [original Font Awesome license notice](https://github.com/FortAwesome/Font-Awesome/blob/afecf2af5d897b763e5e8e28d46aad2f710ccad6/LICENSE.txt) distinguishes icons from fonts and support code. No Font Awesome fonts are included.

The installed react-icons license lists many icon libraries; this plugin uses only the Font Awesome 5 `FaDesktop` icon. Those other listed icon libraries are not included merely because their license references remain in the verbatim package notice.

The template notice preserves `Original Copyright (c) 2022-2024, Steam Deck Homebrew`, all BSD conditions, and the disclaimer. The upstream customization placeholder `Hypothetical Plugin Developer` is omitted; it is not an author of this project, and no replacement authorship is invented.

## Externally supplied runtime libraries

- `@decky/ui` **4.12.1** is the pinned build dependency ([upstream source](https://github.com/SteamDeckHomebrew/decky-frontend-lib/tree/4b68ef7287d8b11e62ed7b285532cf4ea36df89c), SteamDeckHomebrew Team, **LGPL-2.1**). It is externalized by `@decky/rollup` to Decky's `DFL` runtime global, not bundled in `dist/index.js`; the installed Decky runtime supplies its actual version. The [LGPL-2.1 text](../licenses/LGPL-2.1.txt) is included for reference.
- React is externalized to the `SP_REACT` runtime global and supplied by Steam, not bundled in `dist/index.js`. Its runtime version is not fixed by this plugin's build dependencies. React's upstream license is [MIT](https://github.com/facebook/react/blob/main/LICENSE); this notice does not identify or relicense a particular Steam-supplied copy.

See [README](../README.md) for source-build and Decky API modification/relink instructions. These notices describe the identified components and their original licenses; they are not a legal certification.
