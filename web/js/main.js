// Builds the screen from the pipeline's content and plays it: one body large in
// view, a pager of every body, the supply grouped by category, the hand, a done
// star and a name chooser per body, and the placed Items on each body. Taps and
// drags go through the pointer engine; every commit is saved to the store.

import { loadContent, groupByCategory, ContentError } from "./catalog.js";
import { NAMES } from "./names.js";
import { createEngine } from "./gesture.js";
import { createHand } from "./hand.js";
import { load, save } from "./store.js";

const HAND_SLOTS = 6;

const game = document.getElementById("game");
const message = document.getElementById("content-message");
const nameList = document.getElementById("name-list");

const engine = createEngine();
const hand = createHand(HAND_SLOTS);

const state = {
  bodies: [],
  items: [],
  current: 0,
  saved: null,   // the store's state: placements, done, names (see store.js)
  nextZ: 0,      // stacking order: every commit puts its Item on top
  naming: -1,    // body index whose name is being chosen, or -1
};

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child);
  return node;
}

function picture(entry) {
  return el("img", {
    src: entry.image,
    width: entry.width,
    height: entry.height,
    alt: "",
    draggable: "false",
    decoding: "async",
  });
}

const stageOf = (body) => game.querySelector(`.stage[data-rig-stage="${body}"]`);
const regionRect = (name) => game.querySelector(`[data-rig-region="${name}"]`).getBoundingClientRect();
const contains = (rect, x, y) => x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;

// ---------------------------------------------------------------- board

function buildStage(body, index) {
  const star = el("button", {
    class: "star",
    type: "button",
    "aria-label": "done",
    "aria-pressed": "false",
    "data-rig-kind": "star",
    text: "★",
  });
  engine.attachTap(star, () => toggleDone(index));

  const nameButton = el("button", {
    class: "name-button",
    type: "button",
    "aria-label": "name",
    "data-rig-kind": "name",
  }, [el("span", { class: "name-glyph", text: "✎" }), el("span", { class: "body-name" })]);
  engine.attachTap(nameButton, () => openNames(index));

  const figure = el("div", { class: "body", "data-rig-kind": "body", "data-rig-slot": index }, [picture(body)]);
  figure.firstChild.addEventListener("load", () => { if (index === state.current) layoutPlaced(index); });
  const stage = el("div", { class: "stage", "data-rig-stage": index }, [figure, star, nameButton]);
  engine.attachTap(stage, (point) => placeFromHand(index, point));
  stage.hidden = index !== state.current;
  return stage;
}

function buildPager(bodies) {
  const thumbs = bodies.map((body, index) => {
    const thumb = el("button", {
      class: "pager-thumb",
      type: "button",
      "data-rig-kind": "pager-thumb",
      "data-rig-slot": index,
      "aria-current": index === state.current ? "true" : "false",
    }, [picture(body)]);
    engine.attachTap(thumb, () => showBody(index));
    return thumb;
  });
  return el("nav", { class: "pager", "data-rig-region": "pager" }, thumbs);
}

function buildHand() {
  const slots = [];
  for (let k = 0; k < HAND_SLOTS; k += 1) {
    slots.push(el("div", { class: "hand-slot", "data-rig-kind": "hand-slot", "data-rig-slot": k }));
  }
  return el("section", { class: "hand", "data-rig-region": "hand" }, slots);
}

function buildSupply(items) {
  const groups = groupByCategory(items).map(({ category, entries }) => {
    const tiles = entries.map(({ index, item }) => {
      const tile = el("div", { class: "tile", "data-rig-kind": "tile", "data-rig-slot": index }, [picture(item)]);
      engine.attachTap(tile, () => pickUp(index));
      return tile;
    });
    return el("section", { class: "supply-group", "data-category": category }, [
      el("h2", { class: "supply-label", text: category }),
      el("div", { class: "tiles" }, tiles),
    ]);
  });
  const scroll = el("div", { class: "supply-scroll" }, groups);
  return el("section", { class: "supply", "data-rig-region": "supply" }, [scroll]);
}

function render(content) {
  state.bodies = content.bodies;
  state.items = content.items;
  state.saved = load({ buildId: content.buildId, bodyCount: content.bodies.length });
  state.nextZ = state.saved.placements.reduce((top, p) => Math.max(top, p.z + 1), 0);
  const board = el("section", { class: "board", "data-rig-region": "board" },
    content.bodies.map(buildStage));
  game.replaceChildren(buildPager(content.bodies), board, buildHand(), buildSupply(content.items));
  content.bodies.forEach((body, index) => {
    const stage = stageOf(index);
    stage.classList.toggle("done", state.saved.done[index]);
    stage.querySelector(".star").setAttribute("aria-pressed", String(state.saved.done[index]));
    const nameIndex = state.saved.names[index];
    stage.querySelector(".body-name").textContent = nameIndex >= 0 && nameIndex < NAMES.length ? NAMES[nameIndex] : "";
    renderPlaced(index);
  });
  window.addEventListener("resize", () => layoutPlaced(state.current));
}

// ---------------------------------------------------------------- placed items
// A placement's x, y are the Item's centre as fractions of the body's recorded
// width and height, so they are viewport-independent and may fall outside 0..1
// for an Item off the body. On screen one factor, displayed body height over
// recorded body height, scales the body and every Item on it alike (R4); the
// scale block in the content is build metadata and is not a render input.

function bodyFrame(body) {
  const figure = stageOf(body).querySelector(".body");
  const img = figure.querySelector(":scope > img");
  const figureRect = figure.getBoundingClientRect();
  const imgRect = img.getBoundingClientRect();
  const recorded = state.bodies[body];
  const factor = imgRect.height / recorded.height;
  return {
    factor,
    width: recorded.width * factor,
    height: imgRect.height,
    left: imgRect.left,                    // client coordinates of the image box
    top: imgRect.top,
    offsetX: imgRect.left - figureRect.left, // the image box within the figure
    offsetY: imgRect.top - figureRect.top,
  };
}

function toFractions(frame, clientX, clientY) {
  return { x: (clientX - frame.left) / frame.width, y: (clientY - frame.top) / frame.height };
}

function placeElement(element, placement, frame) {
  const item = state.items[placement.item];
  const w = item.width * frame.factor;
  const h = item.height * frame.factor;
  element.style.width = `${w}px`;
  element.style.height = `${h}px`;
  element.style.left = `${frame.offsetX + placement.x * frame.width - w / 2}px`;
  element.style.top = `${frame.offsetY + placement.y * frame.height - h / 2}px`;
  element.style.transform = "";
}

// Rebuilds a body's placed Items in stacking order, lowest z first.
function renderPlaced(body) {
  const figure = stageOf(body).querySelector(".body");
  figure.querySelectorAll(".placed").forEach((node) => node.remove());
  const placements = state.saved.placements.filter((p) => p.body === body).sort((a, b) => a.z - b.z);
  for (const placement of placements) {
    const element = el("div", { class: "placed", "data-rig-kind": "placed", "data-rig-slot": placement.item },
      [picture(state.items[placement.item])]);
    attachPlacedDrag(element, placement);
    figure.append(element);
  }
  layoutPlaced(body);
}

function layoutPlaced(body) {
  const figure = stageOf(body).querySelector(".body");
  const elements = figure.querySelectorAll(".placed");
  if (elements.length === 0) return;
  const frame = bodyFrame(body);
  const placements = state.saved.placements.filter((p) => p.body === body).sort((a, b) => a.z - b.z);
  elements.forEach((element, k) => placeElement(element, placements[k], frame));
}

function attachPlacedDrag(element, placement) {
  engine.attachDrag(element, {
    onStart: () => element.classList.add("dragging"),
    onMove: ({ dx, dy }) => { element.style.transform = `translate(${dx}px, ${dy}px)`; },
    onEnd: ({ dx, dy, x, y }) => {
      element.classList.remove("dragging");
      releasePlaced(placement, dx, dy, x, y);
    },
    onCancel: () => {
      element.classList.remove("dragging");
      renderPlaced(placement.body);
    },
  });
}

// Where a dragged Item is released decides what it becomes (R5, R15): over the
// hand it is carried, over the supply it is taken off, anywhere on the board it
// stays where it landed and stacks on top. A release elsewhere (off every region)
// reverts, since the board's clipping would hide it there.
function releasePlaced(placement, dx, dy, pointerX, pointerY) {
  if (contains(regionRect("hand"), pointerX, pointerY)) {
    if (hand.add(placement.item)) {
      removePlacement(placement);
      renderHand();
    } else {
      renderPlaced(placement.body);
    }
    return;
  }
  if (contains(regionRect("supply"), pointerX, pointerY)) {
    removePlacement(placement);
    return;
  }
  if (!contains(regionRect("board"), pointerX, pointerY)) {
    renderPlaced(placement.body);
    return;
  }
  const frame = bodyFrame(placement.body);
  const centre = toFractions(
    frame,
    frame.left + placement.x * frame.width + dx,
    frame.top + placement.y * frame.height + dy,
  );
  placement.x = centre.x;
  placement.y = centre.y;
  placement.z = state.nextZ++;
  commit(placement.body);
}

function removePlacement(placement) {
  state.saved.placements = state.saved.placements.filter((p) => p !== placement);
  commit(placement.body);
}

function placeFromHand(body, point) {
  const item = hand.takeFirst();
  if (item === undefined) return;
  const centre = toFractions(bodyFrame(body), point.x, point.y);
  state.saved.placements.push({ item, body, x: centre.x, y: centre.y, z: state.nextZ++ });
  renderHand();
  commit(body);
}

function commit(body) {
  save(state.saved);
  renderPlaced(body);
}

// ---------------------------------------------------------------- hand

function renderHand() {
  hand.render([...game.querySelectorAll(".hand-slot")], (item, slot) => {
    const tile = el("div", { class: "hand-tile", "data-rig-kind": "hand-tile", "data-rig-slot": item },
      [picture(state.items[item])]);
    engine.attachTap(tile, () => { hand.remove(slot); renderHand(); });
    return tile;
  });
}

function pickUp(item) {
  if (hand.add(item)) renderHand();
}

// ---------------------------------------------------------------- taps

function showBody(index) {
  state.current = index;
  game.querySelectorAll(".stage").forEach((stage, i) => { stage.hidden = i !== index; });
  game.querySelectorAll(".pager-thumb").forEach((thumb, i) => {
    thumb.setAttribute("aria-current", i === index ? "true" : "false");
  });
  closeNames();
  layoutPlaced(index);
}

function toggleDone(index) {
  state.saved.done[index] = !state.saved.done[index];
  const stage = stageOf(index);
  stage.classList.toggle("done", state.saved.done[index]);
  stage.querySelector(".star").setAttribute("aria-pressed", String(state.saved.done[index]));
  save(state.saved);
}

function openNames(index) {
  state.naming = index;
  nameList.hidden = false;
}

function closeNames() {
  state.naming = -1;
  nameList.hidden = true;
}

function chooseName(nameIndex) {
  const index = state.naming;
  if (index < 0) return;
  state.saved.names[index] = nameIndex;
  stageOf(index).querySelector(".body-name").textContent = NAMES[nameIndex];
  closeNames();
  save(state.saved);
}

function buildNameList() {
  const choices = NAMES.map((name, nameIndex) => {
    const choice = el("button", { class: "name-choice", type: "button", text: name });
    choice.addEventListener("click", () => chooseName(nameIndex));
    return choice;
  });
  const close = el("button", { class: "name-close", type: "button", "aria-label": "close", text: "✕" });
  close.addEventListener("click", closeNames);
  nameList.replaceChildren(el("div", { class: "name-sheet" }, [...choices, close]));
  nameList.addEventListener("click", (event) => { if (event.target === nameList) closeNames(); });
}

// ---------------------------------------------------------------- start

function showFailure(err) {
  const detail = err instanceof ContentError ? err.message : String(err);
  message.replaceChildren(
    el("p", { class: "content-title", text: "Content needs rebuilding" }),
    el("p", { class: "content-detail", text: detail }),
  );
  message.hidden = false;
  game.replaceChildren();
}

async function start() {
  buildNameList();
  try {
    render(await loadContent());
    document.documentElement.dataset.content = "ready";
  } catch (err) {
    showFailure(err);
    document.documentElement.dataset.content = "failed";
  }
}

start();
