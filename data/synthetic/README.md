Synthetic reference datasets (utility registry, transformers, feeders) are
generated at runtime by `src/synthetic_data.py` rather than stored as static
files, so they always stay consistent with the currently loaded PV inventory
(demo or uploaded). This folder is reserved for future exported snapshots
(e.g. via the in-app CSV/GeoJSON export buttons) if you want to version a
specific synthetic scenario.
