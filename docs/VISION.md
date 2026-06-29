# PulseCode Vision

PulseCode can become more than a graph viewer by treating software history as a navigable forensic record. The unique direction is to explain how architecture became what it is, not only what it looks like now.

## Groundbreaking Product Bets

1. **Architecture Replay**
   Let users press play and watch modules split, merge, couple, and decouple over time. The graph should animate structural movement while the timeline narrates why each shift happened.

2. **Causality Lens**
   Connect architectural shifts to the commits, files, and authors most responsible for them. Instead of saying "coupling increased," PulseCode should say "billing became coupled to auth after these three changes."

3. **Evolution Archetypes**
   Classify repo history into recognizable patterns: modular birth, feature accretion, dependency collapse, extraction, platformization, rewrite, and stabilization. These can be rule-based at first.

4. **Architectural Weather**
   Show the current direction of the system as a forecast: coupling pressure, churn hotspots, and modules likely to become bottlenecks if the same trajectory continues.

5. **Before/After Time Portals**
   Let users click an architectural event and compare the graph immediately before and after it, with affected modules highlighted and the relevant commit messages attached.

6. **Narrated System Biography**
   Generate a concise history of the codebase: where it started, what grew, what became central, what was extracted, and where complexity settled.

7. **Local-Only Architectural Memory**
   Keep analysis local but cache prior runs so teams can build a private timeline of their system without sending source code to a cloud service.

## MVP Next Steps

- Add a durable sample repository generator inside the app for demos.
- Parse explicit imports for Python and TypeScript before falling back to co-change heuristics.
- Add before/after event comparison mode.
- Add playback controls beside the slider.
- Add a hotspot mode that colors nodes by churn, centrality, or complexity.
- Export a static evolution report as Markdown or HTML.
