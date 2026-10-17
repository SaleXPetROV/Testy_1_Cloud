/**
 * Global price/amount upper bound used across the app.
 *
 * Anywhere a user types a "цена" or "сумма" (sell resource, sell business,
 * take credit, repay credit, post tender, post sell-offer, deposit/withdraw)
 * we clamp the input to this value to prevent silly billion+ inputs that
 * either trip server-side validation or DOS the formatter.
 *
 * 1_000_000_000 ($CITY / TON / units depending on context) is high enough
 * to never block a legit play and low enough to stop accidental "stars on
 * the keyboard" overflows.
 */
export const MAX_PRICE_VALUE = 1_000_000_000;

/**
 * Clamp a numeric input to [0, MAX_PRICE_VALUE]. Accepts the raw onChange
 * value (string|number). Returns the same shape:
 *   - if input is a string, returns a clamped string (preserves empty input)
 *   - if input is a number, returns a clamped number
 *
 * NaN/empty are passed through unchanged so the user can clear the field.
 */
export function clampPriceValue(value) {
  if (value === '' || value === null || value === undefined) return value;
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return value;
    if (value > MAX_PRICE_VALUE) return MAX_PRICE_VALUE;
    if (value < 0) return 0;
    return value;
  }
  // string path — keep raw if not parseable so the user can keep typing
  const num = Number(value);
  if (!Number.isFinite(num)) return value;
  if (num > MAX_PRICE_VALUE) return String(MAX_PRICE_VALUE);
  if (num < 0) return '0';
  return value;
}

/**
 * onChange wrapper that clamps the raw input value before calling the setter.
 * Use it like:
 *   <Input onChange={onClampedChange(setPrice)} max={MAX_PRICE_VALUE} />
 */
export function onClampedChange(setter) {
  return (e) => setter(clampPriceValue(e.target.value));
}
