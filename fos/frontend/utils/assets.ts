const rawBaseUrl = String(import.meta.env.BASE_URL || "/").trim();

const normalizedBaseUrl =
  rawBaseUrl === "/"
    ? "/"
    : rawBaseUrl.endsWith("/")
      ? rawBaseUrl
      : `${rawBaseUrl}/`;

const tutorialAssetModules = import.meta.glob("../assets/tutorial/*.{png,jpg,jpeg,gif,webp,svg,mp4,webm}", {
  eager: true,
  import: "default",
}) as Record<string, string>;

const tutorialAssetMap = Object.entries(tutorialAssetModules).reduce<Record<string, string>>((map, [modulePath, assetUrl]) => {
  const [, tutorialRelativePath = ""] = modulePath.split("/assets/tutorial/");

  if (!tutorialRelativePath) {
    return map;
  }

  map[`tutorial/${tutorialRelativePath}`] = assetUrl;
  map[`/tutorial/${tutorialRelativePath}`] = assetUrl;
  return map;
}, {});

export function resolveStaticAssetPath(path: string) {
  if (!path) {
    return path;
  }

  if (/^(https?:)?\/\//.test(path) || path.startsWith("data:") || path.startsWith("blob:")) {
    return path;
  }

  if (path.startsWith("/uploads/")) {
    return path;
  }

  const [cleanPath, suffix = ""] = path.split(/([?#].*)/, 2);
  const bundledTutorialAssetUrl = tutorialAssetMap[cleanPath];

  if (bundledTutorialAssetUrl) {
    return `${bundledTutorialAssetUrl}${suffix}`;
  }

  if (
    cleanPath.startsWith("/tutorial/") ||
    cleanPath.startsWith("tutorial/") ||
    cleanPath.startsWith("/docs/") ||
    cleanPath.startsWith("docs/")
  ) {
    const relativePath = cleanPath.replace(/^\/+/, "");
    return `${normalizedBaseUrl}${relativePath}`;
  }

  return path;
}
