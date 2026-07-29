# Ontology (Milestone 2)

Populated from `../environment_map.yaml` (Milestone 1 output), not from a generic decomposition. Target file: `sentinelone_ontology.yaml`, validated against `data/schemas/ontology.schema.json`.

Contents: entities actually present in this tenant, their real attributes (with population/coverage noted — many fields are optional and often empty), relationships as edges (e.g. Alert → Asset, Vulnerability → Asset, Alert → Storyline), decoded enum tables (severity, status, analystVerdict, etc. — real values only, not the full documented range if some never occur here), lifecycle states, and per-entity tool bindings (which MCP tool answers questions about this entity).

Anything from a generic SOC-entity decomposition that isn't actually present in this tenant (e.g. an unlicensed module) is marked out of scope for now, not fabricated. Requires an analyst review checkpoint before freezing v1.
