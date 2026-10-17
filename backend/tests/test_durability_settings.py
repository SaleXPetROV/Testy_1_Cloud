"""Admin durability settings: shifts per 100% and $CITY per 1% of repair (decimals allowed)."""
import business_config as bc


def test_defaults_and_overrides_with_decimals():
    bc.DURABILITY_OVERRIDES.clear()
    assert bc.get_daily_wear("helios", 1) == 0.30                     # default: 100% in 10 shifts
    assert bc.repair_cost_per_pct_city("helios", 1) == 1.0 and bc.repair_cost_per_pct_city("dex", 3) == 20.0
    bc.apply_durability_override("helios", shifts_per_100=12.5, repair_cost_per_pct_city=0.3)
    assert abs(bc.get_daily_wear("helios", 3) - 3 / 12.5) < 1e-9       # 100% in 12.5 shifts
    assert bc.repair_cost_per_pct_city("helios") == 0.3
    assert abs(bc.calculate_repair_cost("helios", 1, 10)["ton"] - 0.003) < 1e-9   # 10% * 0.3 $CITY = 3 $CITY = 0.003 TON
    e = bc.get_business_config_entry("helios")["durability"]
    assert e["shifts_per_100"] == 12.5 and e["repair_cost_per_pct_city"] == 0.3 and e["default_shifts_per_100"] == 10.0
    bc.apply_durability_override("helios", None, None)                # empty -> defaults again
    assert bc.get_daily_wear("helios", 1) == 0.30 and bc.repair_cost_per_pct_city("helios", 1) == 1.0
    bc.apply_durability_override("cold_storage", shifts_per_100=5)    # an alias name works too
    assert abs(bc.get_daily_wear("hydro_cooling", 1) - 0.6) < 1e-9
    bc.DURABILITY_OVERRIDES.clear()
