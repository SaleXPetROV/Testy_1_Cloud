"""
ADMIN_BUYOUT_NICKS — pool of 50 plausible-looking player nicknames used as the
public "buyer" identity when an admin buys out player resources from the P2P
market via `/admin/buyout/execute` (скупка «под левым именем»).

A fresh random pick happens for every purchased lot when the admin chooses the
auto-distribution masking mode.
"""
import random

ADMIN_BUYOUT_NICKS = [
    "Alex_TON", "MarketWhale", "SilentBuyer", "CryptoOtter", "NovaMerchant",
    "IvanTrader", "DeepPockets", "GhostBidder", "OmniByte", "RublePanda",
    "QuietFox", "GoldenBid", "PixelBaron", "SwiftTaker", "ShadowMerch",
    "LunaBuyer", "IronVault", "NeonPurse", "CoolHands99", "MegaHodler",
    "ArtemStock", "TitanBuyer", "VerdeMint", "SableFox", "OrbitTrade",
    "MaxLiquidity", "FrostBid", "ZenMerchant", "PolarTaker", "EchoVault",
    "RavenDeal", "SolarBid", "CobaltBuyer", "MintCondor", "ApexPurse",
    "GraniteBid", "SilverStag", "OnyxBuyer", "PrimeTaker", "DriftMerch",
    "HollowBid", "AtlasVault", "CedarTrade", "VoltPurse", "NimbusBuyer",
    "QuartzBid", "EmberTaker", "AzureMerch", "TundraFox", "OpalVault",
]

assert len(ADMIN_BUYOUT_NICKS) == 50, f"Expected 50 nicks, got {len(ADMIN_BUYOUT_NICKS)}"
assert not any("demo" in n.lower() or "test" in n.lower() for n in ADMIN_BUYOUT_NICKS), \
    "Buyer nicks must not contain 'demo'/'test' substrings"


def pick_buyout_nick() -> str:
    """Return a random nickname from the 50-pool for an admin buyout purchase."""
    return random.choice(ADMIN_BUYOUT_NICKS)
