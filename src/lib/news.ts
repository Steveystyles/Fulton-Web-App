/** Legacy merge helper retained for stored-data compatibility tests. News is no longer routed in the app. */
export function mergeNewsItems<T extends { id: number; updatedAt: string }>(current: T[], incoming: T[]): T[] {
  const merged = new Map(current.map(item => [item.id, item]));
  for (const item of incoming) {
    const existing = merged.get(item.id);
    if (!existing || Date.parse(item.updatedAt) >= Date.parse(existing.updatedAt)) merged.set(item.id, item);
  }
  return [...merged.values()];
}
