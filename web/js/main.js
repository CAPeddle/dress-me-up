// Builds the screen from the pipeline's content: one body large in view, a
// pager of every body, the supply grouped by category, an empty hand, a done
// star and a name chooser per body. Placement, the hand and saving are later.

import { loadContent, groupByCategory, ContentError } from "./catalog.js";
import { NAMES } from "./names.js";

const HAND_SLOTS = 6;

const game = document.getElementById("game");
const message = document.getElementById("content-message");
const nameList = document.getElementById("name-list");

const state = {
  bodies: [],
  items: [],
  current: 0,
  done: [],      // boolean per body index
  names: [],     // index into NAMES per body index, or -1
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
  star.addEventListener("click", () => toggleDone(index));

  const nameButton = el("button", {
    class: "name-button",
    type: "button",
    "aria-label": "name",
    "data-rig-kind": "name",
  }, [el("span", { class: "name-glyph", text: "✎" }), el("span", { class: "body-name" })]);
  nameButton.addEventListener("click", () => openNames(index));

  const figure = el("div", { class: "body", "data-rig-kind": "body", "data-rig-slot": index }, [picture(body)]);
  const stage = el("div", { class: "stage", "data-rig-stage": index }, [figure, star, nameButton]);
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
    thumb.addEventListener("click", () => showBody(index));
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
    const tiles = entries.map(({ index, item }) =>
      el("div", { class: "tile", "data-rig-kind": "tile", "data-rig-slot": index }, [picture(item)]));
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
  state.done = content.bodies.map(() => false);
  state.names = content.bodies.map(() => -1);
  const board = el("section", { class: "board", "data-rig-region": "board" },
    content.bodies.map(buildStage));
  game.replaceChildren(buildPager(content.bodies), board, buildHand(), buildSupply(content.items));
}

// ---------------------------------------------------------------- taps

function showBody(index) {
  state.current = index;
  game.querySelectorAll(".stage").forEach((stage, i) => { stage.hidden = i !== index; });
  game.querySelectorAll(".pager-thumb").forEach((thumb, i) => {
    thumb.setAttribute("aria-current", i === index ? "true" : "false");
  });
  closeNames();
}

function toggleDone(index) {
  state.done[index] = !state.done[index];
  const stage = game.querySelector(`.stage[data-rig-stage="${index}"]`);
  stage.classList.toggle("done", state.done[index]);
  stage.querySelector(".star").setAttribute("aria-pressed", String(state.done[index]));
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
  state.names[index] = nameIndex;
  game.querySelector(`.stage[data-rig-stage="${index}"] .body-name`).textContent = NAMES[nameIndex];
  closeNames();
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
