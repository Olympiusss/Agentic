# Knowledge retrieval-store index (Milestone 6, generated -- not committed)

`chunks_index.json` holds every chunk `services/sentinelone_retrieval_store.py`
indexes -- ontology entities, coverage-matrix rows, the DV field dictionary,
DV hunt templates, recipes, and `data/agent/tools/` descriptions -- each
embedded with the local model in `services/sentinelone_embeddings.py`.

Not committed to git (see `.gitignore`): it's a ~1.8MB engine-specific float
blob, deterministically regenerated from the committed YAML/markdown sources
by `scripts/build_sentinelone_router_index.py`, not hand-reviewable content.

**Before retrieving for the first time** (or after changing any source file
it chunks), run:

```bash
python scripts/build_sentinelone_router_index.py
```
