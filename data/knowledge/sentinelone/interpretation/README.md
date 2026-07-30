# Interpretation-layer runtime log (Milestone 7, generated -- not committed)

`uncatalogued_enum_values.jsonl` -- one JSON line per raw enum value
`services/sentinelone_grounding_service.py`'s `decode_enum_value()` couldn't
find in the ontology's enum tables (entity, enum_ref, raw_value, timestamp).

Not committed to git (see `.gitignore`): it's a runtime log, not curated
knowledge. Same purpose as the router's fallback-candidate logging (Milestone
6): the long tail feeds back into the ontology instead of being silently
passed through or re-guessed. Periodically review it and add confirmed
values to `data/knowledge/sentinelone/ontology/sentinelone_ontology.yaml`'s
`enums` tables.
