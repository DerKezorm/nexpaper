// nexpost in the browser: the fields of the mail server card in their order, the choices of encryption, the warning
// without encryption and the keys of the texts. No component and no look of its own: every app shows these with its
// own building blocks.
//
// Copied unchanged into frontend/src/vendor/nexpost/ by bauplaene/post/tools/sync.py; changed only there.

/** The error codes of the server, in its order (errors.py). */
export const MAIL_ERROR_CODES = [
  'mail_off',
  'mail_unreachable',
  'mail_tls_failed',
  'mail_auth_refused',
  'mail_sender_refused',
  'mail_recipient_refused',
  'mail_refused',
  'mail_failed',
  'mail_address_invalid',
  'mail_settings_invalid',
] as const

export type MailErrorCode = (typeof MAIL_ERROR_CODES)[number]

/** The text key for an error code; ``appCodes`` maps the app's codes of an older version to the module's. */
export function mailErrorKey(code: string | null | undefined, appCodes: Readonly<Record<string, string>> = {}): string {
  const given = code ?? ''
  const own = Object.hasOwn(appCodes, given) ? (appCodes[given] ?? '') : given
  return (MAIL_ERROR_CODES as readonly string[]).includes(own) ? `mail.error.${own}` : 'mail.error.unknown'
}

export const SECURITY = ['starttls', 'tls', 'none'] as const
export type Security = (typeof SECURITY)[number]

/** The usual port of each encryption (filled in when the operator switches, unless the port was typed). */
export const DEFAULT_PORTS: Record<Security, number> = { starttls: 587, tls: 465, none: 25 }

export const SECURITY_LABELS: Record<Security, string> = {
  starttls: 'mail.securityStarttls',
  tls: 'mail.securityTls',
  none: 'mail.securityNone',
}

/** The fields of the mail server card, top to bottom. Below them: the warning, "Send a test mail", the last result. */
export const MAIL_FIELDS = ['server', 'port', 'security', 'user', 'password', 'sender', 'senderName'] as const

/** Whether the card shows ``mail.warningUnencrypted``: no encryption, and a user or a stored password. */
export function warnUnencrypted(values: { security: string; user: string; password: string; passwordSet: boolean }): boolean {
  return values.security === 'none' && (values.user.trim() !== '' || values.password !== '' || values.passwordSet)
}

/** The port to show after the encryption changed: the usual one, unless the operator typed another. */
export function portFor(security: Security, current: number, typed: boolean): number {
  return typed ? current : DEFAULT_PORTS[security]
}

/** The default variables of i18next for these texts. */
export function postVariables(app: string): { app: string } {
  return { app }
}
