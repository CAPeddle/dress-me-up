// Filing's decided parts — the key map and the write queue — kept out of wall.js
// so each can be read without the drawing around it.
//
// The queue is here because a keystroke is not a write. Posting one batch instead
// of one request per key keeps half an hour of labelling off the wire, which means
// there is always a window where an item has left the wall and its verdict is not
// yet on disk. Everything below is about closing that window: a small count, a
// short interval, a flush when the page goes away, and a revert per item whenever
// the server refuses.

export class WallError extends Error {
  constructor(message) {
    super(message);
    this.name = "WallError";
  }
}

// The commands hold their keys before a single category is assigned one. The
// category list grew by one this week (KTD10), and a list that grows must never
// quietly take undo's key away from it.
export const COMMAND_KEYS = Object.freeze({ undo: "u", enlarge: "e", filed: "f" });

const DIGIT_KEYS = "1234567890";
const LETTER_KEYS = "abcdefghijklmnopqrstuvwxyz";

function freeKey(name, taken) {
  // A letter out of the name itself first, so the mapping past the number row is
  // worth remembering; any free letter when the name has none left to give.
  for (const character of `${name}${LETTER_KEYS}`.toLowerCase()) {
    if (LETTER_KEYS.includes(character) && !taken.has(character)) return character;
  }
  throw new WallError(`no key left for ${name}`);
}

// Fifteen actions against ten digits, so the mapping extends past the number row
// (KTD10). Built from the arrays the server sends rather than from a list here:
// the categories are the pipeline's own constant, and a second copy of them would
// only ever agree with itself.
export function buildKeyMap(categories, rejections) {
  const taken = new Set(Object.values(COMMAND_KEYS));
  const entries = [];
  const actions = [
    ...categories.map((name) => ({ name, kind: "category" })),
    ...rejections.map((name) => ({ name, kind: "rejection" })),
  ];
  actions.forEach((action, index) => {
    const key = index < DIGIT_KEYS.length ? DIGIT_KEYS[index] : freeKey(action.name, taken);
    taken.add(key);
    entries.push({ ...action, key });
  });
  for (const [name, key] of Object.entries(COMMAND_KEYS)) {
    entries.push({ name, kind: "command", key });
  }
  const byKey = new Map(entries.map((entry) => [entry.key, entry]));
  // A clash would silently file under the wrong bucket, which is the one failure
  // this tool exists to remove. Refused at boot, where it is still a bug report.
  if (byKey.size !== entries.length) throw new WallError("two actions share one key");
  return { entries, byKey };
}

// One batch in flight at a time, the next waiting behind it: two batches for one
// PDF are safe on the server, but a later batch overtaking an earlier one would
// let a stale verdict land last. The chain is no longer the only thing standing
// between the file and that outcome — every filing carries the page's session and
// its own revision, and the server leaves out one it has already bettered for
// that item — because the chain cannot cover the one write that does not wait for it,
// the beacon `flushOnHide` sends. What the chain still buys is the answer: one
// request outstanding means one batch's failure to revert and report at a time.
export function createQueue({
  send,
  sendOnHide,
  sizeLimit = 12,
  interval = 1500,
  onChange = () => {},
  onFailure = () => {},
  onSettled = () => {},
}) {
  // Keyed by item, so a second verdict on one item replaces the first rather than
  // queueing behind it. That is not only tidiness: the server pops withdrawals
  // before it applies filings, so a filing and its undo in one batch would leave
  // the filing standing and the undo silently lost.
  const open = new Map();
  let inFlight = [];
  let timer = null;
  let chain = Promise.resolve();

  const pending = () => open.size + inFlight.length;
  const report = () => onChange(pending());

  function revert(entries, message) {
    for (const entry of entries) entry.revert();
    onFailure(message, entries);
  }

  async function post() {
    if (open.size === 0) return;
    const batch = [...open.values()];
    open.clear();
    inFlight = batch;
    report();
    try {
      const result = await send({ filings: batch.map((entry) => entry.filing) });
      const failed = Array.isArray(result.failed) ? result.failed : [];
      if (failed.length) {
        // Per PDF: the server reports one outcome per correction file, so only the
        // items whose book did not land come back to the wall.
        const stems = new Set(failed.map((entry) => entry.source_pdf));
        revert(
          batch.filter((entry) => stems.has(entry.source_pdf)),
          failed.map((entry) => `${entry.source_pdf}: ${entry.error}`).join("; "),
        );
      } else {
        onSettled();
      }
    } catch (error) {
      // Whole-batch: the server refuses a bad batch entire and writes none of it.
      revert(batch, error instanceof WallError ? error.message : String(error));
    } finally {
      inFlight = [];
      report();
    }
  }

  function flush() {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    chain = chain.then(post);
    return chain;
  }

  function add(entries) {
    for (const entry of entries) open.set(entry.item_id, entry);
    report();
    if (open.size >= sizeLimit) {
      flush();
      return;
    }
    if (timer === null) timer = setTimeout(flush, interval);
  }

  // The page is going away, so there is no answer to wait for and nothing left to
  // show a failure on: the one thing that matters is that the bytes leave. It
  // cannot wait behind `chain` for that reason — a document being torn down is no
  // place to hold a promise — so this write is the one that can overtake a batch
  // still in flight, and an item re-filed since that batch went out would then be
  // decided by whichever request the server handled second. What keeps the newer
  // verdict is the revision each filing carries: the server applies a filing for
  // an item only when it is newer than the one it last wrote for that item in this
  // session, so order is settled by the numbers and not by arrival.
  //
  // A batch already in flight is still not resent: the server has it, and sending
  // it twice would file the same verdicts again rather than rescue anything.
  function flushOnHide() {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    if (open.size === 0) return;
    const batch = [...open.values()];
    open.clear();
    sendOnHide({ filings: batch.map((entry) => entry.filing) });
    report();
  }

  return { add, flush, flushOnHide, pending };
}
