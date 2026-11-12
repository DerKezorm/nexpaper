/**
 * A sentence with a name in it, the name stressed: "<name>Jule</name> bittet dich um Dokumente". The name is a value
 * somebody chose (a display name, the name of an upload request): it is put in as text, never as markup. `Trans` with
 * the name among its values would read `<strong>` or `<name>` in it as elements (the translations run without escaping,
 * React escapes), so the sentence is taken from the translation with a mark in place of the name, cut there, and the
 * name goes between the two halves as a text node.
 */
import { useTranslation } from 'react-i18next'

import { iso } from '../lib/say'

/** A character no translation and no name holds (a private-use one), where the name stands. */
const MARK = ''

export function NamedSentence({ i18nKey, name, values = {}, className = 'font-semibold text-ink' }: { i18nKey: string; name: string; values?: Record<string, unknown>; className?: string }) {
  const { t } = useTranslation()
  const text = t(i18nKey, { ...values, name: MARK })
  const at = text.indexOf(MARK)
  if (at < 0) return <>{text.replace(/<\/?name>/g, '')}</>
  // The mark stands inside the translation's own <name>…</name>: the tags go, they only said where the stress goes.
  const before = text.slice(0, at).replace(/<name>$/, '')
  const after = text.slice(at + MARK.length).replace(/^<\/name>/, '')
  return (
    <>
      {before}
      <span className={className}>{iso(name)}</span>
      {after}
    </>
  )
}
