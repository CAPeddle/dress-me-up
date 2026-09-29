// The wall: every extracted item as a thumbnail, filed into buckets by keystroke,
// emptying as the pass is done (R1, R2, R3). The server has already ordered the
// corpus by the classifier's guess and already said which items are filed, so this
// module never matches geometry and never sorts by suggestion itself — it draws a
// window of one list, tracks what is selected, and turns a keystroke into a batch.
//
// One continuous list, windowed (KTD8). Numbered pages were the alternative and
// are the one thing the completion signal cannot survive: an empty page reads
// exactly like an empty wall, and an empty wall is how this pass says it is done.

import { WallError, buildKeyMap, createQueue } from "./filing.js";

const MANIFEST_URL = "/api/corpus";
const CORRECTIONS_URL = "/api/corrections";

// Tile geometry, owned here and handed to the stylesheet, because the window
// arithmetic needs the same numbers the layout uses and two copies would drift.
const TILE_W = 152;
const TILE_H = 176;
const GAP = 12;
// Two rows either side of the viewport, so a flick of the wheel does not scroll
// past the render.
const OVERSCAN = 2;

const root = document.documentElement;
const statusEl = document.querySelector("[data-wall-region='status']");
const legendEl = document.querySelector("[data-wall-region='legend']");
const messageEl = document.querySelector("[data-wall-region='message']");
const wallEl = document.querySelector("[data-wall-region='wall']");
const canvasEl = wallEl.querySelector(".canvas");
const enlargeEl = document.querySelector("[data-wall-region='enlarge']");
const filedEl = document.querySelector("[data-wall-region='filed']");

const state = {
  items: [],            // every extracted item, in the manifest's order
  byId: new Map(),
  keys: null,
  filed: new Map(),     // item_id -> {category, rejection}: the verdict now believed
  wall: [],             // the unfiled items, derived from `filed` on every change
  selected: new Set(),
  anchor: -1,           // index into `wall` a shift-click runs from
  focus: null,          // the item an enlarge would show
  picked: new Set(),    // the selection inside the filed view
  pickedAnchor: -1,
  undos: [],            // one entry per filing action: what each item was before
  failure: null,        // a write the person has not been told about yet
};

// The live window: item id -> its tile, so scrolling reuses nodes and a thumbnail
// already decoded is not fetched again.
const live = new Map();
let columns = 1;
let rows = 0;

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child);
  return node;
}

// ---------------------------------------------------------------- the manifest

async function loadCorpus() {
  let response;
  try {
    response = await fetch(MANIFEST_URL, { cache: "no-cache" });
  } catch (error) {
    throw new WallError("the corpus could not be fetched; is the server still running?");
  }
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const body = await response.json();
      if (body && body.error) detail = body.error;
    } catch (error) {
      // A refusal that is not JSON is still a refusal; the status says enough.
    }
    throw new WallError(`the corpus could not be read: ${detail}`);
  }
  let manifest;
  try {
    manifest = await response.json();
  } catch (error) {
    throw new WallError("the corpus is not valid JSON");
  }
  if (!Array.isArray(manifest.items)) throw new WallError("the corpus has no items list");
  if (!Array.isArray(manifest.categories) || !Array.isArray(manifest.rejections)) {
    throw new WallError("the corpus names no categories to file into");
  }
  return manifest;
}

// ---------------------------------------------------------------- the one write

async function postFilings(payload) {
  let response;
  try {
    response = await fetch(CORRECTIONS_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      // Keepalive, because the tab going into the background flushes through here:
      // the answer is still wanted, and the request has to outlive a tab the
      // platform then decides to freeze. A batch is a dozen short records, far
      // under the size a keepalive request is allowed.
      keepalive: true,
    });
  } catch (error) {
    throw new WallError("the server could not be reached; nothing was filed");
  }
  let body = null;
  try {
    body = await response.json();
  } catch (error) {
    body = null;
  }
  if (response.ok) return body || { written: [], failed: [] };
  // A 500 names the books that did not land and the ones that did, so it is an
  // answer rather than an error. Everything else refused the whole batch.
  if (body && Array.isArray(body.failed) && body.failed.length) return body;
  throw new WallError((body && body.error) || `the write was refused (${response.status})`);
}

function beaconFilings(payload) {
  const body = JSON.stringify(payload);
  const blob = new Blob([body], { type: "application/json" });
  if (navigator.sendBeacon && navigator.sendBeacon(CORRECTIONS_URL, blob)) return;
  // No beacon: a keepalive fetch outlives the document too, and there is no answer
  // to read either way.
  fetch(CORRECTIONS_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    keepalive: true,
  }).catch(() => {});
}

const queue = createQueue({
  send: postFilings,
  sendOnHide: beaconFilings,
  onChange: paintStatus,
  onFailure: (message) => {
    state.failure = message;
    refresh();
  },
  onSettled: () => {
    if (state.failure === null) return;
    state.failure = null;
    refresh();
  },
});

// ---------------------------------------------------------------- derived state

function rebuildWall() {
  state.wall = state.items.filter((item) => !state.filed.has(item.item_id));
  for (const id of [...state.selected]) if (state.filed.has(id)) state.selected.delete(id);
  for (const id of [...state.picked]) if (!state.filed.has(id)) state.picked.delete(id);
}

function refresh() {
  rebuildWall();
  layout();
  renderWindow();
  paintStatus();
  paintMessage();
  if (!filedEl.hidden) renderFiled();
}

// ---------------------------------------------------------------- the window

function layout() {
  const width = canvasEl.clientWidth || wallEl.clientWidth;
  columns = Math.max(1, Math.floor((width + GAP) / (TILE_W + GAP)));
  rows = Math.ceil(state.wall.length / columns);
  canvasEl.style.height = `${Math.max(rows * (TILE_H + GAP) - GAP, 0)}px`;
}

function tileFor(item) {
  const node = el(
    "div",
    {
      class: "tile",
      "data-wall-kind": "tile",
      "data-wall-item": item.item_id,
      "data-wall-suggestion": item.suggestion === null ? "none" : item.suggestion,
      "data-wall-selected": "false",
    },
    [
      el("img", { src: item.thumb, alt: "", draggable: "false", decoding: "async" }),
      el("span", { class: "tag", text: item.suggestion === null ? "no guess" : item.suggestion }),
    ],
  );
  // The 80 QA rejections are all for being small and a hair clip is legitimately
  // small, so the mark is a hint to look closer, never a reason to skip the item.
  if (item.accepted === false) node.classList.add("unaccepted");
  node.addEventListener("click", (event) => selectOnWall(item.item_id, event.shiftKey));
  return node;
}

function renderWindow() {
  const rowHeight = TILE_H + GAP;
  const firstRow = Math.max(0, Math.floor(wallEl.scrollTop / rowHeight) - OVERSCAN);
  const lastRow = Math.min(rows - 1, Math.floor((wallEl.scrollTop + wallEl.clientHeight) / rowHeight) + OVERSCAN);
  const from = firstRow * columns;
  const to = Math.min(state.wall.length, (lastRow + 1) * columns);

  const wanted = state.wall.slice(Math.max(from, 0), Math.max(to, 0));
  const keep = new Set(wanted.map((item) => item.item_id));
  for (const [id, node] of live) {
    if (keep.has(id)) continue;
    node.remove();
    live.delete(id);
  }
  wanted.forEach((item, offset) => {
    const index = from + offset;
    let node = live.get(item.item_id);
    if (node === undefined) {
      node = tileFor(item);
      live.set(item.item_id, node);
    }
    node.dataset.wallSelected = state.selected.has(item.item_id) ? "true" : "false";
    node.classList.toggle("focused", state.focus === item.item_id);
    node.style.transform = `translate(${(index % columns) * (TILE_W + GAP)}px, ${
      Math.floor(index / columns) * (TILE_H + GAP)
    }px)`;
    // Appended in wall order every pass, so the DOM reads in the order the eye
    // does even after a run has been filed out of the middle of it.
    canvasEl.append(node);
  });
}

// ---------------------------------------------------------------- selection

function selectOnWall(itemId, extend) {
  const index = state.wall.findIndex((item) => item.item_id === itemId);
  if (index < 0) return;
  if (extend && state.anchor >= 0 && state.anchor < state.wall.length) {
    const [from, to] = state.anchor <= index ? [state.anchor, index] : [index, state.anchor];
    state.selected = new Set(state.wall.slice(from, to + 1).map((item) => item.item_id));
  } else {
    state.selected = new Set([itemId]);
    state.anchor = index;
  }
  state.focus = itemId;
  state.picked.clear();
  renderWindow();
  paintStatus();
}

function selectInFiled(itemId, extend) {
  const order = filedOrder();
  const index = order.indexOf(itemId);
  if (index < 0) return;
  if (extend && state.pickedAnchor >= 0 && state.pickedAnchor < order.length) {
    const [from, to] = state.pickedAnchor <= index ? [state.pickedAnchor, index] : [index, state.pickedAnchor];
    state.picked = new Set(order.slice(from, to + 1));
  } else {
    state.picked = new Set([itemId]);
    state.pickedAnchor = index;
  }
  state.focus = itemId;
  state.selected.clear();
  renderWindow();
  renderFiled();
  paintStatus();
}

// ---------------------------------------------------------------- filing

function entryFor(itemId, filing, previous) {
  const item = state.byId.get(itemId);
  return {
    item_id: itemId,
    source_pdf: item.source_pdf,
    filing,
    // What the page has to go back to when the server refuses. An undo of a
    // reverted filing is then a no-op on both the page and the file, which is the
    // right answer rather than a second thing to explain.
    revert: () => {
      if (previous === null) state.filed.delete(itemId);
      else state.filed.set(itemId, previous);
    },
  };
}

function fileSelection(action) {
  const fromFiled = !filedEl.hidden && state.picked.size > 0;
  const ids = fromFiled ? [...state.picked] : [...state.selected];
  if (ids.length === 0) return;
  const verdict =
    action.kind === "category" ? { category: action.name } : { rejection: action.name };
  const undo = [];
  const entries = [];
  for (const id of ids) {
    const previous = state.filed.get(id) || null;
    undo.push({ item_id: id, previous });
    state.filed.set(id, { category: verdict.category || null, rejection: verdict.rejection || null });
    entries.push(entryFor(id, { item_id: id, ...verdict }, previous));
  }
  state.undos.push(undo);
  // The enlarge is opened to judge one item; once that judgement is filed it is
  // showing a verdict that has already been given.
  enlargeEl.hidden = true;
  if (fromFiled) state.picked.clear();
  else {
    state.selected.clear();
    state.anchor = -1;
  }
  refresh();
  queue.add(entries);
}

// One keystroke back out of a whole run: run filing means one mis-key can misfile
// dozens at once, and hunting each of them back through the filed view is the
// expensive recovery this exists to avoid (R6).
function undoLast() {
  const last = state.undos.pop();
  if (last === undefined) return;
  const entries = [];
  for (const { item_id: itemId, previous } of last) {
    const current = state.filed.get(itemId) || null;
    if (previous === null) state.filed.delete(itemId);
    else state.filed.set(itemId, previous);
    const filing =
      previous === null
        ? { item_id: itemId, unfile: true }
        : {
            item_id: itemId,
            ...(previous.category === null ? { rejection: previous.rejection } : { category: previous.category }),
          };
    entries.push(entryFor(itemId, filing, current));
  }
  refresh();
  queue.add(entries);
  // The recovery keystroke does not wait on the batch interval: the person is
  // watching to see the run come back, and the file has to agree with the wall.
  queue.flush();
}

// ---------------------------------------------------------------- the chrome

function paintStatus() {
  statusEl.dataset.wallRemaining = String(state.wall.length);
  statusEl.dataset.wallFiled = String(state.filed.size);
  statusEl.dataset.wallQueued = String(queue.pending());
  const selected = state.selected.size || state.picked.size;
  statusEl.querySelector(".remaining").textContent = `${state.wall.length} left`;
  statusEl.querySelector(".filed").textContent = `${state.filed.size} filed`;
  const queued = queue.pending();
  statusEl.querySelector(".queued").textContent = [
    queued > 0 ? `${queued} saving` : "saved",
    selected > 0 ? `${selected} selected` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

function paintMessage() {
  if (state.failure !== null) {
    messageEl.textContent = `Not filed: ${state.failure}. Those items are back on the wall.`;
    messageEl.dataset.wallFailed = "write";
    delete messageEl.dataset.wallEmpty;
    messageEl.hidden = false;
    return;
  }
  delete messageEl.dataset.wallFailed;
  if (state.items.length === 0) {
    messageEl.textContent = "There is nothing extracted to label yet.";
    messageEl.dataset.wallEmpty = "corpus";
    messageEl.hidden = false;
    return;
  }
  if (state.wall.length === 0) {
    messageEl.textContent = "Every item is filed — this pass is finished.";
    messageEl.dataset.wallEmpty = "finished";
    messageEl.hidden = false;
    return;
  }
  delete messageEl.dataset.wallEmpty;
  messageEl.hidden = true;
}

function failLoad(message) {
  state.failure = null;
  messageEl.textContent = message;
  messageEl.dataset.wallFailed = "load";
  delete messageEl.dataset.wallEmpty;
  messageEl.hidden = false;
  root.dataset.wall = "failed";
}

// Every action is on the page, because nobody sorting several hundred items holds
// fifteen keys in their head (KTD10).
function renderLegend() {
  legendEl.replaceChildren(
    ...state.keys.entries.map((entry) =>
      el(
        "span",
        {
          class: `legend-entry ${entry.kind}`,
          "data-wall-kind": "legend-entry",
          "data-wall-action": entry.name,
          "data-wall-action-kind": entry.kind,
          "data-wall-key": entry.key,
        },
        [
          el("kbd", { class: "key", text: entry.key }),
          el("span", { class: "name", text: entry.name.replace(/_/g, " ") }),
        ],
      ),
    ),
  );
}

// ---------------------------------------------------------------- the overlays

function verdictName(verdict) {
  return verdict.category === null ? verdict.rejection : verdict.category;
}

function filedOrder() {
  // Bucket by bucket in the pipeline's order, so the flat order the filed view
  // shows is the order a shift-click runs along.
  const buckets = new Map(
    state.keys.entries.filter((entry) => entry.kind !== "command").map((entry) => [entry.name, []]),
  );
  for (const item of state.items) {
    const verdict = state.filed.get(item.item_id);
    if (verdict === undefined) continue;
    const bucket = buckets.get(verdictName(verdict));
    if (bucket !== undefined) bucket.push(item.item_id);
  }
  return [...buckets.values()].flat();
}

// What has been filed, grouped by bucket, so an older item can be found and
// re-filed rather than edited into the file by hand (R6).
function renderFiled() {
  const order = filedOrder();
  if (order.length === 0) {
    filedEl.replaceChildren(el("p", { class: "note", text: "Nothing filed yet." }));
    return;
  }
  const buckets = new Map();
  for (const itemId of order) {
    const name = verdictName(state.filed.get(itemId));
    if (!buckets.has(name)) buckets.set(name, []);
    buckets.get(name).push(itemId);
  }
  filedEl.replaceChildren(
    ...[...buckets].map(([name, ids]) =>
      el(
        "section",
        { class: "bucket", "data-wall-kind": "bucket", "data-wall-bucket": name },
        [
          el("h2", { class: "bucket-name", text: `${name.replace(/_/g, " ")} (${ids.length})` }),
          el(
            "div",
            { class: "bucket-tiles" },
            ids.map((itemId) => {
              const item = state.byId.get(itemId);
              const node = el(
                "div",
                {
                  class: "tile filed-tile",
                  "data-wall-kind": "filed-tile",
                  "data-wall-item": itemId,
                  "data-wall-selected": state.picked.has(itemId) ? "true" : "false",
                },
                // Lazy, because a finished pass has every item in here and the
                // whole corpus decoded at once is the thing the wall windows to avoid.
                [el("img", { src: item.thumb, alt: "", loading: "lazy", draggable: "false" })],
              );
              node.addEventListener("click", (event) => selectInFiled(itemId, event.shiftKey));
              return node;
            }),
          ),
        ],
      ),
    ),
  );
}

function toggleFiled() {
  if (filedEl.hidden) {
    renderFiled();
    filedEl.hidden = false;
  } else {
    filedEl.hidden = true;
    state.picked.clear();
    paintStatus();
  }
}

// The original cutout, not the thumbnail (KTD7): a 44x56 cutout is a guess at
// thumbnail size, and guessing is what this pass exists to stop.
function toggleEnlarge() {
  if (!enlargeEl.hidden) {
    enlargeEl.hidden = true;
    return;
  }
  const itemId = state.focus;
  if (itemId === null || !state.byId.has(itemId)) return;
  const item = state.byId.get(itemId);
  const filed = state.filed.get(itemId);
  enlargeEl.replaceChildren(
    el("img", { class: "enlarged", "data-wall-kind": "enlarged", src: item.source, alt: "" }),
    el("p", {
      class: "note",
      text: [
        `${item.bbox.w}x${item.bbox.h} on page ${item.page + 1} of ${item.source_pdf}`,
        item.suggestion === null ? "no guess" : `guessed ${item.suggestion}`,
        filed === undefined ? "unfiled" : `filed as ${verdictName(filed)}`,
      ].join(" · "),
    }),
  );
  enlargeEl.hidden = false;
}

// ---------------------------------------------------------------- the keyboard

function onKeyDown(event) {
  // Ctrl-R still reloads and the browser's own chords are left alone; a held key
  // files once, not once per repeat.
  if (event.ctrlKey || event.metaKey || event.altKey || event.repeat) return;
  const key = event.key.toLowerCase();
  if (key === "escape") {
    if (!enlargeEl.hidden) enlargeEl.hidden = true;
    else if (!filedEl.hidden) toggleFiled();
    return;
  }
  const action = state.keys === null ? undefined : state.keys.byKey.get(key);
  if (action === undefined) return;
  event.preventDefault();
  if (action.kind === "command") {
    if (action.name === "undo") undoLast();
    else if (action.name === "enlarge") toggleEnlarge();
    else if (action.name === "filed") toggleFiled();
    return;
  }
  fileSelection(action);
}

// ---------------------------------------------------------------- boot

async function boot() {
  canvasEl.style.setProperty("--tile-w", `${TILE_W}px`);
  canvasEl.style.setProperty("--tile-h", `${TILE_H}px`);
  let manifest;
  try {
    manifest = await loadCorpus();
    state.keys = buildKeyMap(manifest.categories, manifest.rejections);
  } catch (error) {
    if (!(error instanceof WallError)) throw error;
    failLoad(`${error.message} Nothing can be filed until it loads.`);
    return;
  }
  state.items = manifest.items;
  state.byId = new Map(state.items.map((item) => [item.item_id, item]));
  // The server re-reads the corrections on every request, so this is the whole of
  // resuming a pass: an item belongs on the wall exactly when nothing is filed
  // against it (R5).
  for (const item of state.items) {
    if (item.filed !== null) state.filed.set(item.item_id, item.filed);
  }
  renderLegend();
  refresh();
  root.dataset.wall = "ready";
}

wallEl.addEventListener("scroll", renderWindow, { passive: true });
window.addEventListener("resize", () => {
  layout();
  renderWindow();
});
window.addEventListener("keydown", onKeyDown);
// An item leaves the wall the moment it is filed, so a batch still queued is work
// the person believes is saved. `pagehide` is the close and the navigation, and the
// last event a document reliably gets: nothing there can wait for an answer.
window.addEventListener("pagehide", () => queue.flushOnHide());
document.addEventListener("visibilitychange", () => {
  // A backgrounded tab is not a closed one: looking away at the physical book is
  // the normal rhythm of this sitting, so the batch goes out as a real request
  // whose refusal can still be shown. Only `pagehide` gives up on an answer.
  if (document.visibilityState === "hidden") queue.flush();
});

boot();
