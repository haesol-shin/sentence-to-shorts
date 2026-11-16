/** A forced visual state, used by the gallery. Never used in a real screen. */
export type ForceState = string | readonly string[];

/** One splitter for the gallery's state strings and arrays. */
export function statesOf(value?: ForceState): readonly string[] {
  if (value === undefined) return [];
  return typeof value === 'string' ? value.split(/\s+/).filter(Boolean) : value;
}
