import business_config as bc


def test_repair_price_per_level():
    bc.apply_durability_override("bio_farm", None, 2.0, {"1": 0.5, "10": 7})
    try:
        assert bc.repair_cost_per_pct_city("bio_farm", 1, 1) == 0.5
        assert bc.repair_cost_per_pct_city("bio_farm", 1, 10) == 7
        assert bc.repair_cost_per_pct_city("bio_farm", 1, 5) == 2.0          # no level value: the type's value
        assert bc.repair_cost_per_pct_city("bio_farm", 1) == 2.0
        bc.apply_durability_override("bio_farm", None, None, {})
        assert bc.repair_cost_per_pct_city("bio_farm", 1, 1) == bc.DEFAULT_REPAIR_COST_PER_PCT[1]
    finally:
        bc.apply_durability_override("bio_farm", None, None, {})
