/** The transfer code (K1): what the dialog checks before it asks the server for the code. */

/** How long the code waits after the last key before it is drawn anew. */
export const REDRAW_MS = 400
/** What a purpose may hold (the server's ``transfer.PURPOSE_CHARS``): the SEPA set and the German umlauts. */
export const PURPOSE_CHARS = /^[A-Za-z0-9/\-?:().,'+ ÄÖÜäöüß]*$/
/** The most a code may ask for, in cents (999.999.999,99 €). */
export const AMOUNT_MAX = 99_999_999_999

/** "DE12 3456 ..." for the eye; the code takes the IBAN without blanks. */
export function spacedIban(iban: string): string {
  return iban.replace(/(.{4})/g, '$1 ').trim()
}
