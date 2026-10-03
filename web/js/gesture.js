// The pointer engine (KTD6): gesture state keyed by pointer id, at most one live
// gesture, commit on release, revert on cancel. DOM-only, so it can be driven by
// dispatched PointerEvents; it knows nothing about bodies, items or the hand.
//
// Two kinds of gesture:
//   tap candidate  opened by pointerdown on a tappable surface; commits on a
//                  pointerup within the slop radius and the time window, and
//                  aborts silently on movement beyond slop, on pointercancel, or
//                  on timeout. The surface keeps its native touch-action, so the
//                  supply and the pager still pan.
//   drag           opened by pointerdown on a placed Item, which takes pointer
//                  capture (and carries touch-action: none in CSS); only the live
//                  pointer's moves steer it, pointerup commits at the release
//                  point, and pointercancel or a lost capture reverts it.
//
// While a gesture is live every other pointerdown is ignored, not queued, so a
// pointerdown that bubbles from a placed Item up to the stage under it opens
// exactly one gesture: the drag.

export const DEFAULT_SLOP_PX = 12;
export const DEFAULT_TAP_MS = 400;

export function createEngine({ slop = DEFAULT_SLOP_PX, tapMs = DEFAULT_TAP_MS } = {}) {
  const live = new Map(); // pointerId -> gesture kind

  const beyondSlop = (origin, event) =>
    Math.hypot(event.clientX - origin.x, event.clientY - origin.y) > slop;

  // Follow-up events are taken at the document, filtered to the live pointer:
  // a captured pointer's events target the capturing element and an uncaptured
  // pointer's target whatever is under it, and both bubble here.
  function follow(pointerId, handlers) {
    const offs = Object.entries(handlers).map(([type, handler]) => {
      const listener = (event) => { if (event.pointerId === pointerId) handler(event); };
      document.addEventListener(type, listener);
      return () => document.removeEventListener(type, listener);
    });
    return () => offs.forEach((off) => off());
  }

  function attachTap(element, onTap) {
    element.addEventListener("pointerdown", (event) => {
      if (live.size > 0) return;
      const id = event.pointerId;
      const origin = { x: event.clientX, y: event.clientY };
      let stop = () => {};
      const finish = () => {
        clearTimeout(timer);
        stop();
        live.delete(id);
      };
      const timer = setTimeout(finish, tapMs);
      stop = follow(id, {
        pointermove: (e) => { if (beyondSlop(origin, e)) finish(); },
        pointerup: (e) => {
          const withinSlop = !beyondSlop(origin, e);
          finish();
          if (withinSlop) onTap(origin);
        },
        pointercancel: finish,
      });
      live.set(id, "tap");
    });
  }

  function attachDrag(element, { onStart, onMove, onEnd, onCancel }) {
    element.addEventListener("pointerdown", (event) => {
      if (live.size > 0) return;
      event.preventDefault();
      const id = event.pointerId;
      const origin = { x: event.clientX, y: event.clientY };
      const delta = (e) => ({ dx: e.clientX - origin.x, dy: e.clientY - origin.y, x: e.clientX, y: e.clientY });
      let moved = false;
      let stop = () => {};
      const finish = () => {
        stop();
        element.removeEventListener("lostpointercapture", lost);
        live.delete(id);
        try { element.releasePointerCapture(id); } catch (err) { /* already released */ }
      };
      // A capture lost with no pointerup (the element left the DOM, or the browser
      // took the pointer) ends the drag the way a cancel does.
      const lost = (e) => {
        if (e.pointerId !== id) return;
        finish();
        onCancel();
      };
      // A synthetic pointer cannot be captured; the document listeners still follow it.
      try { element.setPointerCapture(id); } catch (err) { /* not an active pointer */ }
      element.addEventListener("lostpointercapture", lost);
      stop = follow(id, {
        pointermove: (e) => {
          const d = delta(e);
          if (!moved && Math.hypot(d.dx, d.dy) <= slop) return;
          moved = true;
          onMove(d);
        },
        pointerup: (e) => {
          finish();
          // A release within slop is a tap, and a tap on a placed Item does
          // nothing, so it ends the way a cancel does: nothing moved, nothing saved.
          if (moved) onEnd(delta(e));
          else onCancel();
        },
        pointercancel: () => {
          finish();
          onCancel();
        },
      });
      live.set(id, "drag");
      onStart(origin);
    });
  }

  return { attachTap, attachDrag };
}
