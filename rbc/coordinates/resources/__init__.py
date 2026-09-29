"""External data that coordinate finding reads, one module per resource.

Each module is named after its resource and keeps its local files in the subfolder of
the run's ``resources_dir`` carrying the same name (s. `build_shared_resources`).

An overview of what they all are for:
- `gem`, `ppm`, `osmpp`, `overpass`: "What EGE locations are known?"
  -- supply match candidates with coordinates, via a `LocatorSchema` mapping their columns.
- `eic`: "What details can be found for an EGE based on its EIC code? And what is its parent?"
  -- name enrichment and parent resolution. NO COORDINATES!
- `natural_earth`:  "Does a coordinate lie in that region?"
  -- define regions as a registry, validation only. NO COORDINATES!

Some sources do several things (e.g.: `gem` and `ppm` also answer code questions in
`match_by_entsoe_id`), which is why they all live in one folder rather than being split
into locators and registries.
"""
