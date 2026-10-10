import { tagsInEvery, tagsOfVault } from './tags'

const groups = [
  { name: 'Strom', items: [{ id: 1, vault_id: 9 }] },
  { name: 'Haus', items: [{ id: 2, vault_id: 7 }, { id: 3, vault_id: 9 }] },
  { name: 'Geheim', items: [{ id: 4, vault_id: 7 }] },
]

describe('the tags of one vault', () => {
  it('are the names that vault has, and no name only other vaults have', () => {
    expect(tagsOfVault(groups, 9)).toEqual(['Strom', 'Haus'])
    expect(tagsOfVault(groups, 7)).toEqual(['Haus', 'Geheim'])
    expect(tagsOfVault(groups, 3)).toEqual([])
  })

  it('of several vaults are those every one has', () => {
    expect(tagsInEvery([['Strom', 'Haus'], ['haus', 'Geheim']])).toEqual(['Haus'])
    expect(tagsInEvery([['Strom']])).toEqual(['Strom'])
    expect(tagsInEvery([])).toEqual([])
  })
})
