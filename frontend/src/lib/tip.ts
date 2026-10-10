/**
 * Where a tooltip of a chart stands. It is drawn in the window (`position: fixed`), outside every scrolling box, so it
 * can neither be cut off by one nor make one scroll. This works out its corner from the thing it points at: centred
 * over it, above it when there is room, below it otherwise, and never beyond the edges of the window.
 */

export type Box = { left: number; top: number; width: number; height: number }

/** The space kept free at the edges of the window, in pixels. */
export const TIP_MARGIN = 8
/** The space between the tooltip and what it points at. */
export const TIP_GAP = 6

export function placeTip(anchor: Box, tip: { width: number; height: number }, view: { width: number; height: number }): { left: number; top: number; above: boolean } {
  const centre = anchor.left + anchor.width / 2
  const left = Math.max(TIP_MARGIN, Math.min(centre - tip.width / 2, view.width - tip.width - TIP_MARGIN))
  const roomAbove = anchor.top - TIP_GAP - tip.height >= TIP_MARGIN
  const above = roomAbove || anchor.top + anchor.height + TIP_GAP + tip.height > view.height - TIP_MARGIN
  const wanted = above ? anchor.top - TIP_GAP - tip.height : anchor.top + anchor.height + TIP_GAP
  const top = Math.max(TIP_MARGIN, Math.min(wanted, view.height - tip.height - TIP_MARGIN))
  return { left, top, above }
}
