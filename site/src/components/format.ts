export const base = '/own-the-machine-weekly/';
export const link = (path = '') => base + path.replace(/^\//, '');
export const pct = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? '—' : `${value > 0 ? '+' : ''}${(value * 100).toFixed(2)}%`;
export const score = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? '—' : Math.round(value * 100).toString();
export const number = (value: number | null | undefined, digits = 1) => value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits);
export const gateLabels: Record<string,string> = {g1_price_above_150_200:'Price above 150 & 200-day averages',g2_sma150_above_sma200:'150-day above 200-day average',g3_sma200_trending_up:'200-day average rising',g4_sma50_above_150_200:'50-day above longer averages',g5_price_above_sma50:'Price above 50-day average',g6_30pct_above_52w_low:'At least 30% above annual low',g7_within_25pct_of_52w_high:'Within 25% of annual high',g8_rs_rating_ge_70:'Broad-market RS at least 70'};
export const date = (value: string) => new Date(value + 'T12:00:00Z').toLocaleDateString('en-GB', {day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC'});
export const shortDate = (value: string) => new Date(value + 'T12:00:00Z').toLocaleDateString('en-GB', {day: 'numeric', month: 'short', timeZone: 'UTC'});
export const cleanTitle = (story: any) => story.title.endsWith(` - ${story.source_name}`) ? story.title.slice(0, -story.source_name.length - 3) : story.title;
export function spark(bars: any[] = []) {
  if (bars.length < 2) return '';
  const values = bars.map(b => b.close), lo = Math.min(...values), hi = Math.max(...values);
  return values.map((v, i) => `${(i / (values.length - 1) * 140).toFixed(1)},${(38 - ((v - lo) / (hi - lo || 1)) * 32).toFixed(1)}`).join(' ');
}
