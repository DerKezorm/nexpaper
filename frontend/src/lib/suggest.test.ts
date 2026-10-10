import { filterNames, fold, similar, suggest } from './suggest'

describe('suggesting names', () => {
  it('ignores case and accents, and marks the span in the name as written', () => {
    expect(fold('Müller')).toBe('muller')
    const { shown } = suggest(['Bäckerei Müller', 'Stadtwerke Lindenau'], 'MULL')
    expect(shown).toEqual([{ name: 'Bäckerei Müller', marks: [[9, 13]] }])
  })

  it('puts a name that starts with the typing before one that only contains it', () => {
    const { shown } = suggest(['Glanzwerk Reinigungsservice', 'Reinhard Wendt', 'Tom Reinhardt'], 'rein')
    expect(shown.map((s) => s.name)).toEqual(['Reinhard Wendt', 'Glanzwerk Reinigungsservice', 'Tom Reinhardt'])
  })

  it('shows at most the limit and counts the rest', () => {
    const names = Array.from({ length: 12 }, (_, i) => `Absender ${i}`)
    const { shown, more } = suggest(names, 'abs', 8)
    expect(shown).toHaveLength(8)
    expect(more).toBe(4)
  })

  it('finds nothing for nothing typed, and lists everything for the overlay', () => {
    expect(suggest(['A'], '  ').shown).toEqual([])
    expect(filterNames(['b', 'a'], '').map((s) => s.name)).toEqual(['a', 'b'])
    expect(filterNames(['b', 'a'], 'x')).toEqual([])
  })

  it('keeps the marks right where a letter decomposes', () => {
    const { shown } = suggest(['Café Ünal'], 'unal')
    expect(shown[0].marks).toEqual([[5, 9]])
  })
})

describe('names that look like what is typed', () => {
  const names = ['Strom', 'Stromzähler', 'Steuer', 'Versicherung', 'Zahnarzt', 'Haus']

  it('finds a name the typing contains whole', () => {
    expect(similar(names, 'Stromvertrag')).toEqual(['Strom'])
    expect(similar(names, 'Steuern')).toEqual(['Steuer'])
  })

  it('finds a slip of the finger, more of them for a longer word', () => {
    expect(similar(names, 'Versicherrung')).toEqual(['Versicherung'])
    expect(similar(names, 'Zahnartzt')).toEqual(['Zahnarzt'])
    expect(similar(names, 'Strmo')).toEqual([])
  })

  it('leaves out what the typing is part of (the list shows those), what is the same, and what is far', () => {
    expect(similar(names, 'strom')).toEqual([])
    expect(similar(names, 'Garantie')).toEqual([])
    expect(similar(names, 'ab')).toEqual([])
    expect(similar(names, '')).toEqual([])
  })

  it('does not take a short word for a part of a long one', () => {
    expect(similar(['Ha', 'Ab'], 'Haushalt')).toEqual([])
  })

  it('puts the closest first and counts no more than the limit', () => {
    expect(similar(['Strom', 'Stromvertrag', 'Vertrag'], 'Stromvertragsnummer', 2)).toEqual(['Stromvertrag', 'Vertrag'])
  })
})
