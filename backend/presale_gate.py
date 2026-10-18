"""Presale gate — presale is the single source of truth for map purchases.

A plot on the map may be bought / staked (Level-0) ONLY when it belongs to the
currently ACTIVE presale allowlist (`selected_plots`). If there is no active
presale, or the active presale has no selected plots, or the plot is not in the
allowlist, the purchase is blocked everywhere and the admin's custom button text
is shown in place of the "Купить" button.

Admins bypass the gate so they can always test / manage the map.
"""


async def get_presale_doc(db):
    return await db.admin_settings.find_one({"type": "presale"}, {"_id": 0})


def presale_button_text(doc) -> str:
    """Global custom replacement text for the Buy button (stored as-is, no i18n).
    Empty string => frontend falls back to the default 'Купить' label."""
    return ((doc or {}).get("buy_button_text") or "").strip()


def _allowlist(doc, map_id):
    """Set of (x, y) coords buyable via the active presale for this map.
    Returns None when there is no active presale at all (=> block everywhere)."""
    if not doc or not doc.get("active"):
        return None
    if (doc.get("map_id") or "ton_island") != (map_id or "ton_island"):
        return set()
    return {(p.get("x"), p.get("y")) for p in (doc.get("selected_plots") or [])}


async def presale_allows(db, map_id, x, y, is_admin: bool = False):
    """Return (allowed: bool, button_text: str).

    Admins are always allowed. For everyone else the plot must be in the active
    presale allowlist. An empty / absent presale blocks all purchases."""
    doc = await get_presale_doc(db)
    btn = presale_button_text(doc)
    if is_admin:
        return True, btn
    allow = _allowlist(doc, map_id)
    if not allow:
        return False, btn
    return ((x, y) in allow), btn
