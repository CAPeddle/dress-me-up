// Saved state (KTD7): one versioned localStorage key, written on every commit,
// read once and defensively. The state holds only integer indices into the
// served content, positions, stacking order, done marks and name indices; never
// free text, never a content id.
//
// The stored shape, which is also the in-memory state:
//   { version: 1, build_id, placements: [{ item, body, x, y, z }], done: [bool per body], names: [int per body, -1 for none] }
//
// Indices are meaningless across content builds: item 3 in one build is any
// other Item in the next, so a store carrying a different build_id is treated as
// fresh rather than dressing the wrong bodies with the wrong Items. Every index
// is also bounded against the content actually served, since a build id alone
// cannot tell that the catalog behind it shrank.

export const STORE_KEY = "dressmeup.v1";
export const VERSION = 1;

export function freshState({ buildId, bodyCount }) {
  return {
    version: VERSION,
    build_id: buildId,
    placements: [],
    done: Array.from({ length: bodyCount }, () => false),
    names: Array.from({ length: bodyCount }, () => -1),
  };
}

export function serialize(state) {
  return JSON.stringify({
    version: state.version,
    build_id: state.build_id,
    placements: state.placements.map(({ item, body, x, y, z }) => ({ item, body, x, y, z })),
    done: state.done.slice(),
    names: state.names.slice(),
  });
}

const isIndex = (v) => Number.isInteger(v) && v >= 0;
const isNameIndex = (v) => Number.isInteger(v) && v >= -1;

// A bound a stored index is checked against. Missing one is a caller's mistake,
// not a malformed store: `4 >= undefined` is false, so an absent bound would
// wave every index through instead of rejecting it.
function requireCount(value, name) {
  if (!Number.isInteger(value) || value < 0) {
    throw new TypeError(`${name} must be a non-negative integer`);
  }
}

// A state from stored text, or null when the text is not a state of this
// version and build, or names content that is not there; anything malformed is
// null too, never a partial state.
export function deserialize(text, { buildId, bodyCount, itemCount }) {
  requireCount(bodyCount, "bodyCount");
  requireCount(itemCount, "itemCount");
  let raw;
  try {
    raw = JSON.parse(text);
  } catch (err) {
    return null;
  }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  if (raw.version !== VERSION || raw.build_id !== buildId) return null;
  if (!Array.isArray(raw.placements) || !Array.isArray(raw.done) || !Array.isArray(raw.names)) return null;
  if (raw.done.length !== bodyCount || raw.names.length !== bodyCount) return null;
  if (!raw.done.every((d) => typeof d === "boolean") || !raw.names.every(isNameIndex)) return null;
  const placements = [];
  for (const p of raw.placements) {
    if (!p || typeof p !== "object") return null;
    const { item, body, x, y, z } = p;
    if (!isIndex(item) || item >= itemCount) return null;
    if (!isIndex(body) || body >= bodyCount) return null;
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isInteger(z)) return null;
    placements.push({ item, body, x, y, z });
  }
  return { version: VERSION, build_id: buildId, placements, done: raw.done.slice(), names: raw.names.slice() };
}

// Reads the store once. Missing, throwing, unparseable, wrong version, a
// different build or an index past the served content all mean a fresh state.
export function load({ buildId, bodyCount, itemCount }) {
  requireCount(bodyCount, "bodyCount");
  requireCount(itemCount, "itemCount");
  let text = null;
  try {
    text = window.localStorage.getItem(STORE_KEY);
  } catch (err) {
    text = null;
  }
  const stored = text !== null && deserialize(text, { buildId, bodyCount, itemCount });
  return stored || freshState({ buildId, bodyCount });
}

// Writes the state; a throwing store (disabled, full) loses the save and nothing else.
export function save(state) {
  try {
    window.localStorage.setItem(STORE_KEY, serialize(state));
  } catch (err) {
    /* play goes on without a save */
  }
}
