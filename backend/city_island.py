"""The NEW city map as an island document (same schema the game already uses).

`build_city_island()` turns backend/data/city_layout_v1.json (478 typed slots in 4
districts, parks) into the `islands` document with id "ton_island": every slot is
one cell at its TOP-LEFT tile, with the usual fields (zone, pre_business, prices,
name, icon, tier, income) plus w/h (lot size), district and slot_id. All existing
buy / claim / level-0 / plot code keeps working because it addresses cells by x, y.
"""
import json
from functools import lru_cache
from pathlib import Path
from typing import Dict

from map_config import CITY_BUSINESSES, ton_to_city, ZONE_CONFIG

LAYOUT_PATH = Path(__file__).resolve().parent / "data" / "city_layout_v1.json"
# sprite / layout names -> CITY_BUSINESSES keys used by the island & plot code
TO_MAP_KEY = {"chips_factory": "chip_factory", "logistics_hub": "logistics", "repair_shop": "repair_zone",
              "hydro_cooling": "cold_storage"}


@lru_cache(maxsize=1)
def load_layout() -> Dict:
    return json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))


def _zone(slot: Dict) -> str:
    if slot["size"] == "3x3":
        return "core"
    if slot["size"] in ("2x2", "1x2"):
        return "center"
    return "middle" if slot["district"] in (1, 2) else "outer"


def build_city_island() -> Dict:
    lay = load_layout()
    cells, zone_stats, biz_stats = [], {"core": 0, "center": 0, "middle": 0, "outer": 0}, {"tier1": 0, "tier2": 0, "tier3": 0, "empty": 0}
    for s in lay["slots"]:
        key = TO_MAP_KEY.get(s["business_type"], s["business_type"])
        biz = CITY_BUSINESSES.get(key, {})
        zone = _zone(s)
        cell = {"x": s["x"], "y": s["y"], "w": s["w"], "h": s["h"], "slot_id": s["slot_id"], "district": s["district"],
                "size": s["size"], "is_available": True, "owner": None, "zone": zone, "pre_business": key,
                "is_center": s["district"] == 1}
        if biz:
            cell.update({"price_ton": biz["price_ton"], "price_city": ton_to_city(biz["price_ton"]),
                         "business_icon": biz.get("icon"), "business_name": biz.get("name"), "business_tier": biz.get("tier"),
                         "monthly_income_ton": biz.get("monthly_income_ton"),
                         "monthly_income_city": ton_to_city(biz.get("monthly_income_ton") or 0)})
            biz_stats[f"tier{biz.get('tier', 1)}"] += 1
        zone_stats[zone] += 1
        cells.append(cell)
    return {"id": "ton_island", "version": lay.get("version", "city_v1"), "name": "GRAM City",
            "width": lay["grid"], "height": lay["grid"], "total_cells": len(cells), "cells": cells,
            "districts": lay["districts"],
            # "x,y" strings: portable (no nested arrays) and compact
            "parks": [f"{p[0]},{p[1]}" if isinstance(p, (list, tuple)) else str(p) for p in lay["parks"]],
            "zone_stats": zone_stats, "business_stats": biz_stats,
            "zones": ZONE_CONFIG, "businesses": CITY_BUSINESSES, "city_rate": 1000}
