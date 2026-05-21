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
