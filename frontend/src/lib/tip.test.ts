/**
 * Where a tooltip stands: over what it points at, under it where there is no room above, never beyond the window.
 */
import { placeTip, TIP_GAP, TIP_MARGIN } from './tip'

const tip = { width: 200, height: 50 }
const view = { width: 1000, height: 700 }

describe('placing a tooltip', () => {
  it('centres it over the anchor', () => {
    const at = placeTip({ left: 480, top: 300, width: 40, height: 20 }, tip, view)
    expect(at).toEqual({ left: 400, top: 300 - TIP_GAP - 50, above: true })
  })

  it('pushes it back from the right and the left edge', () => {
    expect(placeTip({ left: 990, top: 300, width: 10, height: 10 }, tip, view).left).toBe(1000 - 200 - TIP_MARGIN)
    expect(placeTip({ left: 0, top: 300, width: 10, height: 10 }, tip, view).left).toBe(TIP_MARGIN)
  })

  it('goes under the anchor when there is no room above', () => {
    const at = placeTip({ left: 480, top: 20, width: 40, height: 20 }, tip, view)
    expect(at).toEqual({ left: 400, top: 20 + 20 + TIP_GAP, above: false })
  })

  it('never leaves the window, even where there is room for neither side', () => {
    const at = placeTip({ left: 480, top: 30, width: 40, height: 650 }, tip, view)
    expect(at.top).toBeGreaterThanOrEqual(TIP_MARGIN)
    expect(at.top + 50).toBeLessThanOrEqual(700 - TIP_MARGIN)
  })

  it('fits a tooltip wider than the window to the margin on the left', () => {
    expect(placeTip({ left: 100, top: 300, width: 10, height: 10 }, { width: 400, height: 50 }, { width: 300, height: 700 }).left).toBe(TIP_MARGIN)
  })
})
