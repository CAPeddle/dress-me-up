// The hand (R16): the Items she is carrying, as a list of Item indices, oldest
// first. It is her fingers, not the book, so it is never saved. A supply tap
// adds to it, a body tap takes the first Item out, and a tap on a hand tile puts
// that Item back in the supply.

export function createHand(capacity) {
  const items = [];

  return {
    // Appends an Item; a full hand ignores the add and says so.
    add(item) {
      if (items.length >= capacity) return false;
      items.push(item);
      return true;
    },
    takeFirst() {
      return items.shift();
    },
    // Drops the Item in the given slot.
    remove(slot) {
      items.splice(slot, 1);
    },
    // Fills the slot elements in order; `tileFor(item, slot)` builds the tile.
    render(slots, tileFor) {
      slots.forEach((slot, k) => {
        slot.replaceChildren(...(k < items.length ? [tileFor(items[k], k)] : []));
      });
    },
  };
}
