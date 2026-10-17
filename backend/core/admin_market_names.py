"""
ADMIN_MARKET_NICKS — pool of 200 plausible-looking player nicknames used as
the public `seller_username` when admin lists a resource on the market via
`/admin/market/bot-listing`. Replaces the giveaway "GRAM-City Bot" label so
ordinary players can't tell an admin-injected lot from a real player's lot.

A fresh random pick happens on every listing creation.
"""
import random

ADMIN_MARKET_NICKS = [
    "IvanMerchant", "AliceTrader", "MaxWolf", "Nikolay_77", "EvaGold",
    "DmitryStar", "OlgaMint", "PavelKnight", "SergeyKing", "AntonShadow",
    "RomanRiver", "AnnaPearl", "VladimirRex", "KseniaRose", "ArturBlitz",
    "MariaNova", "GregorVox", "TatianaSky", "MikhailFalcon", "ElenaCrown",
    "ArtemHawk", "SofiaLake", "BorisFlame", "VictorIce", "NadyaMoon",
    "FedorDream", "LisaStorm", "EgorBolt", "PolinaGem", "DenisPlasma",
    "YanaQuartz", "RuslanQuasar", "InnaWisp", "TimurZenith", "AlexaRune",
    "GleboMaster", "DariaWillow", "StasGalaxy", "MilaCipher", "OlegSpark",
    "VeraEclipse", "KirillRift", "SnejaShine", "BogdanForge", "RegimaWave",
    "MariusGrove", "EkateraPrism", "RostyaNeon", "ValeriDrift", "ArinaPulse",
    "FrostByte_77", "SilverFox22", "GoldenWolf", "EmeraldHawk", "ScarletRaven",
    "ObsidianMage", "TitaniumBear", "OrionStar", "PhantomKnight", "AlphaTrader",
    "OmegaTycoon", "DeltaFox", "ZetaWizard", "SigmaPanda", "NeonStriker",
    "QuantumPilot", "PlasmaCobra", "GalaxyNomad", "VortexHero", "AstralViking",
    "LunarPilot", "SolarBlaze", "StellaSpike", "EclipseDuke", "NovaSpirit",
    "MeteorByte", "PulsarBaron", "NebulaSaint", "CometKnight", "AsteroidEagle",
    "TraderJax", "MerchantOwl", "BronzeBison", "CrystalLynx", "DiamondHusky",
    "CoralPanda", "AmberShark", "JadeFalcon", "RubyOtter", "SapphireFox",
    "TopazBear", "OnyxRaven", "PearlEagle", "OpalLynx", "AmethystWolf",
    "GranitePilot", "MarbleRanger", "QuartzKnight", "BasaltWarden", "AgateHunter",
    "WolfRider99", "BearRunner21", "EagleSpark", "OwlGazer42", "RavenCaller",
    "FoxStrider", "LynxDrifter", "HawkPiercer", "OtterScout", "SharkScribe",
    "Tigron_KV", "DragonRose", "PhoenixVein", "GriffinFist", "BasiliskEye",
    "WyvernAce", "ChimeraDay", "CentaurSky", "SphynxCipher", "MinotaurFire",
    "ScribeNova", "ForgeBaron", "OracleVox", "MysticRune", "ArcaneSpur",
    "MysticIron", "RuneSeeker", "OracleByte", "SagaWanderer", "EpicForge",
    "NightOwlBR", "SunDriver12", "MoonWatch88", "DawnRider", "DuskRiver",
    "TwilightFox", "MidnightSpark", "AuroraBaron", "ZephyrLynx", "BorealStar",
    "TempestKnight", "MonsoonRider", "CycloneEagle", "AvalancheBear", "TyphoonHusky",
    "TundraFox", "PrairieWolf", "SavannahHawk", "JungleOtter", "DesertRaven",
    "AshenScribe", "EmberWraith", "CinderHowl", "EmberKing", "AshSpire",
    "FrostPaladin", "GlacierGale", "IceCrown_77", "WintergleamX", "BlizzardWolf",
    "ShadowDuke", "VoidStriker", "EclipseRune", "AbyssalFox", "ObsidianRaven",
    "CrimsonWave", "ScarletWisp", "VermilionBear", "MagentaPilot", "AzureHusky",
    "CobaltKnight", "IndigoOwl", "VioletScribe", "PlumRaven", "TangerineFox",
    "MerchantSky", "GuildArtisan", "BazaarLord", "ForgeMaster_77", "AnvilSpark",
    "HammerWatch", "AnchorEagle", "CompassRose", "MapMaker_42", "ChartSeer",
    "VeloceRanger", "RapidByte", "ChronoPilot", "TempoBear", "MetronomeWolf",
    "QuestKnight", "ValorOwl", "HonorRaven", "GloryFox", "RenownHusky",
    "LegendDraco", "MythRune", "FableSpike", "BalladKing", "SonnetSaint",
]

assert len(ADMIN_MARKET_NICKS) == 200, f"Expected 200 nicks, got {len(ADMIN_MARKET_NICKS)}"


def pick_admin_market_nick() -> str:
    """Return a random nickname from the 200-pool for an admin-injected market lot."""
    return random.choice(ADMIN_MARKET_NICKS)
