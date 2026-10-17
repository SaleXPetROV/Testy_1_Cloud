// Human name + effect of a tier-3 resource buff (e.g. «Разгон системы · +8% к производству»), any language.
import { fill } from '@/lib/translationsMore';

const EFFECT = { // effect value -> the % shown to the player
  production_multiplier: (v) => Math.round((v - 1) * 100),
  repair_cost_multiplier: (v) => Math.round((1 - v) * 100),
  trade_fee_multiplier: (v) => Math.round((1 - v) * 100),
  crit_chance_bonus: (v) => Math.round(v * 100),
  wear_reduction: (v) => Math.round((1 - v) * 100),
  consumption_multiplier: (v) => Math.round((1 - v) * 100),
  withdrawal_fee_multiplier: (v) => Math.round((1 - v) * 100),
};

export function buffTexts(b, t) {
  const id = String(b.resource || b.resource_id || '').replace(/_tutorial$/, '');
  const nameKey = `buffname_${id}`;
  const name = t(nameKey) !== nameKey ? t(nameKey) : (b.name && !/^[a-z_]+$/.test(b.name) ? b.name : id);
  const ek = `buffeff_${b.effect_type}`;
  const pct = EFFECT[b.effect_type] && b.effect_value != null ? EFFECT[b.effect_type](Number(b.effect_value)) : null;
  const effect = pct != null && t(ek) !== ek ? fill(t(ek), { v: pct }) : '';
  return { name, effect };
}
