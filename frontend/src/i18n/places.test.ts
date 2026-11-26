/**
 * The places nexpaper's texts name are the places of the settings as they are now (plan "Einstellungen", E39): a path
 * "Mein Konto › …" or "Server › …" goes on with an area of that group, in the words of the navigation (the kit's titles
 * and nexpaper's own areas). The word for a program's access is "API-Schlüssel" ("API key", "clé d’API"), never
 * "API-Token" (only Paperless calls its own one so); and no text points the old way ("unter Einstellungen, Allgemein",
 * "Mein Konto, Erinnerungen", "Einstellungen → Anmeldung").
 */
import { describe, expect, it } from 'vitest'

import { NEXUI_TEXTS } from '../vendor/nexui'
import schluesselDe from '../vendor/nexschluessel/schluessel.de.json'
import schluesselEn from '../vendor/nexschluessel/schluessel.en.json'
import de from './de.json'
import en from './en.json'
import fr from './fr.json'

type Tree = { [key: string]: string | Tree }

function texts(tree: Tree, prefix = ''): [string, string][] {
  return Object.entries(tree).flatMap(([key, value]) =>
    typeof value === 'string' ? [[prefix + key, value] as [string, string]] : texts(value, `${prefix}${key}.`),
  )
}

const ACCOUNT = ['profile', 'security', 'appearance', 'notifications', 'connections'] as const
const SERVER = ['general', 'sign-in', 'mail', 'storage', 'accounts', 'log', 'ai-provider'] as const
/** nexpaper's own areas (`settings.areas.<key>`), by group. */
const OWN_ACCOUNT = ['upload', 'myAi'] as const
const OWN_SERVER = ['ocr', 'filing', 'inputs', 'import'] as const

const LANGUAGES = [
  { name: 'de', tree: de as unknown as Tree, kit: NEXUI_TEXTS.de, areas: de.settings.areas },
  { name: 'en', tree: en as unknown as Tree, kit: NEXUI_TEXTS.en, areas: en.settings.areas },
  { name: 'fr', tree: fr as unknown as Tree, kit: NEXUI_TEXTS.fr, areas: fr.settings.areas },
]

/** Texts about other programs keep their words (E46): Safari's menus in the card "Auf diesem Gerät installieren". */
const FOREIGN = /^install\./
/** E48: the one sentence of "Grenzen" that names the dialog of an account, "Konten › Verwalten". */
const E48 = /^storage\.limits\.(newAccountStorageHint|hint)$/

/** Paperless names its own access "API-Token"; that is Paperless' word, on the page of the import. */
const PAPERLESS = /^paperless\./

describe('the places the texts name', () => {
  for (const { name, tree, kit, areas } of LANGUAGES) {
    const groups: Record<string, string[]> = {
      [kit.groupAccount]: [...ACCOUNT.map((slug) => kit.areas[slug].title), ...OWN_ACCOUNT.map((key) => areas[key].title)],
      [kit.groupServer]: [...SERVER.map((slug) => kit.areas[slug].title), ...OWN_SERVER.map((key) => areas[key].title)],
    }

    it(`are areas of the settings as the navigation calls them (${name})`, () => {
      const wrong: string[] = []
      let paths = 0
      for (const [key, text] of texts(tree)) {
        for (const [group, titles] of Object.entries(groups)) {
          for (const found of text.matchAll(new RegExp(`${group} › `, 'g'))) {
            paths += 1
            const rest = text.slice((found.index ?? 0) + found[0].length)
            if (!titles.some((title) => rest.startsWith(title))) wrong.push(`${key}: ${text}`)
          }
        }
      }
      expect(wrong).toEqual([])
      // Profile, Security, Upload, Notifications, Connections, AI; Sign-in, General, AI provider, the address.
      expect(paths).toBeGreaterThanOrEqual(25)
    })

    it(`say API key and point no old way (${name})`, () => {
      const old = texts(tree).filter(
        ([key, text]) =>
          (!PAPERLESS.test(key) && /API-Token|API tokens?\b|[Jj]etons? API/.test(text)) ||
          /Einstellungen, |Einstellungen →|Settings, |Settings →|Paramètres, |Paramètres →|Mein Konto, |My account, |Mon compte, |Mein Konto →|My account →|Mon compte →|Speicher und Sicherungen/.test(text),
      )
      expect(old.map(([key, text]) => `${key}: ${text}`)).toEqual([])
    })
  }

  for (const { name, tree, kit, areas: own } of LANGUAGES) {
    const titles = [...ACCOUNT, ...SERVER].map((slug) => kit.areas[slug].title)
      .concat([...OWN_ACCOUNT, ...OWN_SERVER].map((key) => own[key].title))
    const escape = (word: string) => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const words = [kit.groupAccount, kit.groupServer, kit.settings, ...titles].map(escape).join('|')
    const areas = titles.map(escape).join('|')

    it(`write a place group › area, with no comma, arrow or "card" as a separator (E46, ${name})`, () => {
      const wrong: string[] = []
      for (const [key, text] of texts(tree)) {
        // Safari's own menus ("Teilen › Zum Home-Bildschirm", "Ablage › Zum Dock hinzufügen") keep its words (E46).
        if (FOREIGN.test(key)) continue
        if (new RegExp(`(^|[^\\p{L}])(${words})\\s*(,|→|->)\\s*(${words})($|[^\\p{L}])`, 'u').test(text)) wrong.push(`${key}: ${text}`)
        if (new RegExp(`(Karte|card|carte) [„“"«]\\s?(${words})|(,|in der|in the|dans la) (Karte|card|carte) [„“"«]`).test(text)) wrong.push(`${key}: ${text}`)
        // An area at the start of a path needs its group before it; E48 sets "Konten › Verwalten" in "Grenzen".
        for (const found of text.matchAll(new RegExp(`(^|[^›] )(${areas}) › `, 'g'))) {
          const before = text.slice(0, (found.index ?? 0) + found[1]!.length)
          const grouped = [kit.groupAccount, kit.groupServer].some((group) => before.endsWith(`${group} › `))
          const e48 = E48.test(key) && found[2] === kit.areas.accounts.title
          if (!grouped && !e48) wrong.push(`${key}: ${text}`)
        }
      }
      expect(wrong).toEqual([])
    })
  }

  it('lead to the cards where things are now, in their words', () => {
    // The interface's switch is a card under General (schluessel's "Schnittstellen"), the shortcut under Connections.
    expect(de.apiKeys.offOperator).toBe(`Unter Server › Allgemein › ${schluesselDe.interfaces.title} freigeben.`)
    expect(en.apiKeys.offOperator).toBe(`Allow them under Server › General › ${schluesselEn.interfaces.title}.`)
    expect(de.phone.settings.text).toContain('Unter Mein Konto › Verbindungen steht dann „Kurzbefehl laden“.')
    expect(de.phone.iphone.key).toBe('Schlüssel für den Kurzbefehl')
    expect(de.uploadRequest.off).toContain(`Server › Allgemein › ${de.server.features}`)
    expect(en.uploadRequest.off).toContain(`Server › General › ${en.server.features}`)
    expect(fr.uploadRequest.off).toContain(`Serveur › Général › ${fr.server.features}`)
    expect(de.errors.public_url_missing).toContain('Server › Anmeldung')
    expect(de.reminders.week.why).toContain('Mein Konto › Benachrichtigungen')
    expect(de.me.ai.noneOperator).toContain('<settings>Server › KI-Anbieter</settings>')
    expect(de.errors.key_invalid).toBe('Kein gültiger API-Schlüssel.')
  })
})
