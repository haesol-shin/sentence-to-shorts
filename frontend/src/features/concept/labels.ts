/** The locale's name for a settings value, falling back to the raw value. */
export function valueLabel(value: unknown, t: (key: string) => string): string {
  if (value === null || value === undefined) return t('concept.value.none');
  if (typeof value === 'object') {
    if ('id' in value) return valueLabel(value.id, t);
    return Object.entries(value).map(([key, part]) => `${key}: ${valueLabel(part, t)}`).join(', ');
  }
  const key = `concept.value.${String(value)}`;
  const label = t(key);
  return label === key ? String(value) : label;
}
