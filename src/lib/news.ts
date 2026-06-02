export const newsFallbackRefreshMs = 10 * 60 * 1000;

export function cleanNewsTitle(title: string, source: string) {
  const trimmedTitle = title.trim();
  const trimmedSource = source.trim();

  if (!trimmedSource) {
    return trimmedTitle;
  }

  const escapedSource = trimmedSource.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return trimmedTitle
    .replace(new RegExp(`\\s[-|:]+\\s${escapedSource}$`, "i"), "")
    .replace(new RegExp(`\\s\\(${escapedSource}\\)$`, "i"), "")
    .replace(new RegExp(`^${escapedSource}\\s[-|:]+\\s`, "i"), "")
    .trim();
}

function normaliseNewsText(value: string) {
  return value.toLocaleLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

export function cleanNewsSummary(summary: string, title: string, source: string) {
  const cleanTitle = cleanNewsTitle(title, source);
  const trimmedSource = source.trim();
  const escapedSource = trimmedSource.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const cleanedSummary = summary
    .trim()
    .replace(trimmedSource ? new RegExp(`\\s+${escapedSource}$`, "i") : /$^/, "")
    .trim();
  const summaryKey = normaliseNewsText(cleanedSummary);
  const titleKey = normaliseNewsText(cleanTitle);

  if (
    !summaryKey ||
    summaryKey === titleKey ||
    (summaryKey.length >= 24 &&
      (summaryKey.startsWith(titleKey) || titleKey.startsWith(summaryKey)))
  ) {
    return "";
  }
  return cleanedSummary;
}

export function newsStoryKey(title: string, source: string) {
  return normaliseNewsText(cleanNewsTitle(title, source));
}

export function visibleNewsTags(tags: string[]) {
  const hiddenTags = new Set([
    "breaking",
    "live-scores",
    "news",
    "scottish-football",
    "st-mirren",
  ]);
  return tags.filter((tag) => !hiddenTags.has(tag.toLocaleLowerCase())).slice(0, 3);
}
