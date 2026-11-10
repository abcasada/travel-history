# UI layouts and keyboard shortcuts

Moved from PLAN.md §18 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 18. UI layouts and keyboard shortcuts

### 18.1 Shell selection

One React codebase, two shells on the same API, served under `/app/` (public pages and the API live outside it). Desktop shell when
`(min-width: 1024px) and (pointer: fine)` matches, else mobile; a manual switch in the menu
overrides it (stored as a preference per device class). The route editor, review queue and
stats pages are lazy-loaded chunks imported only by the desktop shell.

### 18.2 Desktop

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ ◉ Travel   [Map] [Trips] [Review 12] [Stats] [Vehicles] [History]   🔍 /  ☰ │
├─────────────────────────────┬─┬──────────────────────────────────────────────┤
│ Filters: 2019–2024 · Work × │ │                                              │
│ ☐ ▸ 2024-08 Colorado roadtrip│║│            MapLibre map                      │
│ ☑ ▸ 2024-06 Chicago (work)  │║│   trips (vector tiles) · selected trip       │
│ ☑ ▸ 2024-05 Family visit    │║│   highlighted · flights as arcs              │
│ ☐ ▸ 2024-03 Denver flight   │║│                                              │
│ ...                         │ │                                              │
│ [2 selected] Tag · Purpose ·│ │                        [layers] [+/-] [fit]  │
│ Participants · Visibility   │ │                                              │
└─────────────────────────────┴─┴──────────────────────────────────────────────┘
   list pane                 draggable divider (ratio saved per user + device class)
```

- Home screen: map of all my trips (and trips visible to me, toggle) with the list collapsed.
- Trip detail replaces the list pane: header, legs timeline, participants, tags, notes,
  photos, route versions; "Edit route" opens the route editor over the map.
- Review queue: list of candidates on the left, candidate's points/segments and proposed legs on
  the map, action bar with keys.

### 18.3 Mobile

```
┌───────────────────────┐
│ ◉ Travel        🔍  ☰ │
├───────────────────────┤
│                       │
│      map (half)       │
│                       │
├───────────────────────┤
│ ▔▔ (drag sheet)       │
│ 2024-08 Colorado …    │
│ 2024-06 Chicago …     │
│ ...                   │
├───────────────────────┤
│ Map  Trips  Add  Me   │
└───────────────────────┘
```

Browse/filter trips, view them on the map, edit tags, participants, notes and own
contributions, add basic photos. No route editing, review queue or stats editing.

### 18.4 Keyboard shortcuts (desktop)

No Ctrl/Cmd combinations are used (they collide with browser and OS shortcuts such as Ctrl+T/W/N/L/R/S/P/F, Ctrl+Tab, Alt+←).
Shortcuts are ignored while typing in a text field, except `Esc`. Implemented behind the
`shortcuts` adapter so a desktop wrapper can add global shortcuts later.

| Scope | Keys | Action |
|---|---|---|
| Global | `?` | shortcut help |
| | `/` | focus search |
| | `g` then `m` / `t` / `r` / `s` / `v` / `h` | go to Map / Trips / Review / Stats / Vehicles / History |
| | `[` / `]` | shrink / grow list pane; `\` toggle list pane |
| | `Esc` | close dialog / clear selection / cancel edit |
| Lists | `j` / `k` | next / previous |
| | `x` | toggle select; `Shift+j/k` extend selection; `*` then `a` / `n` select all / none |
| | `Enter` / `o` | open |
| | `e` | edit selected |
| | `t` | tag selected |
| | `p` | participants for selected |
| | `u` | purpose for selected; `1`–`7` set purpose directly |
| | `f` | fit map to selection |
| Review queue | `a` | accept (confirm + lock) |
| | `r` | reject |
| | `m` | merge with next candidate |
| | `s` | split at the selected point |
| | `z` | undo last action |
| Route editor | `Enter` | save as new route version |
| | `Esc` | discard changes |
| | `Backspace` / `Delete` | remove selected anchor |
| | `z` / `Shift+z` | undo / redo |
| | `r` | re-route from current anchors |
| | `f` | fit to route |
