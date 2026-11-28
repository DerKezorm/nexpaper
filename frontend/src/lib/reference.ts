/**
 * The reference of a document ("Aktenzeichen", #13): one free text per document, a patient's file number or a case
 * number. Each vault may give the field its own name or hide it; a document that has a value always shows it, so
 * nothing is kept where nobody sees it.
 */
import type { TFunction } from 'i18next'

import type { Vault } from '../api/client'

/** The longest reference the server keeps. */
export const REFERENCE_MAX = 100
/** The longest name a vault gives the field. */
export const REFERENCE_NAME_MAX = 40

/** The name of the field in this vault: its own, else the default of the language. */
export function referenceName(vault: Pick<Vault, 'reference_name'> | undefined, t: TFunction): string {
  return vault?.reference_name?.trim() || t('docs.fields.reference')
}

/** Whether the field shows: always, unless the vault hides it and there is nothing in it. */
export function referenceShown(vault: Pick<Vault, 'reference_hidden'> | undefined, ...values: (string | null | undefined)[]): boolean {
  return !vault?.reference_hidden || values.some((value) => (value ?? '').trim() !== '')
}
