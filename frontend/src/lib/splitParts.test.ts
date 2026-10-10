/** Where a stack is cut: the parts a set of cuts and dropped pages make. */
import { partsOf } from './splitParts'

describe('the parts of a stack', () => {
  it('starts a part at every cut and leaves dropped pages out', () => {
    expect(partsOf(6, new Set([2, 5]), new Set([1, 4]))).toEqual([[0], [2, 3], [5]])
    expect(partsOf(4, new Set([0]), new Set())).toEqual([[0, 1, 2, 3]])
    expect(partsOf(3, new Set(), new Set([0, 1, 2]))).toEqual([])
  })
})
