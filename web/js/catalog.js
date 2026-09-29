// The web version's end of the content contract (R8): the pipeline writes
// catalog.json and bodies.json into the assets directory, this module reads them.
// Both files carry the same build id and scale block; a pair from different
// builds is refused rather than drawn mis-scaled (KTD4).

// Slot categories in the pipeline's order (dressup_pipeline/models.py CATEGORIES).
export const CATEGORY_ORDER = Object.freeze([
  "hat", "hair", "top", "bottom", "dress", "shoes",
  "weapon", "shield", "accessory", "wings", "companion", "mount",
]);

export class ContentError extends Error {
  constructor(message) {
    super(message);
    this.name = "ContentError";
  }
}

// Returns the shared build id, or throws when the two files disagree.
export function checkBuildIds(catalog, bodies) {
  const a = catalog && catalog.build_id;
  const b = bodies && bodies.build_id;
  if (typeof a !== "string" || typeof b !== "string" || a === "" || b === "") {
    throw new ContentError("a content file has no build id");
  }
  if (a !== b) {
    throw new ContentError(`catalog build ${a} does not match bodies build ${b}`);
  }
  return a;
}

// A path from inside the content, resolved against the served assets root: the
// two content files themselves as well as every image they name. Same-origin and
// relative by construction, so a content file can never point the page elsewhere.
export function resolveContentPath(baseUrl, path) {
  if (typeof path !== "string" || path === "" || path.startsWith("/") || path.includes("..")) {
    throw new ContentError(`bad image path ${JSON.stringify(path)}`);
  }
  return baseUrl.endsWith("/") ? baseUrl + path : `${baseUrl}/${path}`;
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
    throw new ContentError(`${url} could not be fetched`);
  }
  if (!response.ok) {
    throw new ContentError(`${url} is missing (${response.status})`);
  }
  try {
    return await response.json();
  } catch (err) {
    throw new ContentError(`${url} is not valid JSON`);
  }
}

export async function loadContent(baseUrl = "assets/") {
  const [catalog, bodies] = await Promise.all([
    fetchJson(resolveContentPath(baseUrl, "catalog.json")),
    fetchJson(resolveContentPath(baseUrl, "bodies.json")),
  ]);
  if (!Array.isArray(catalog.items)) throw new ContentError("catalog.json has no items list");
  if (!Array.isArray(bodies.bodies)) throw new ContentError("bodies.json has no bodies list");
  const buildId = checkBuildIds(catalog, bodies);
  const withImage = (entry) => ({ ...entry, image: resolveContentPath(baseUrl, entry.image) });
  return {
    buildId,
    scale: catalog.scale || bodies.scale || null,
    bodies: bodies.bodies.map(withImage),
    items: catalog.items.map(withImage),
  };
}
