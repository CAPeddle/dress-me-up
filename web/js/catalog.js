// The web version's end of the content contract (R8): the pipeline writes
// catalog.json and bodies.json into the assets directory, this module reads them.
// Both files carry the same build id and scale block; a pair from different
// builds is refused rather than drawn mis-scaled (KTD4).

// Slot categories in the pipeline's order (dressup_pipeline/models.py CATEGORIES).
export const CATEGORY_ORDER = Object.freeze([
  "hat", "hair", "top", "bottom", "dress", "shoes",
  "weapon", "shield", "accessory", "wings", "mount",
]);

export class ContentError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "ContentError";
    this.code = code; // "missing" | "invalid" | "build-mismatch"
  }
}

// Returns the shared build id, or throws when the two files disagree.
export function checkBuildIds(catalog, bodies) {
  const a = catalog && catalog.build_id;
  const b = bodies && bodies.build_id;
  if (typeof a !== "string" || typeof b !== "string" || a === "" || b === "") {
    throw new ContentError("invalid", "a content file has no build id");
  }
  if (a !== b) {
    throw new ContentError("build-mismatch", `catalog build ${a} does not match bodies build ${b}`);
  }
  return a;
}

// An image path from a content file, made relative to the served assets root.
export function resolveImage(baseUrl, image) {
  if (typeof image !== "string" || image === "" || image.startsWith("/") || image.includes("..")) {
    throw new ContentError("invalid", `bad image path ${JSON.stringify(image)}`);
  }
  return baseUrl.endsWith("/") ? baseUrl + image : `${baseUrl}/${image}`;
}

// Items grouped by category in the pipeline's order, keeping each item's index
// into the served list (the only identity the recording layer may see).
// Categories the order does not name come last, in first-seen order.
export function groupByCategory(items, order = CATEGORY_ORDER) {
  const groups = new Map();
  for (const category of order) groups.set(category, []);
  items.forEach((item, index) => {
    if (!groups.has(item.category)) groups.set(item.category, []);
    groups.get(item.category).push({ index, item });
  });
  return [...groups]
    .filter(([, entries]) => entries.length > 0)
    .map(([category, entries]) => ({ category, entries }));
}

async function fetchJson(url) {
  let response;
  try {
    response = await fetch(url, { cache: "no-cache" });
  } catch (err) {
    throw new ContentError("missing", `${url} could not be fetched`);
  }
  if (!response.ok) {
    throw new ContentError("missing", `${url} is missing (${response.status})`);
  }
  try {
    return await response.json();
  } catch (err) {
    throw new ContentError("invalid", `${url} is not valid JSON`);
  }
}

export async function loadContent(baseUrl = "assets/") {
  const [catalog, bodies] = await Promise.all([
    fetchJson(resolveImage(baseUrl, "catalog.json")),
    fetchJson(resolveImage(baseUrl, "bodies.json")),
  ]);
  if (!Array.isArray(catalog.items)) throw new ContentError("invalid", "catalog.json has no items list");
  if (!Array.isArray(bodies.bodies)) throw new ContentError("invalid", "bodies.json has no bodies list");
  const buildId = checkBuildIds(catalog, bodies);
  const withImage = (entry) => ({ ...entry, image: resolveImage(baseUrl, entry.image) });
  return {
    buildId,
    scale: catalog.scale || bodies.scale || null,
    bodies: bodies.bodies.map(withImage),
    items: catalog.items.map(withImage),
  };
}
