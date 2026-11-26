// nexkonten in the browser: the fields of every screen in their order, the rules, the username suggestion and the
// keys of the texts. No component and no look of its own: every app shows these with its own building blocks
// (field, button, card, dialog), so that the screens are the same in every app and look like the app.
//
// Copied unchanged into frontend/src/vendor/nexkonten/ by bauplaene/konten/tools/sync.py; changed only there.

/** The rules of a username, the same as the server's (names.py). */
export const USERNAME_MIN = 2
export const USERNAME_MAX = 64
export const USERNAME_PATTERN = /^[a-z0-9][a-z0-9._-]{1,63}$/
export const DISPLAY_NAME_MAX = 80
export const EMAIL_MAX = 254
export const PASSWORD_MIN = 12

/** The error codes of the server, in its order (errors.py). */
export const ACCOUNT_ERROR_CODES = [
  'setup_code_wrong',
  'already_set_up',
  'display_name_empty',
  'display_name_taken',
  'username_invalid',
  'username_taken',
  'email_invalid',
  'email_taken',
  'email_same',
  'password_too_short',
  'password_too_long',
  'wrong_password',
  'fresh_sign_in_needed',
  'wrong_credentials',
  'account_blocked',
  'not_allowed',
  'not_found',
  'use_account_page',
  'password_login_off',
  'invalid_days',
  'invite_invalid',
  'invite_expired',
  'reset_invalid',
  'reset_expired',
  'email_link_invalid',
  'email_link_expired',
  'no_pending_email',
  'code_wrong',
  'enrolment_expired',
  'sign_in_expired',
  'factor_missing',
  'factor_required',
  'passkeys_off',
  'passkey_invalid',
  'passkey_expired',
  'passkey_exists',
  'too_many_passkeys',
  'too_many_attempts',
  'avatar_too_large',
  'avatar_not_a_picture',
  'avatars_busy',
  'public_url_needed',
  'nothing_to_prove',
  // since 1.1.0
  'cannot_demote_self',
  'cannot_block_self',
  'cannot_delete_self',
  'last_operator',
  'feature_off',
  'invalid_limit',
  'theme_invalid',
  'provider_first',
  'own_second_factor_first',
] as const

export type AccountErrorCode = (typeof ACCOUNT_ERROR_CODES)[number]

/** Codes whose sentence is one of the main texts rather than one under account.error. */
const MAIN_TEXT: Partial<Record<AccountErrorCode, string>> = {
  wrong_credentials: 'account.wrong',
  username_taken: 'account.usernameTaken',
  username_invalid: 'account.usernameRules',
  email_taken: 'account.emailTaken',
}

function isAccountCode(code: string): code is AccountErrorCode {
  return (ACCOUNT_ERROR_CODES as readonly string[]).includes(code)
}

/** The text key for an error code from the server; never show the code itself. ``appCodes`` maps the app's own codes
 * of an older version to the module's (the server's AppConfig.error_codes the other way round), e.g.
 * { name_taken: 'username_taken' }.
 *
 * Since 0.3.10 ``accountCode``: the module's own code where the server mapped it to an older one (``account_code`` in
 * the answer, ``AccountError.as_dict``). An app may answer ``invite_invalid`` for ``invite_expired`` too (its clients
 * know only the old code); its pages still say "expired". The chain, the first that is a code of the module:
 * ``accountCode``, then ``code`` through ``appCodes``, then ``code`` itself; else ``account.error.unknown``. */
export function accountErrorKey(
  code: string | null | undefined,
  appCodes: Readonly<Record<string, string>> = {},
  accountCode?: string | null,
): string {
  const given = code ?? ''
  const mapped = Object.hasOwn(appCodes, given) ? (appCodes[given] ?? '') : given
  const own = [accountCode ?? '', mapped].find((candidate) => isAccountCode(candidate))
  if (own === undefined || !isAccountCode(own)) return 'account.error.unknown'
  return MAIN_TEXT[own] ?? `account.error.${own}`
}

/** Since 0.3.10: ``accountErrorKey`` for an answer of the server as it came (``code`` and, where the app maps it,
 * ``account_code``). */
export function accountErrorKeyOf(
  answer: { code?: string | null; account_code?: string | null } | null | undefined,
  appCodes: Readonly<Record<string, string>> = {},
): string {
  return accountErrorKey(answer?.code, appCodes, answer?.account_code)
}

/** Every field the module's screens know. */
export type AccountField =
  | 'setupCode'
  | 'displayName'
  | 'username'
  | 'email'
  | 'login'
  | 'password'
  | 'currentPassword'
  | 'newPassword'
  | 'passwordRepeat'
  | 'language'

export interface FieldSpec {
  /** The text key of the label. */
  label: string
  /** The text key of the hint under the field; '' for none. */
  hint: string
  type: 'text' | 'email' | 'password' | 'select'
  autoComplete: string
  required: boolean
  /** The longest value the field takes; 0 for no limit of the module's. */
  maxLength: number
}

export const FIELDS: Record<AccountField, FieldSpec> = {
  setupCode: { label: 'account.setupCode', hint: 'account.setupCodeHint', type: 'text', autoComplete: 'off', required: true, maxLength: 0 },
  displayName: { label: 'account.displayName', hint: 'account.displayNameHint', type: 'text', autoComplete: 'name', required: true, maxLength: DISPLAY_NAME_MAX },
  username: { label: 'account.username', hint: 'account.usernameHint', type: 'text', autoComplete: 'username', required: true, maxLength: USERNAME_MAX },
  email: { label: 'account.email', hint: 'account.emailHint', type: 'email', autoComplete: 'email', required: false, maxLength: EMAIL_MAX },
  login: { label: 'account.login', hint: '', type: 'text', autoComplete: 'username', required: true, maxLength: EMAIL_MAX },
  password: { label: 'account.password', hint: '', type: 'password', autoComplete: 'current-password', required: true, maxLength: 0 },
  currentPassword: { label: 'account.currentPassword', hint: '', type: 'password', autoComplete: 'current-password', required: true, maxLength: 0 },
  newPassword: { label: 'account.newPassword', hint: 'account.passwordRules', type: 'password', autoComplete: 'new-password', required: true, maxLength: 0 },
  passwordRepeat: { label: 'account.passwordRepeat', hint: '', type: 'password', autoComplete: 'new-password', required: true, maxLength: 0 },
  language: { label: 'account.language', hint: '', type: 'select', autoComplete: 'language', required: true, maxLength: 0 },
}

/** The screens and their fields, top to bottom. Below the fields: the button, then (login and invitation) the
 * provider buttons of the OIDC module under "or". The setup has no language field: the language comes from the
 * browser silently and is changed in the profile. */
export const SCREENS = {
  setup: ['setupCode', 'displayName', 'username', 'email', 'newPassword', 'passwordRepeat'],
  invite: ['displayName', 'username', 'email', 'newPassword', 'passwordRepeat'],
  login: ['login', 'password'],
  forgot: ['login'],
  reset: ['newPassword', 'passwordRepeat'],
  profile: ['displayName', 'username', 'email', 'language'],
  operatorInvite: ['email', 'displayName'],
  /** Since 1.1.2: the dialog "Passwort ändern" under Security (each app draws it; its words come from here). */
  change: ['currentPassword', 'newPassword', 'passwordRepeat'],
} as const satisfies Record<string, readonly AccountField[]>

/** Since 1.1.2: labels that differ by screen. Where a password replaces one there was (changing it, a new one after
 * "Passwort vergessen?") the field says "Neues Passwort" (``account.changedPassword``); where it is the first one
 * (setup, invitation) it stays "Passwort" (``account.newPassword``, unchanged). */
export const SCREEN_LABELS: Partial<Record<AccountScreen, Partial<Record<AccountField, string>>>> = {
  reset: { newPassword: 'account.changedPassword' },
  change: { newPassword: 'account.changedPassword' },
}

/** Since 1.1.2: the text key of a field's label on a screen (``SCREEN_LABELS``, else ``FIELDS``). */
export function fieldLabel(screen: AccountScreen, field: AccountField): string {
  return SCREEN_LABELS[screen]?.[field] ?? FIELDS[field].label
}

export type AccountScreen = keyof typeof SCREENS

/** The parts of the account pages, top to bottom, each titled with ``account.<part>``. ``providerEmailOffer``
 * (since 0.3.3) shows only while the account has ``offered_email``: "Use the address from <provider>?" with
 * ``account.providerEmailTake`` and ``account.providerEmailDismiss`` (``{{provider}}`` the provider's label). "Mail me about a new sign-in"
 * sits under security next to the signed-in devices, not in the profile. ``operatorSignIn``: the operator's switches,
 * each with its hint (``account.factorRequiredSwitchHint``). */
export const SECTIONS = {
  profile: ['picture', 'displayName', 'username', 'email', 'providerEmailOffer', 'language', 'role'],
  /** Since 0.3.6: "Sign out everywhere else" is the button of ``sessions`` ("Signed-in devices"), see ``PAGES``. */
  security: ['password', 'secondFactor', 'recoveryCodes', 'passkeys', 'sessions', 'newSignInMail'],
  operatorSignIn: ['factorRequiredSwitch', 'passkeysAllowed'],
  /** Since 0.3.3: the operator's dialog "Reset the second factor" (``factor.reset_overview``): the account's
   * passkeys by name, then the two boxes, both ticked by default. */
  operatorFactorReset: ['factorResetHint', 'passkeys', 'factorResetPasskeys', 'factorResetDevices'],
} as const satisfies Record<string, readonly string[]>

/** Since 0.3.4: the parts of the operator's dialog "Reset the second factor" for one account (what
 * ``factor.reset_overview`` gave): the passkeys and the box "Remove the passkeys too" only when it has passkeys. The
 * same as ``ResetOverview.parts`` on the server. */
export function factorResetParts(overview: { passkeys: readonly unknown[] | number }): string[] {
  const count = typeof overview.passkeys === 'number' ? overview.passkeys : overview.passkeys.length
  return SECTIONS.operatorFactorReset.filter(
    (part: string) => count > 0 || (part !== 'passkeys' && part !== 'factorResetPasskeys'),
  )
}

/** The boxes of the operator's dialog "Reset the second factor" and how they start. */
export const FACTOR_RESET_DEFAULTS = { factorResetPasskeys: true, factorResetDevices: true } as const

/** One part of an account page (since 0.3.6): its heading or label, the hint under it, the buttons it may show (text
 * keys, in their order; which one shows depends on the state, e.g. ``totpSetup`` or ``totpRemove``). ``rules``
 * (since 0.3.7): a second hint under the first, the rules of the value (the username in the profile). */
export interface PagePart {
  part: string
  title: string
  hint: string
  rules?: string
  /** Since 0.3.10: a line every app shows in this part, whatever the state (the password's last change, see
   * ``passwordChanged``). */
  line?: string
  buttons: readonly string[]
}

/** Since 0.3.7: how the profile saves. ``save: 'button'``: one button (``saveButton``) under the fields saves
 * ``saveFields`` together, never on leaving a field. Has one of ``confirmOnSave`` changed, saving first asks for the
 * password (``account.confirmWithPassword``; without a password a fresh sign-in, ``account.confirmFresh``), once for
 * all of them: the server confirms the username and the address that way (profiles.change_username, change_email). */
export interface PageSave {
  save: 'button'
  saveButton: string
  saveFields: readonly AccountField[]
  confirmOnSave: readonly AccountField[]
}

/** Since 0.3.6: the pages "Profile" and "Security" as every app shows them, so that they look the same everywhere:
 * the page title, the parts top to bottom (the order of ``SECTIONS``) with their headings, hints and buttons, all
 * from the module's texts. ``stacked``: the fields stand one under the other, never side by side. In the profile the
 * username is changed right in its field; saving asks for the password (``account.confirmWithPassword``; without a
 * password a fresh sign-in, ``account.confirmFresh``). The role shows small at the end. The app's own parts (nexmail
 * "Google and Microsoft accounts", nexnotes "Links for reading") come after the module's (``pageOrder``). Since 0.3.7
 * the profile has one button "Save" for display name, username and email (``PageSave``), and the username shows two
 * hints, what it is for and its rules. Picture, offered address and language keep their own ways. */
export const PAGES = {
  profile: {
    title: 'account.profile',
    layout: 'stacked',
    save: 'button',
    saveButton: 'account.save',
    saveFields: ['displayName', 'username', 'email'],
    confirmOnSave: ['username', 'email'],
    parts: [
      { part: 'picture', title: 'account.picture', hint: 'account.pictureHint', buttons: ['account.pictureUpload', 'account.pictureRemove'] },
      { part: 'displayName', title: 'account.displayName', hint: 'account.displayNameHint', buttons: [] },
      { part: 'username', title: 'account.username', hint: 'account.usernameHintProfile', rules: 'account.usernameRules', buttons: [] },
      { part: 'email', title: 'account.email', hint: 'account.emailHint', buttons: [] },
      { part: 'providerEmailOffer', title: 'account.providerEmailOffer', hint: '', buttons: ['account.providerEmailTake', 'account.providerEmailDismiss'] },
      { part: 'language', title: 'account.language', hint: '', buttons: [] },
      { part: 'role', title: 'account.role', hint: '', buttons: [] },
    ],
  },
  security: {
    title: 'account.security',
    layout: 'stacked',
    parts: [
      { part: 'password', title: 'account.password', hint: '', line: 'account.passwordChangedAt', buttons: ['account.passwordChange'] },
      { part: 'secondFactor', title: 'account.secondFactor', hint: 'account.secondFactorHint', buttons: ['account.totpSetup', 'account.totpRemove'] },
      { part: 'recoveryCodes', title: 'account.recoveryCodes', hint: 'account.recoveryCodesHint', buttons: ['account.recoveryCodesNew'] },
      { part: 'passkeys', title: 'account.passkeys', hint: 'account.passkeysHint', buttons: ['account.passkeyAdd'] },
      { part: 'sessions', title: 'account.sessions', hint: 'account.signOutEverywhereHint', buttons: ['account.signOutEverywhere'] },
      { part: 'newSignInMail', title: 'account.newSignInMail', hint: 'account.newSignInMailHint', buttons: [] },
    ],
  },
} as const satisfies {
  profile: { title: string; layout: 'stacked'; parts: readonly PagePart[] } & PageSave
  security: { title: string; layout: 'stacked'; parts: readonly PagePart[] }
}

/** Since 0.3.10: the line "Last changed on …" in the box Password under Security, in every app (decided for 0.3.10;
 * nexmail and nextasks had none). ``at``: the server's ``password_changed_at`` (ISO); null or left out where it is not
 * known (a password of an older version): then ``account.passwordChangedUnknown``. ``date`` fills ``{{day}}`` the
 * app's way. An account without a password shows none of this. */
export function passwordChanged(at: string | null | undefined): {
  text: 'account.passwordChangedAt' | 'account.passwordChangedUnknown'
  date?: string
} {
  return at ? { text: 'account.passwordChangedAt', date: at } : { text: 'account.passwordChangedUnknown' }
}

/** Since 0.3.6: the parts a page shows, top to bottom: the module's first in their order, then the app's own. */
export function pageOrder(page: keyof typeof PAGES, own: readonly string[] = []): string[] {
  return [...PAGES[page].parts.map((entry: PagePart) => entry.part), ...own]
}

/** Since 0.3.8: the three kinds of buttons on the account pages, the same in every app (the shared kit ``ui``):
 * ``primary`` filled in the accent colour, at most one per box; ``secondary`` light with a fine edge; ``danger`` light
 * red with a red symbol and red words, for everything that ends or removes something. There is no fourth kind. */
export const BUTTON_KINDS = ['primary', 'secondary', 'danger'] as const

export type ButtonKind = (typeof BUTTON_KINDS)[number]

/** Since 0.3.8: how one button looks: its kind and its symbol (the name of a lucide icon, as the kit ``ui`` knows it). */
export interface ButtonSpec {
  kind: ButtonKind
  icon: string
  /** Since 1.1.0 (ui 1.1.0): ``sm`` for a button in a row, a list or a small box (``data-size``); left out ``md``. The
   * dialog "Manage" keeps ``md`` (decided 25.11.2026). */
  size?: 'sm'
}

/** Since 1.1.0: the two sizes of ui 1.1.0. */
export const BUTTON_SIZES = ['md', 'sm'] as const

export type ButtonSize = (typeof BUTTON_SIZES)[number]

/** Since 0.3.8: every button of the account pages and screens with its kind and symbol, so that the same button looks
 * the same in every app. Keyed by its text key where the module (or ``oidc``) words it, else by its role (the app
 * words it: ``signIn`` is nexmail's "Weiter" and nexnotes' "Anmelden"). An app renders these buttons only through a
 * helper that takes kind and symbol from here (``buttonSpec``), never with its own. */
export const BUTTONS = {
  // Profile
  'account.pictureUpload': { kind: 'secondary', icon: 'Upload' },
  'account.pictureChange': { kind: 'secondary', icon: 'Upload' },
  'account.pictureRemove': { kind: 'danger', icon: 'Trash2' },
  'account.save': { kind: 'primary', icon: 'Check' },
  'account.providerEmailTake': { kind: 'primary', icon: 'Check' },
  'account.providerEmailDismiss': { kind: 'secondary', icon: 'X' },
  'account.emailResend': { kind: 'secondary', icon: 'Send', size: 'sm' },
  'account.emailWithdraw': { kind: 'danger', icon: 'Undo2', size: 'sm' },
  'account.emailRemove': { kind: 'danger', icon: 'Trash2' },
  // Since 0.3.10: "Confirm by link" for an address that counts and is not proven yet (profiles.prove_email)
  'account.emailProve': { kind: 'secondary', icon: 'Send', size: 'sm' },
  // Security
  'account.passwordChange': { kind: 'secondary', icon: 'KeyRound' },
  'account.totpSetup': { kind: 'primary', icon: 'ShieldCheck' },
  'account.totpRemove': { kind: 'danger', icon: 'ShieldOff' },
  'account.recoveryCodesNew': { kind: 'secondary', icon: 'RefreshCw' },
  'account.passkeyAdd': { kind: 'secondary', icon: 'Fingerprint' },
  'account.passkeyRemove': { kind: 'danger', icon: 'Trash2', size: 'sm' },
  'account.sessionSignOut': { kind: 'danger', icon: 'LogOut', size: 'sm' },
  'account.signOutEverywhere': { kind: 'danger', icon: 'LogOut' },
  'account.disconnectAll': { kind: 'danger', icon: 'Unplug' },
  // Signing in, setup, invitation, forgotten password, the dialog "Session expired"
  'account.forgotSubmit': { kind: 'primary', icon: 'Send' },
  'account.passkeySignIn': { kind: 'secondary', icon: 'Fingerprint' },
  'account.signInAgain': { kind: 'primary', icon: 'LogIn' },
  // The operator's account list
  'account.resetLink': { kind: 'secondary', icon: 'Link' },
  'account.factorReset': { kind: 'danger', icon: 'ShieldOff' },
  // Since 0.3.9: the list, its dialog "Manage" (ACCOUNT_LIST, MANAGE_DIALOG), "Invite" and the open invitations
  'account.invite': { kind: 'primary', icon: 'UserPlus' },
  'account.manage': { kind: 'secondary', icon: 'UserCog', size: 'sm' },
  'account.changeDisplayName': { kind: 'secondary', icon: 'UserPen' },
  'account.changeUsername': { kind: 'secondary', icon: 'Pencil' },
  'account.makeOperator': { kind: 'secondary', icon: 'Crown' },
  'account.makeMember': { kind: 'secondary', icon: 'UserRound' },
  'account.signOutAccount': { kind: 'danger', icon: 'LogOut' },
  'account.unlinkProvider': { kind: 'danger', icon: 'Unlink' },
  'account.block': { kind: 'danger', icon: 'Ban' },
  'account.unblock': { kind: 'secondary', icon: 'CircleCheck' },
  'account.remove': { kind: 'danger', icon: 'UserX' },
  'account.restore': { kind: 'secondary', icon: 'RotateCcw' },
  'account.linkMake': { kind: 'primary', icon: 'Link' },
  'account.linkSend': { kind: 'primary', icon: 'Send' },
  'account.inviteWithdraw': { kind: 'danger', icon: 'Undo2', size: 'sm' },
  // The providers (the words of the module oidc)
  'oidc.login.button': { kind: 'secondary', icon: 'KeyRound' },
  'oidc.account.link': { kind: 'secondary', icon: 'Link', size: 'sm' },
  'oidc.account.unlink': { kind: 'danger', icon: 'Unlink', size: 'sm' },
  // Buttons the app words, by their role
  signIn: { kind: 'primary', icon: 'LogIn' },
  setupSubmit: { kind: 'primary', icon: 'Check' },
  inviteSubmit: { kind: 'primary', icon: 'Check' },
  resetSubmit: { kind: 'primary', icon: 'KeyRound' },
  codeSubmit: { kind: 'primary', icon: 'LogIn' },
  signOut: { kind: 'danger', icon: 'LogOut' },
  invite: { kind: 'primary', icon: 'UserPlus' },
  editAccount: { kind: 'secondary', icon: 'Pencil' },
  blockAccount: { kind: 'danger', icon: 'Ban' },
  unblockAccount: { kind: 'secondary', icon: 'CircleCheck' },
  removeAccount: { kind: 'danger', icon: 'UserX' },
  copy: { kind: 'secondary', icon: 'Copy', size: 'sm' },
  download: { kind: 'secondary', icon: 'Download' },
  done: { kind: 'primary', icon: 'Check' },
  confirm: { kind: 'primary', icon: 'Check' },
  cancel: { kind: 'secondary', icon: 'X' },
  back: { kind: 'secondary', icon: 'ArrowLeft' },
  // Since 0.3.9: the app's own buttons in the dialog "Manage", at their fixed places (OwnButton)
  storageLimit: { kind: 'secondary', icon: 'HardDrive' },
  handOver: { kind: 'secondary', icon: 'ArrowRightLeft' },
  // Since 1.0.0: taking an own value of the app away again (a storage limit, a quota; nextime and nexnotes borrowed
  // account.emailRemove for it): red, a bin, like every other removing
  removeValue: { kind: 'danger', icon: 'Trash2' },
  // Since 1.1.0: the operator's functions of every app (the storage limit where the app has it), the profile's box
  // "Address not confirmed yet", signing out, the operator's sign-in settings (ShieldOff: the second factor no more)
  'account.storageLimit': { kind: 'secondary', icon: 'HardDrive' },
  'account.storageLimitRemove': { kind: 'danger', icon: 'Trash2' },
  'account.emailProveSend': { kind: 'secondary', icon: 'Send', size: 'sm' },
  'account.signOut': { kind: 'danger', icon: 'LogOut' },
  'account.waitForChanges': { kind: 'secondary', icon: 'X' },
  'account.signOutAnyway': { kind: 'danger', icon: 'LogOut' },
  'account.factorRequiredOff': { kind: 'danger', icon: 'ShieldOff' },
  'account.cancel': { kind: 'secondary', icon: 'X' },
} as const satisfies Record<string, ButtonSpec>

/** Since 1.1.0: the size of a button (``ui`` ``Button size``): ``sm`` where ``BUTTONS`` says so, else ``md``. */
export function buttonSize(name: ButtonName): ButtonSize {
  const spec: ButtonSpec = BUTTONS[name]
  return spec.size ?? 'md'
}

export type ButtonName = keyof typeof BUTTONS

/** Since 0.3.8: kind and symbol of a button of the account pages. */
export function buttonSpec(name: ButtonName): ButtonSpec {
  return BUTTONS[name]
}

/** Since 0.3.6: what the second factor shows next to its heading, by the server's ``second_factor`` state: "Off"
 * while none is set up (also where one is required and missing), "On" with an authenticator or a passkey. */
export const SECOND_FACTOR_STATE = {
  none: 'account.stateOff',
  required: 'account.stateOff',
  active: 'account.stateOn',
  passkey: 'account.stateOn',
} as const

/** Since 0.3.6: the setup page's title and subtitle, the same in every app. Under the password no word about the
 * second factor while none is required; where the operator requires one (``factorRequired``), the page says so. */
export const SETUP_PAGE = { title: 'account.setupTitle', subtitle: 'account.setupSubtitle' } as const

export function setupNotes(options: { factorRequired?: boolean } = {}): string[] {
  return options.factorRequired ? ['account.factorRequired'] : []
}

/** Since 0.3.3: notices shown plainly at the top of every account page and of the operator's settings while the
 * server says so. ``secondFactorOff``: the emergency hammer is down (``factor.switched_off()``), with its hint
 * ``account.secondFactorOffHint``. */
export const NOTICES = ['secondFactorOff'] as const

export interface ScreenOptions {
  /** The app's own autocomplete of a field, e.g. { login: 'username webauthn' } where passkeys sign in too. */
  autoComplete?: Partial<Record<AccountField, string>>
}

/** The fields of a screen with their specs; on the profile the display name may stay empty (the username shows).
 * ``hints`` (since 0.3.7): every hint under the field, in order, each joined to the field by ``aria-describedby`` (the
 * first is ``hint``); the field's accessible name is its label, nothing else. */
export function screenFields(
  screen: AccountScreen,
  options: ScreenOptions = {},
): Array<FieldSpec & { field: AccountField; hints: string[] }> {
  return SCREENS[screen].map((field: AccountField) => {
    const spec = FIELDS[field]
    const optional = (screen === 'profile' || screen === 'operatorInvite') && field === 'displayName'
    const autoComplete = options.autoComplete?.[field] ?? spec.autoComplete
    // In the profile the username is changed right there: its hint says only what it is for.
    const profileName = screen === 'profile' && field === 'username'
    const hint = profileName ? 'account.usernameHintProfile' : spec.hint
    // Since 0.3.7 the profile names the rules under it too.
    const hints = profileName ? [hint, 'account.usernameRules'] : hint ? [hint] : []
    return { ...spec, label: fieldLabel(screen, field), field, autoComplete, hint, hints, required: optional ? false : spec.required }
  })
}

/** How long an invitation and a link of the operator may hold, in days, and the defaults. A link a person asks for
 * on the sign-in page holds one hour, always. */
export const INVITE_DAYS = [1, 7, 30] as const
export const INVITE_DAYS_DEFAULT = 7
export const RESET_DAYS = [1, 7, 30] as const
export const RESET_DAYS_DEFAULT = 1

/** What the app starts after setup, an invitation or a new password (the server's next). */
export const NEXT_STEPS = ['session', 'second_factor', 'second_factor_setup', 'sign_in', 'passkey', 'show_codes'] as const

/** Since 0.3.5: the dialog "Session expired" (the session ended while a page was open; the page stays underneath):
 * its parts for each step, top to bottom, the same as ``common.SESSION_EXPIRED_PARTS`` on the server. It starts at
 * ``sign_in`` (``or``: "or" and the provider buttons as on the sign-in page; ``password`` and its button only where
 * the account has a password), then shows what the server's ``next`` says: the code, the passkey ("Sign in with a
 * passkey"), setting a factor up, the recovery codes. ``session``: the dialog closes and the page goes on. */
export const SESSION_EXPIRED = {
  sign_in: ['sessionExpiredHint', 'password', 'signInAgain', 'or'],
  second_factor: ['code', 'signInAgain'],
  passkey: ['passkeySignIn'],
  second_factor_setup: ['factorRequired', 'totpSetup', 'passkeyAdd'],
  show_codes: ['recoveryCodesHint', 'recoveryCodes'],
  session: [],
} as const satisfies Record<(typeof NEXT_STEPS)[number], readonly string[]>

/** Since 0.3.5: the parts of the dialog "Session expired" for the server's ``next``; an unknown one starts over. */
export function sessionExpiredParts(next: string): readonly string[] {
  return next in SESSION_EXPIRED ? SESSION_EXPIRED[next as keyof typeof SESSION_EXPIRED] : SESSION_EXPIRED.sign_in
}

export function normalizeUsername(raw: string): string {
  return raw.trim().toLowerCase()
}

export function usernameValid(name: string): boolean {
  return USERNAME_PATTERN.test(name) && !name.includes('@')
}

const GERMAN: Record<string, string> = { 'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss' }

/** A username from a display name ('Max Müller' becomes 'max-mueller'); '' when nothing usable is left. The same
 * as the server's suggest_username. */
export function suggestUsername(displayName: string): string {
  let text = (displayName ?? '').normalize('NFC').toLowerCase().replace(/[äöüß]/g, (char) => GERMAN[char] ?? char)
  text = text.normalize('NFKD').replace(/\p{M}/gu, '')
  text = text.replace(/[^a-z0-9._-]+/g, '-').replace(/([._-])[._-]+/g, '$1')
  text = text.replace(/^[._-]+|[._-]+$/g, '')
  if (text.length > USERNAME_MAX) {
    const numbered = /^(.*?)(-\d+)$/.exec(text)
    const suffix = numbered?.[2] ?? ''
    const stem = numbered?.[1] ?? text
    text = stem.slice(0, USERNAME_MAX - suffix.length).replace(/[._-]+$/, '') + suffix
  }
  text = text.replace(/^[._-]+|[._-]+$/g, '')
  return usernameValid(text) ? text : ''
}

/** The username field follows the display name until somebody touches it. */
export function followUsername(state: { touched: boolean; username: string }, displayName: string): string {
  return state.touched ? state.username : suggestUsername(displayName)
}

/** The sign-in field holds an address when it has an @ (a username never has one). */
export function isEmailLogin(typed: string): boolean {
  return typed.includes('@')
}

/** What is wrong with a new password and its repetition, as a text key; '' when nothing. */
export function newPasswordProblem(password: string, repeat: string): string {
  if (password.length < PASSWORD_MIN) return 'account.error.password_too_short'
  if (password !== repeat) return 'account.passwordMismatch'
  return ''
}

/** What is wrong with a username before it goes to the server, as a text key; '' when nothing. */
export function usernameProblem(raw: string): string {
  return usernameValid(normalizeUsername(raw)) ? '' : 'account.usernameRules'
}

/** Since 1.0.0: the largest profile picture in MB (``avatars.MAX_MB`` on the server), ``{{mb}}`` in
 * ``account.error.avatar_too_large``. */
export const AVATAR_MAX_MB = 20

/** The default variables of i18next for the texts of this module: the app's name as its container is called, the
 * environment variables of the setup code and of the emergency hammer (since 0.3.3), since 1.0.0 the largest picture
 * (``mb``). */
export function kontenVariables(app: string): {
  app: string
  setupTokenEnv: string
  secondFactorOffEnv: string
  minimum: number
  mb: number
} {
  const name = app.trim().toLowerCase()
  const env = name.toUpperCase().replace(/-/g, '_')
  return {
    app: name,
    setupTokenEnv: `${env}_SETUP_TOKEN`,
    secondFactorOffEnv: `${env}_SECOND_FACTOR_OFF`,
    minimum: PASSWORD_MIN,
    mb: AVATAR_MAX_MB,
  }
}

// --- Since 0.3.0: second factor, sessions, passkeys, pictures ------------------------------------------------------

/** Digits of a time-based code; recovery codes are ``xxxxx-xxxxx``. */
export const CODE_DIGITS = 6
export const RECOVERY_CODES = 10
/** "Stay signed in" is ticked by default; ticked 30 days from the last use, else until the browser closes (12 h). */
export const STAY_SIGNED_IN_DEFAULT = true
export const REMEMBER_DAYS = 30
export const BROWSER_HOURS = 12

/** What the code field takes: digits of the authenticator app or a recovery code (letters, a hyphen). */
export function codeLooksValid(typed: string): boolean {
  const code = typed.trim().replace(/[\s-]/g, '')
  return /^[0-9]{6}$/.test(code) || /^[a-z2-9]{10}$/i.test(code)
}

/** The picture for an account without a photo: one letter and a hue (0 to 359) from the name, the same in every app
 * and in the iPhone apps (avatars.placeholder on the server). The app picks lightness and saturation for its look. */
export function avatarPlaceholder(name: string): { letter: string; hue: number } {
  const text = name.trim()
  const first = Array.from(text)[0] ?? ''
  const letter = first ? (Array.from(first.toUpperCase())[0] ?? '?') : '?'
  let hash = 0x811c9dc5
  for (const byte of new TextEncoder().encode(text.toLowerCase())) {
    hash ^= byte
    hash = Math.imul(hash, 0x01000193) >>> 0
  }
  return { letter, hue: hash % 360 }
}

// --- Since 0.3.9: the operator's account list, the dialog "Manage", inviting --------------------------------------

/** Since 0.3.9: the tones of a badge, as the kit ``ui`` knows them (``Badge``). */
export type BadgeTone = 'accent' | 'on' | 'off' | 'warn' | 'danger'

/** Since 0.3.9: a provider an account is linked with (the module ``oidc``): its link's id and the label of its
 * button ("Pocket ID"). */
export interface ListedProvider {
  id: number | string
  label: string
}

/** Since 0.3.9: one account as the operator's list knows it. Every app maps its own row to this once (the names of
 * its interfaces stay); what the app does not know it leaves out, and the list shows nothing for it. ``color``
 * (since 0.3.10): the colour the app gives this person already (nextime, nexfolk), for the letter of a picture-less
 * account everywhere, the list included. */
export interface ListedAccount {
  id: number | string
  username: string
  /** '' when none: the username shows in its place. */
  displayName: string
  /** '' when the account has no address. */
  email: string
  /** Whether the address counts (confirmed); left out where the app does not tell. */
  emailConfirmed?: boolean
  /** Another account has the same address (it counts for neither). */
  emailDuplicate?: boolean
  operator: boolean
  /** The operator's own account: what changes it is in the profile and under security, not here. */
  self: boolean
  hasPassword: boolean
  /** An authenticator app is set up. */
  authenticator: boolean
  /** How many passkeys the account has. */
  passkeys: number
  providers: readonly ListedProvider[]
  blocked?: boolean
  /** When it was blocked (ISO); null or left out: not known. */
  blockedAt?: string | null
  /** Held for a while by the brake after wrong passwords (not the operator's block). */
  locked?: boolean
  /** When it was deleted (ISO); null or left out: not deleted. */
  deletedAt?: string | null
  /** The day it goes for good (ISO), while it can still be brought back. */
  purgeAt?: string | null
  /** The last sign-in (ISO); null: never; left out: the app does not keep it, and the fact does not show. */
  lastSeenAt?: string | null
  /** The address of its own picture; null or left out: the letter (``avatarPlaceholder``). */
  picture?: string | null
  /** Since 0.3.10: the app's colour of this person (a CSS colour, ``#4a6491``); null or left out: the hue from the
   * name (``avatarPlaceholder``), as before. */
  color?: string | null
  /** Since 1.1.0, apps with the feature ``storage_limit``: the account's limit in bytes (null: none) and what it uses. */
  storageLimit?: number | null
  storageUsed?: number | null
  /** Since 1.1.0: the rights the account has (``ai``, ``immich``); only the app's features show (``FEATURES``). */
  rights?: readonly string[]
}

/** Since 0.3.9: the badges of a row, in this order, each with its words and tone. ``provider`` is one badge per
 * linked provider, worded with the provider's label. ``deleted`` names the day it goes for good (``{{day}}``, the app
 * writes the day its way). */
export const ACCOUNT_BADGES = {
  operator: { text: 'account.roleOperator', tone: 'accent' },
  you: { text: 'account.badgeYou', tone: 'off' },
  secondFactor: { text: 'account.badgeSecondFactor', tone: 'on' },
  blocked: { text: 'account.badgeBlocked', tone: 'danger' },
  locked: { text: 'account.badgeLocked', tone: 'warn' },
  deleted: { text: 'account.badgeDeleted', tone: 'danger' },
  emailDuplicate: { text: 'account.badgeEmailDuplicate', tone: 'warn' },
  provider: { text: '', tone: 'off' },
} as const satisfies Record<string, { text: string; tone: BadgeTone }>

export type AccountBadge = keyof typeof ACCOUNT_BADGES

export const ACCOUNT_BADGE_ORDER = [
  'operator',
  'you',
  'secondFactor',
  'blocked',
  'locked',
  'deleted',
  'emailDuplicate',
  'provider',
] as const satisfies readonly AccountBadge[]

/** One badge to show: its text key (with ``{{day}}`` from ``date``), or for a provider its label. */
export interface BadgeShown {
  badge: AccountBadge | 'invite'
  text: string
  tone: BadgeTone
  /** The provider's label, shown as it is (``text`` is then ''). */
  label?: string
  /** A day the app writes its way, ``{{day}}`` in ``text``. */
  date?: string
}

/** Since 0.3.9: the operator's account list, the same in every app (``ui``: ``Card``, ``Rows``, ``Row`` with ``lead``
 * and ``sub``, ``Avatar``, ``Badge``, ``Button``). A card titled ``account.accounts`` with the number of accounts under
 * it (``account.accountsCount`` with ``count``, deleted ones not counted), the button ``account.invite`` first, then one
 * row per account: ``row`` in this order. ``picture``: ``Avatar`` 32 px (``accountPicture``); ``name``: the display
 * name, else the username (``accountName``); ``badges``: ``accountBadges``; ``lines``: small under the name,
 * ``username · email`` (``accountLine``, no address: the username alone); ``manage``: the button ``account.manage``
 * (named for readers ``account.manageTitle`` with ``{{name}}``), which opens ``MANAGE_DIALOG``. Under the card, only
 * while there are any, the card ``OPEN_INVITES``. Nothing else in a row: every act on an account is in the dialog. */
export const ACCOUNT_LIST = {
  title: 'account.accounts',
  subtitle: 'account.accountsCount',
  invite: 'account.invite',
  row: ['picture', 'name', 'badges', 'lines', 'manage'],
  picture: 32,
  lines: ['username', 'email'],
  separator: ' · ',
  badges: ACCOUNT_BADGE_ORDER,
  manage: 'account.manage',
  manageLabel: 'account.manageTitle',
  after: ['openInvites'],
} as const

/** Since 0.3.9: what a row and the dialog show as the name: the display name, else the username. */
export function accountName(row: Pick<ListedAccount, 'displayName' | 'username'>): string {
  return row.displayName.trim() || row.username
}

/** Since 0.3.9: the small line under the name: ``username · email``, without an address the username alone. */
export function accountLine(row: Pick<ListedAccount, 'username' | 'email'>): string {
  return row.email ? `${row.username}${ACCOUNT_LIST.separator}${row.email}` : row.username
}

/** Since 0.3.9: the picture of a row and of the dialog: the own picture where there is one, the letter and hue in any
 * case (``Avatar`` falls back to them when the picture does not load). Since 0.3.10 ``color``: the app's colour of the
 * person (``ListedAccount.color``) where it has one, for ``Avatar``'s ``color``; else null and the hue counts (decided
 * 25.11.2026: an app with colours of its own for people paints the letter in that colour everywhere). */
export function accountPicture(row: Pick<ListedAccount, 'displayName' | 'username' | 'picture' | 'color'>): {
  src: string | null
  letter: string
  hue: number
  color: string | null
} {
  const color = row.color?.trim() ?? ''
  return { src: row.picture ?? null, ...avatarPlaceholder(accountName(row)), color: color || null }
}

/** Since 0.3.9: how many accounts the subtitle counts: all but the deleted ones. */
export function accountCount(rows: readonly Pick<ListedAccount, 'deletedAt'>[]): number {
  return rows.filter((row) => !row.deletedAt).length
}

/** Since 0.3.9: whether the account has a second factor (an authenticator or a passkey; a passkey counts). */
export function hasSecondFactor(row: Pick<ListedAccount, 'authenticator' | 'passkeys'>): boolean {
  return row.authenticator || row.passkeys > 0
}

/** Since 0.3.9: the badges of one account, in ``ACCOUNT_BADGE_ORDER``. A deleted account is neither blocked nor
 * locked any more; without its day it says only "Deleted" (``account.badgeDeletedNow``). */
export function accountBadges(row: ListedAccount): BadgeShown[] {
  const shown: BadgeShown[] = []
  const add = (badge: Exclude<AccountBadge, 'provider'>, date?: string) => {
    const spec = ACCOUNT_BADGES[badge]
    shown.push(date === undefined ? { badge, text: spec.text, tone: spec.tone } : { badge, text: spec.text, tone: spec.tone, date })
  }
  if (row.operator) add('operator')
  if (row.self) add('you')
  if (hasSecondFactor(row)) add('secondFactor')
  if (row.blocked && !row.deletedAt) add('blocked')
  if (row.locked && !row.deletedAt) add('locked')
  if (row.deletedAt) {
    if (row.purgeAt) add('deleted', row.purgeAt)
    else shown.push({ badge: 'deleted', text: 'account.badgeDeletedNow', tone: ACCOUNT_BADGES.deleted.tone })
  }
  if (row.email && row.emailDuplicate) add('emailDuplicate')
  for (const provider of row.providers) shown.push({ badge: 'provider', text: '', tone: ACCOUNT_BADGES.provider.tone, label: provider.label })
  return shown
}

/** Since 0.3.9: the facts of the dialog "Manage" by the module, in this order; the app's own follow (``accountFacts``). */
export const ACCOUNT_FACTS = ['username', 'email', 'role', 'signIn', 'lastSeen', 'blockedSince', 'purgeAt'] as const

/** One fact of the dialog "Manage" (``ui``: ``Facts``): its label (text key) and one value: ``raw`` as it is, ``text``
 * a text key with ``values``, or ``date`` a moment the app writes its way (day, or day and time). ``state``: a small
 * word after the value (text key, "confirmed"); ``note``: a line under the value (text key). An app's own facts
 * (storage with its limit, mailboxes, documents) come in the same shape. */
export interface FactShown {
  fact: string
  label: string
  raw?: string
  text?: string
  values?: Readonly<Record<string, string>>
  date?: string
  state?: string
  note?: string
}

/** Since 0.3.9: how an account signs in, as the fact ``signIn`` says it: password (with a second factor), providers
 * (``{{providers}}`` their labels), or both. */
export function signInWay(row: Pick<ListedAccount, 'hasPassword' | 'authenticator' | 'passkeys' | 'providers'>): {
  text: string
  values?: Readonly<Record<string, string>>
} {
  const providers = row.providers.map((provider) => provider.label).join(', ')
  const factor = hasSecondFactor(row)
  if (row.hasPassword && providers) return { text: factor ? 'account.wayBothFactor' : 'account.wayBoth', values: { providers } }
  if (row.hasPassword) return { text: factor ? 'account.wayPasswordFactor' : 'account.wayPassword' }
  if (providers) return { text: 'account.wayProviders', values: { providers } }
  return { text: 'account.wayNone' }
}

/** Since 0.3.9: the facts of one account, top to bottom (``ACCOUNT_FACTS``, only those with a value), then the app's
 * own (``own``) in the order given. */
export function accountFacts(row: ListedAccount, own: readonly FactShown[] = []): FactShown[] {
  const facts: FactShown[] = [{ fact: 'username', label: 'account.username', raw: row.username }]
  if (row.email) {
    const email: FactShown = { fact: 'email', label: 'account.email', raw: row.email }
    if (row.emailConfirmed !== undefined) email.state = row.emailConfirmed ? 'account.emailStateConfirmed' : 'account.emailStateWaiting'
    if (row.emailDuplicate) email.note = 'account.emailDuplicate'
    facts.push(email)
  } else {
    facts.push({ fact: 'email', label: 'account.email', text: 'account.emailNone' })
  }
  facts.push({ fact: 'role', label: 'account.role', text: row.operator ? 'account.roleOperator' : 'account.roleMember' })
  facts.push({ fact: 'signIn', label: 'account.signInWay', ...signInWay(row) })
  if (row.lastSeenAt === null) facts.push({ fact: 'lastSeen', label: 'account.lastSeen', text: 'account.never' })
  else if (row.lastSeenAt !== undefined) facts.push({ fact: 'lastSeen', label: 'account.lastSeen', date: row.lastSeenAt })
  if (row.blocked && row.blockedAt && !row.deletedAt) facts.push({ fact: 'blockedSince', label: 'account.blockedSince', date: row.blockedAt })
  if (row.deletedAt && row.purgeAt) facts.push({ fact: 'purgeAt', label: 'account.purgeAt', date: row.purgeAt })
  return [...facts, ...own]
}

/** Since 0.3.9: the groups of the dialog "Manage", top to bottom: change it (secondary; removing the address is
 * danger), the app's rights as boxes to tick, access, end it (danger; unblock and bring back are secondary). */
export const MANAGE_GROUPS = ['change', 'rights', 'access', 'end'] as const

export type ManageGroup = (typeof MANAGE_GROUPS)[number]

/** Since 0.3.9: the dialog behind "Manage" (``ui``: ``Dialog`` titled ``account.manageTitle`` with ``{{name}}``). At
 * the head the picture 48 px with name, badges and the line under it (``Row`` with ``lead`` and ``sub``), then the facts
 * (``Facts``: ``accountFacts`` with the app's own), then one ``ButtonGroup`` per group that has anything, titled
 * ``title``, its buttons (``layout: 'buttons'``) or boxes (``'list'``, ``CheckboxRow``) from ``accountActions`` in that
 * order. ``buttons``: the module's buttons of each group in their order (``makeOperator`` or ``makeMember``, ``block``
 * or ``unblock``, ``unlinkProvider`` once per provider). Every button says what it does in words. */
export const MANAGE_DIALOG = {
  title: 'account.manageTitle',
  picture: 48,
  parts: ['head', 'facts', 'change', 'rights', 'access', 'end'],
  groups: {
    change: {
      title: 'account.groupChange',
      layout: 'buttons',
      buttons: [
        'account.changeDisplayName',
        'account.changeUsername',
        'account.makeOperator',
        'account.makeMember',
        'account.storageLimit',
        'account.emailRemove',
      ],
    },
    rights: { title: 'account.groupRights', layout: 'list', buttons: [] },
    access: {
      title: 'account.groupAccess',
      layout: 'buttons',
      buttons: ['account.resetLink', 'account.factorReset', 'account.signOutAccount', 'account.unlinkProvider'],
    },
    end: { title: 'account.groupEnd', layout: 'buttons', buttons: ['account.block', 'account.unblock', 'account.remove', 'account.restore'] },
  },
} as const satisfies {
  title: string
  picture: number
  parts: readonly string[]
  groups: Record<ManageGroup, { title: string; layout: 'buttons' | 'list'; buttons: readonly ButtonName[] }>
}

/** Since 0.3.9: a button of the module in the dialog "Manage". */
export type ManageButton =
  | (typeof MANAGE_DIALOG.groups.change.buttons)[number]
  | (typeof MANAGE_DIALOG.groups.access.buttons)[number]
  | (typeof MANAGE_DIALOG.groups.end.buttons)[number]

/** Since 0.3.9: the switches of an app, what its server can do for the operator; a switch left out is off, and its
 * buttons do not show. ``rename``: display name and username; ``roles``: operator or member; ``emailRemove``: take an
 * account's address; ``resetLink``: a link for a new password; ``factorReset``: reset the second factor;
 * ``signOut``: sign an account out everywhere; ``unlink``: take a provider's link; ``blocking``: block and unblock;
 * ``remove``: delete; ``restore``: bring a deleted account back while its days run. ``inviteRole`` (since 0.3.10): the
 * field "Role" in the dialog "Invite"; left out it follows ``roles`` as before (nextasks changes roles but invites
 * members only: ``inviteRole: false``). */
export const ACCOUNT_CAPS = [
  'rename',
  'roles',
  'emailRemove',
  'resetLink',
  'factorReset',
  'signOut',
  'unlink',
  'blocking',
  'remove',
  'restore',
  'inviteRole',
  'storageLimit',
  'ai',
  'immich',
] as const

export type AccountCap = (typeof ACCOUNT_CAPS)[number]

export type AccountCaps = Partial<Record<AccountCap, boolean>>

/** Since 0.3.9: which switch each button of the module needs. */
export const MANAGE_CAP: Record<ManageButton, AccountCap> = {
  'account.changeDisplayName': 'rename',
  'account.changeUsername': 'rename',
  'account.makeOperator': 'roles',
  'account.makeMember': 'roles',
  'account.storageLimit': 'storageLimit',
  'account.emailRemove': 'emailRemove',
  'account.resetLink': 'resetLink',
  'account.factorReset': 'factorReset',
  'account.signOutAccount': 'signOut',
  'account.unlinkProvider': 'unlink',
  'account.block': 'blocking',
  'account.unblock': 'blocking',
  'account.remove': 'remove',
  'account.restore': 'restore',
}

/** Since 0.3.9: what the dialog never offers on the operator's own account: that is changed in the profile and under
 * security (and an operator does not demote, block or delete themself). An app's own button with ``notSelf`` too.
 * Since 0.3.10 also "Sign out everywhere" (it would sign the operator out of this very page; the own account has
 * "Sign out everywhere else" under security) and "Unlink" (the own providers are under security). */
export const NOT_ON_SELF = [
  'account.makeOperator',
  'account.makeMember',
  'account.block',
  'account.unblock',
  'account.remove',
  'account.resetLink',
  'account.factorReset',
  'account.signOutAccount',
  'account.unlinkProvider',
] as const satisfies readonly ManageButton[]

/** Since 0.3.9: how an act in the dialog is confirmed. ``password``: a dialog with the operator's own password
 * (``account.confirmWithPassword``; an operator without a password signs in fresh at their provider,
 * ``account.confirmFresh``, as ``confirmLine`` says); ``ask``: a question without a password; ``none``: at once. */
export type ManageConfirm = 'password' | 'ask' | 'none'

/** Since 0.3.9: how each act is confirmed and the sentence of its dialog (text key; ``{{name}}`` the account's name,
 * ``{{provider}}`` the provider, ``{{email}}`` the address, ``{{app}}`` the app; '' none). Everything that changes or
 * ends an account asks for the password; signing out everywhere and withdrawing an invitation only ask; the app's boxes
 * of rights save at once. The dialog's title and confirming button are the act's own words, kind and symbol.
 * ``account.remove``: the app adds its numbers (notes, mailboxes, events, documents) after ``text``, then
 * ``removeLines`` (nexpaper brings its own dialog for handing documents on). The renaming dialogs have their field
 * (``FIELDS.displayName``; ``FIELDS.username`` with ``account.usernameRules``) and save with ``account.save``. */
export const MANAGE_CONFIRM = {
  'account.changeDisplayName': { confirm: 'password', text: '' },
  'account.changeUsername': { confirm: 'password', text: 'account.askChangeUsername' },
  'account.makeOperator': { confirm: 'password', text: 'account.askMakeOperator' },
  'account.makeMember': { confirm: 'password', text: 'account.askMakeMember' },
  'account.storageLimit': { confirm: 'password', text: '' },
  'account.emailRemove': { confirm: 'password', text: 'account.askEmailRemove' },
  'account.resetLink': { confirm: 'password', text: 'account.askResetLink' },
  'account.factorReset': { confirm: 'password', text: 'account.factorResetHint' },
  'account.signOutAccount': { confirm: 'ask', text: 'account.askSignOut' },
  'account.unlinkProvider': { confirm: 'password', text: 'account.askUnlink' },
  'account.block': { confirm: 'password', text: 'account.askBlock' },
  'account.unblock': { confirm: 'password', text: 'account.askUnblock' },
  'account.remove': { confirm: 'password', text: 'account.askRemove' },
  'account.restore': { confirm: 'password', text: 'account.askRestore' },
  'account.inviteWithdraw': { confirm: 'ask', text: 'account.askInviteWithdraw' },
} as const satisfies Record<ManageButton | 'account.inviteWithdraw', { confirm: ManageConfirm; text: string }>

/** Since 0.3.9: how an act of the dialog (the module's, or the app's by its name) is confirmed: the app's own buttons
 * with the password like the module's, its boxes at once. */
export function manageConfirm(action: Pick<AccountAction, 'type' | 'name' | 'own'>): ManageConfirm {
  if (action.type === 'check') return 'none'
  if (action.own) return 'password'
  const base = action.name.split(':')[0] ?? ''
  return base in MANAGE_CONFIRM ? MANAGE_CONFIRM[base as keyof typeof MANAGE_CONFIRM].confirm : 'password'
}

/** Since 0.3.9: the line above the password field of a ``password`` dialog. */
export function confirmLine(operatorHasPassword: boolean): 'account.confirmWithPassword' | 'account.confirmFresh' {
  return operatorHasPassword ? 'account.confirmWithPassword' : 'account.confirmFresh'
}

/** Since 0.3.9: the line of the question "Delete account" after the app's numbers: how many days it can be brought
 * back (``account.askRemoveDays`` with ``count``) where the app can, else that it cannot be undone. */
export function removeLines(caps: AccountCaps): Array<'account.askRemoveDays' | 'account.askRemoveFinal'> {
  return caps.restore ? ['account.askRemoveDays'] : ['account.askRemoveFinal']
}

/** Since 0.3.9: an app's own button in the dialog "Manage": its name (unique there), its words (the app's text key),
 * its group, its look by a name in ``BUTTONS`` (the module's or a role: ``storageLimit``, ``handOver``), and its fixed
 * place: before or after one of the module's buttons of that group (else at the end of the group); the place holds
 * where that button does not show. ``notSelf``: not on the operator's own account (``handOver``). Confirmed with the
 * password like the module's. */
export interface OwnButton {
  name: string
  label: string
  group: Exclude<ManageGroup, 'rights'>
  button: ButtonName
  before?: ManageButton
  after?: ManageButton
  notSelf?: boolean
  values?: Readonly<Record<string, string>>
}

/** Since 0.3.9: an app's own right as a box to tick in the group ``rights`` (``CheckboxRow``: "AI allowed", "Immich
 * allowed"), saved at once without a question; ``checked`` its state for this account. */
export interface OwnCheck {
  name: string
  label: string
  group: 'rights'
  checked: boolean
  hint?: string
  notSelf?: boolean
}

export type OwnAction = OwnButton | OwnCheck

/** Since 0.3.9: one thing the dialog "Manage" offers, in its order: a button (``kind`` and ``icon`` from ``BUTTONS``,
 * by ``button``) or a box to tick. ``values`` fill the words (``{{provider}}`` of ``account.unlinkProvider``);
 * ``provider`` is the link to take. ``own``: the app's. */
export type AccountAction =
  | {
      type: 'button'
      name: string
      label: string
      group: Exclude<ManageGroup, 'rights'>
      button: ButtonName
      kind: ButtonKind
      icon: string
      confirm: ManageConfirm
      own: boolean
      values?: Readonly<Record<string, string>>
      provider?: ListedProvider
    }
  | {
      type: 'check'
      name: string
      label: string
      group: 'rights'
      checked: boolean
      confirm: 'none'
      own: boolean
      hint?: string
      /** Since 1.1.0: a right of the module (``ai``, ``immich``); the app saves it through ``manage.set_right``. */
      right?: Right
    }

type ButtonAction = Extract<AccountAction, { type: 'button' }>

/** Since 0.3.9: the buttons and boxes the dialog "Manage" shows for one account, in their order, by the app's switches
 * (``caps``) and the rules: nothing of ``NOT_ON_SELF`` (nor an own ``notSelf``) on the operator's own account;
 * "Reset the second factor" only with an authenticator or a passkey; "Remove address" only with an address; "Unlink"
 * once per linked provider; "Make operator" or "Make member" by the role, "Block" or "Unblock" by the state; a deleted
 * account shows nothing but "Bring back" (with ``restore``, while it has its day). ``own``: the app's buttons and boxes
 * at their fixed places. */
export function accountActions(row: ListedAccount, caps: AccountCaps, own: readonly OwnAction[] = []): AccountAction[] {
  const visible = (name: ManageButton): boolean => {
    if (!caps[MANAGE_CAP[name]]) return false
    if (row.self && (NOT_ON_SELF as readonly string[]).includes(name)) return false
    if (row.deletedAt) return name === 'account.restore' && Boolean(row.purgeAt)
    switch (name) {
      case 'account.makeOperator':
        return !row.operator
      case 'account.makeMember':
        return row.operator
      case 'account.emailRemove':
        return Boolean(row.email)
      case 'account.factorReset':
        return hasSecondFactor(row)
      case 'account.block':
        return !row.blocked
      case 'account.unblock':
        return Boolean(row.blocked)
      case 'account.restore':
        return false
      default:
        return true
    }
  }
  const moduleButton = (name: ManageButton, group: Exclude<ManageGroup, 'rights'>): ButtonAction[] => {
    if (!visible(name)) return []
    const spec = BUTTONS[name]
    const base: ButtonAction = { type: 'button', name, label: name, group, button: name, kind: spec.kind, icon: spec.icon, confirm: MANAGE_CONFIRM[name].confirm, own: false }
    if (name !== 'account.unlinkProvider') return [base]
    return row.providers.map((provider) => ({ ...base, name: `${name}:${provider.id}`, values: { provider: provider.label }, provider }))
  }
  const ownButton = (entry: OwnButton): ButtonAction[] => {
    if (row.deletedAt || (row.self && entry.notSelf)) return []
    const spec = BUTTONS[entry.button]
    const action: ButtonAction = { type: 'button', name: entry.name, label: entry.label, group: entry.group, button: entry.button, kind: spec.kind, icon: spec.icon, confirm: 'password', own: true }
    if (entry.values) action.values = entry.values
    return [action]
  }
  const shown: AccountAction[] = []
  for (const group of MANAGE_GROUPS) {
    if (group === 'rights') {
      if (row.deletedAt) continue
      for (const right of RIGHTS) {
        if (!caps[right]) continue
        shown.push({ type: 'check', name: RIGHT_TEXT[right], label: RIGHT_TEXT[right], group: 'rights', checked: (row.rights ?? []).includes(right), confirm: 'none', own: false, right })
      }
      for (const entry of own) {
        if (entry.group !== 'rights' || (row.self && entry.notSelf)) continue
        const check: AccountAction = { type: 'check', name: entry.name, label: entry.label, group: 'rights', checked: entry.checked, confirm: 'none', own: true }
        if (entry.hint !== undefined) check.hint = entry.hint
        shown.push(check)
      }
      continue
    }
    const mine = own.filter((entry): entry is OwnButton => entry.group === group)
    const placed = new Set<OwnButton>()
    const at = (name: ManageButton, where: 'before' | 'after'): ButtonAction[] =>
      mine
        .filter((entry) => !placed.has(entry) && entry[where] === name)
        .flatMap((entry) => {
          placed.add(entry)
          return ownButton(entry)
        })
    for (const name of MANAGE_DIALOG.groups[group].buttons) {
      shown.push(...at(name, 'before'), ...moduleButton(name, group), ...at(name, 'after'))
    }
    for (const entry of mine) if (!placed.has(entry)) shown.push(...ownButton(entry))
  }
  return shown
}

/** Since 0.3.9: the groups the dialog shows for these actions (only those with anything), each with its title and
 * layout, in ``MANAGE_GROUPS`` order. */
export function manageGroups(actions: readonly AccountAction[]): Array<{
  group: ManageGroup
  title: string
  layout: 'buttons' | 'list'
  actions: AccountAction[]
}> {
  return MANAGE_GROUPS.map((group: ManageGroup) => ({
    group,
    title: MANAGE_DIALOG.groups[group].title,
    layout: MANAGE_DIALOG.groups[group].layout,
    actions: actions.filter((action) => action.group === group),
  })).filter((entry) => entry.actions.length > 0)
}

/** Since 0.3.9: the dialog "Invite" (``ui``: ``Dialog`` with ``Field``, ``SelectField``, ``CheckboxRow``), fields top to
 * bottom: the address (free, hint ``account.inviteEmailHint``), the display name (free), the role (only with
 * ``caps.roles``; member by default), how long it holds (``INVITE_DAYS``, 7 by default), the box "Send by mail" (only
 * with a mail server and an address typed). The button makes the link (``account.linkMake``) or sends it
 * (``account.linkSend``, box ticked). Afterwards: ``account.inviteSent`` where it went by mail, and always the link to
 * copy (``account.inviteLink``, hint ``account.inviteLinkHint`` with ``{{day}}``), ``copy`` and ``done``. No username:
 * the person picks it. */
export const INVITE_DIALOG = {
  title: 'account.inviteTitle',
  fields: ['email', 'displayName', 'role', 'days', 'sendMail'],
  emailHint: 'account.inviteEmailHint',
  role: { label: 'account.role', options: ['member', 'operator'], texts: { member: 'account.roleMember', operator: 'account.roleOperator' }, default: 'member' },
  days: { label: 'account.validFor', options: INVITE_DAYS, default: INVITE_DAYS_DEFAULT },
  sendMail: 'account.inviteSendMail',
  submit: { make: 'account.linkMake', send: 'account.linkSend' },
  cancel: 'cancel',
  done: { sent: 'account.inviteSent', link: 'account.inviteLink', linkHint: 'account.inviteLinkHint', copy: 'copy', close: 'done' },
} as const

export type InviteField = (typeof INVITE_DIALOG.fields)[number]

/** Since 0.3.9: the fields the dialog "Invite" shows now. The role since 0.3.10 by ``caps.inviteRole``, left out by
 * ``caps.roles`` as before. */
export function inviteFields(caps: AccountCaps, state: { mailServer: boolean; email: string }): InviteField[] {
  return INVITE_DIALOG.fields.filter((field: InviteField) => {
    if (field === 'role') return caps.inviteRole ?? Boolean(caps.roles)
    if (field === 'sendMail') return state.mailServer && state.email.trim().includes('@')
    return true
  })
}

/** Since 0.3.9: the words of the button of "Invite" and of "Link for a new password": it sends where the link goes by
 * mail, else it makes the link to hand on. */
export function linkSubmit(sends: boolean): 'account.linkMake' | 'account.linkSend' {
  return sends ? 'account.linkSend' : 'account.linkMake'
}

/** Since 0.3.9: the dialog "Link for a new password" (``account.resetLink``): the sentence, how long it holds
 * (``RESET_DAYS``, 1 by default), the password; with a mail server and an address it goes there by mail
 * (``account.resetLinkSent``), else it shows once to copy (``account.resetLinkShown``). */
export const RESET_LINK_DIALOG = {
  title: 'account.resetLink',
  text: 'account.askResetLink',
  days: { label: 'account.validFor', options: RESET_DAYS, default: RESET_DAYS_DEFAULT },
  sent: 'account.resetLinkSent',
  shown: 'account.resetLinkShown',
} as const

/** Since 0.3.10: the kinds of access that stay after a new password (``Access.kind`` on the server, ``ACCESS_KINDS``),
 * the same names in every app, each with its words for "These devices still have access". */
export const ACCESS_KINDS = {
  device: 'account.accessDevice',
  calendar: 'account.accessCalendar',
  contacts: 'account.accessContacts',
  'api_key': 'account.accessApiKey',
  passkey: 'account.accessPasskey',
} as const

export type AccessKind = keyof typeof ACCESS_KINDS

/** Since 0.3.10: the words of an access kind; '' for a kind the module does not know (the label shows alone). */
export function accessKindText(kind: string): string {
  return Object.hasOwn(ACCESS_KINDS, kind) ? ACCESS_KINDS[kind as AccessKind] : ''
}

/** Since 0.3.10: the namespace of the texts belongs to the module. An app keeps no text of its own under ``account``
 * (nextime had ``account.later``); the vitest template checks that the app's texts there are the module's, word for
 * word, and nothing else. */
export const ACCOUNT_NAMESPACE = 'account'

/** Since 0.3.9: an invitation still open, as the list knows it. Since 0.3.10 said plainly: the app's route lists an
 * expired invitation too, with ``expired: true``, until the operator withdraws it (the contract test
 * ``test_the_list_route_keeps_expired_invitations`` holds every app to it). */
export interface ListedInvite {
  id: number | string
  displayName?: string
  email?: string
  /** The fixed name of an invitation of an older version. */
  username?: string
  role?: 'operator' | 'member'
  /** When it stops holding (ISO). */
  expiresAt: string
  /** Where the server says so; else from ``expiresAt``. */
  expired?: boolean
}

/** Since 0.3.9: the card "Open invitations" under the list (``ui``: ``Card``, ``Rows``, ``Row``), only while there are
 * any. One row each: the name (display name, older username, else the address, else ``account.inviteNoName``), the
 * address small under it where the name is not the address, the badges (operator where it makes one, then how long it
 * holds: ``account.inviteUntil`` with ``{{day}}``, or ``account.inviteExpired``; expired ones stay until withdrawn), and
 * "Withdraw" (``account.inviteWithdraw``, danger) with a question without password (``MANAGE_CONFIRM``). */
export const OPEN_INVITES = {
  title: 'account.openInvites',
  row: ['name', 'badges', 'lines', 'withdraw'],
  noName: 'account.inviteNoName',
  valid: { text: 'account.inviteUntil', tone: 'off' },
  expired: { text: 'account.inviteExpired', tone: 'warn' },
  withdraw: 'account.inviteWithdraw',
} as const

/** Since 0.3.9: one row of the open invitations: ``name`` as it is, or ``nameText`` (a text key) where there is none;
 * ``sub`` the address under it; the badges (``date``: ``{{day}}``). */
export function inviteRow(
  invite: ListedInvite,
  now = Date.now(),
): { name: string; nameText: string; sub: string; badges: BadgeShown[]; expired: boolean } {
  const email = invite.email?.trim() ?? ''
  const named = invite.displayName?.trim() || invite.username?.trim() || ''
  const expired = invite.expired ?? Date.parse(invite.expiresAt) <= now
  const badges: BadgeShown[] = []
  if (invite.role === 'operator') badges.push({ badge: 'operator', text: ACCOUNT_BADGES.operator.text, tone: ACCOUNT_BADGES.operator.tone })
  badges.push(
    expired
      ? { badge: 'invite', text: OPEN_INVITES.expired.text, tone: OPEN_INVITES.expired.tone }
      : { badge: 'invite', text: OPEN_INVITES.valid.text, tone: OPEN_INVITES.valid.tone, date: invite.expiresAt },
  )
  return { name: named || email, nameText: named || email ? '' : OPEN_INVITES.noName, sub: named ? email : '', badges, expired }
}

// --- Since 1.1.0: the settings (plan "Einstellungen") ------------------------------------------------------------------

/** Since 1.1.0: what the operator's functions offer beyond what every app has, by feature, the apps that have it (the
 * same table as ``config.FEATURES`` on the server): a storage limit per account where accounts keep files, "AI allowed"
 * where the app has AI built in, "Immich allowed" where Immich is connected (decided 25.11.2026). */
export const FEATURES = {
  storageLimit: ['nexnotes', 'nexpaper', 'nexdiary', 'nexlore'],
  ai: ['nexmail', 'nexpaper', 'nexdiary', 'nexlore'],
  immich: ['nexdiary'],
} as const satisfies Record<string, readonly string[]>

export type Feature = keyof typeof FEATURES

/** Since 1.1.0: the features of an app by its name. */
export function featuresOf(app: string): Feature[] {
  const name = app.trim().toLowerCase()
  return (Object.keys(FEATURES) as Feature[]).filter((feature) => (FEATURES[feature] as readonly string[]).includes(name))
}

/** Since 1.1.0: the rights of an account, boxes to tick in "Rights" of the dialog "Manage", saved at once (the server's
 * ``manage.set_right`` with these names). */
export const RIGHTS = ['ai', 'immich'] as const

export type Right = (typeof RIGHTS)[number]

export const RIGHT_TEXT: Record<Right, string> = { ai: 'account.rightAi', immich: 'account.rightImmich' }

/** Since 1.1.0: the account functions every app has (several operators, block, delete with 30 days to bring back,
 * decided 25.11.2026). */
export const STANDARD_CAPS = { roles: true, blocking: true, remove: true, restore: true } as const satisfies AccountCaps

/** Since 1.1.0: the switches of the dialog "Manage" for an app: what it has of its own (``rename``, ``resetLink`` …,
 * as before), the standard ones, and its features from ``FEATURES``. The standard ones and the features are not the
 * app's to switch off. */
export function capsOf(app: string, own: AccountCaps = {}): AccountCaps {
  const features = featuresOf(app)
  return {
    ...own,
    ...STANDARD_CAPS,
    storageLimit: features.includes('storageLimit'),
    ai: features.includes('ai'),
    immich: features.includes('immich'),
  }
}

/** Since 1.1.0: how long a deleted account can be brought back (``manage.DELETE_DAYS``), ``count`` of
 * ``account.askRemoveDays``. */
export const DELETE_DAYS = 30

/** Since 1.1.0: the storage limit's field takes GB (the server takes bytes). */
export const STORAGE_LIMIT_UNIT = 1024 ** 3

/** Since 1.1.0: the dialog of the storage limit (``account.storageLimit``): title with ``{{name}}``, the field in GB
 * with what the account uses under it, "Remove limit" while it has one, and the app's sentence of what the limit stops
 * (its own text) after ``text``. */
export const STORAGE_LIMIT_DIALOG = {
  title: 'account.storageLimitTitle',
  field: 'account.storageLimitField',
  used: 'account.storageUsed',
  remove: 'account.storageLimitRemove',
  save: 'account.save',
} as const

/** Since 1.1.0: the fact "Storage" of an account in the dialog "Manage" (``FactShown``): used of the limit, or used
 * without one. ``size`` writes a number of bytes the app's way. */
export function storageFact(
  row: Pick<ListedAccount, 'storageLimit' | 'storageUsed'>,
  size: (bytes: number) => string,
): FactShown {
  const used = size(row.storageUsed ?? 0)
  return row.storageLimit
    ? { fact: 'storage', label: 'account.storage', text: 'account.storageUsedOf', values: { used, limit: size(row.storageLimit) } }
    : { fact: 'storage', label: 'account.storage', text: 'account.storageUsedNoLimit', values: { used } }
}

// --- Appearance ---

/** Since 1.1.0: light, dark, as the device says (ui ``ThemeSegment``), kept at the account on every device (E5, E17;
 * ``profiles.change_theme``). */
export const THEMES = ['light', 'dark', 'system'] as const

export type Theme = (typeof THEMES)[number]

export const THEME_DEFAULT: Theme = 'system'

/** Since 1.1.0: the account's theme, ``system`` while it has chosen none. */
export function themeOf(value: string | null | undefined): Theme {
  return (THEMES as readonly string[]).includes(value ?? '') ? (value as Theme) : THEME_DEFAULT
}

/** Since 1.1.0: the value a browser kept before 1.1.0 (``nexnotes.theme`` = ``dark``, nexmail's JSON ``"dark"``), as a
 * theme, else '' (nothing to hand the server, ``profiles.adopt_theme``). The app names its own key. */
export function browserTheme(raw: string | null | undefined): Theme | '' {
  const value = (raw ?? '').trim().replace(/^"|"$/g, '').trim().toLowerCase()
  return (THEMES as readonly string[]).includes(value) ? (value as Theme) : ''
}

/** Since E49: what the box "Passkeys" under My account › Security shows where passkeys are added: the button "Add a
 * passkey" where the server says it can (``passkeys.can_add``: a public https address, or the page on localhost), else
 * the sentence that the address is missing; an operator gets the place to enter it (``account.passkeysNeedAddressPlace``,
 * a link to Server › Sign-in), a member only the sentence. Passkeys the account has stay listed and removable. */
export function passkeyAddition(canAdd: boolean, operator: boolean): { button: boolean; note: string; place: string } {
  if (canAdd) return { button: true, note: '', place: '' }
  return operator
    ? { button: false, note: 'account.passkeysNeedAddress', place: 'account.passkeysNeedAddressPlace' }
    : { button: false, note: 'account.passkeysNeedAddressMember', place: '' }
}

/** Since 1.1.0: the card "Appearance", first on the page Appearance of every app (``AppearanceCard``): id, symbol, the
 * title from ui (``appearance``, "Aussehen"), the ``ThemeSegment`` with its hint. */
export const APPEARANCE_CARD = { id: 'appearance', icon: 'Palette' } as const

// --- Profile ---

/** Since 1.1.0: the box "Address not confirmed yet" in the profile of every app (``UnconfirmedEmailBox``; nexpaper had
 * it as a line): for an address that counts but no link has proven yet (``profiles.prove_email``), while a mail server
 * can send the link. "Send link" (``account.emailProveSend``, ``sm``), then ``account.emailProveSent``. The same as
 * ``profiles.needs_proof`` on the server. Addresses of before the update count as proven (E23: the migration to 1.1.0
 * marks them; nexpaper keeps its unproven ones), so the box shows only for one entered from now on. */
export function showUnconfirmed(
  me: { email?: string | null; emailConfirmed?: boolean; emailProven?: boolean; pendingEmail?: string | null },
  mailServer: boolean,
): boolean {
  return Boolean(me.email) && me.emailConfirmed !== false && me.emailProven === false && !me.pendingEmail && mailServer
}

export const UNCONFIRMED_BOX = {
  title: 'account.emailUnconfirmed',
  hint: 'account.emailUnconfirmedHint',
  button: 'account.emailProveSend',
  sent: 'account.emailProveSent',
} as const

/** Since 1.1.0: the card "Sign out" of every profile (``SignOutCard``): the module's sentence with the app's word for
 * its things (``{{things}}``: Notizen, Mails …), with a provider the sentence that it stays signed in there, the button
 * ``account.signOut``. Where the app knows changes that still wait (nexnotes, nextime, nexfolk), it asks first. */
export const SIGN_OUT_CARD = {
  id: 'sign-out',
  icon: 'LogOut',
  title: 'account.signOut',
  text: 'account.signOutText',
  provider: 'account.signOutProvider',
  button: 'account.signOut',
  pending: 'account.signOutPending',
  wait: 'account.waitForChanges',
  anyway: 'account.signOutAnyway',
} as const

// --- Accounts ---

/** Since 1.1.0: the card "What you see" under Server › Accounts in all eight apps (ShieldCheck): the app's sentence
 * (its own text key, "Als Betreiber siehst du …, aber nie …"). */
export const WHAT_YOU_SEE_CARD = { id: 'accounts-what-you-see', icon: 'ShieldCheck', title: 'account.whatYouSee' } as const

// --- Server › Sign-in ---

/** Since 1.1.0: the page Server › Sign-in of every app, top to bottom (``SignInPage``): the emergency hammer's notice
 * (only while it is down), "Ready for the internet?", the card "Sign-in", then the module oidc's cards "Sign-in
 * providers" and "authentik in one step". */
export const SIGN_IN_PAGE = ['secondFactorOff', 'readiness', 'signIn', 'providers', 'authentik'] as const

/** Since 1.1.0: the card "Sign-in", its parts top to bottom: password sign-in, the public address (field with
 * "Save" beside it), the second factor for everybody (on only with a factor of one's own, off only with the password),
 * passkeys allowed with its hint. */
export const SIGN_IN_CARD = {
  id: 'sign-in',
  icon: 'ShieldCheck',
  title: 'oidc.admin.signInTitle',
  parts: ['passwordLogin', 'publicUrl', 'factorRequired', 'passkeysAllowed'],
  passwordLogin: { label: 'oidc.admin.password', hint: 'oidc.admin.passwordHint' },
  publicUrl: { label: 'oidc.admin.address', hint: 'oidc.admin.addressHint', button: 'account.save' },
  factorRequired: {
    label: 'account.factorRequiredSwitch',
    hint: 'account.factorRequiredSwitchHint',
    locked: 'account.ownSecondFactorFirst',
    /** Since E36: after the hint, who is not affected (accounts whose provider checks the second factor itself);
     * ``{{trusts}}`` is the words of oidc's switch ``oidc.admin.trustsSecondFactor``. */
    exempt: 'account.factorRequiredExempt',
    exemptLocked: 'account.factorRequiredExemptLocked',
    offTitle: 'account.factorRequiredOffTitle',
    offText: 'account.factorRequiredOffText',
    offButton: 'account.factorRequiredOff',
  },
  passkeysAllowed: { label: 'account.passkeysAllowed', hint: 'account.passkeysAllowedHint' },
} as const

/** Since 1.1.0: the placeholder of the public address per app (nexlore showed nexnotes'). */
export const PUBLIC_URL_PLACEHOLDERS = {
  nexnotes: 'https://notes.example.com',
  nexmail: 'https://mail.example.com',
  nextasks: 'https://tasks.example.com',
  nextime: 'https://time.example.com',
  nexpaper: 'https://paper.example.com',
  nexdiary: 'https://diary.example.com',
  nexlore: 'https://lore.example.com',
  nexfolk: 'https://folk.example.com',
} as const satisfies Record<string, string>

/** Since 1.1.1 (E57): the hint of "Mail bei neuer Anmeldung" (``account.newSignInMailHint``, in the app's words already)
 * with an optional sentence of the app after it, where its notice goes further (nexpaper: "Auch als Mitteilung auf
 * deinen Geräten."). Without a sentence the module's hint alone, as before. */
export function newSignInMailHint(hint: string, sentence?: string | null): string {
  const more = (sentence ?? '').trim()
  return more ? `${hint.trim()} ${more}` : hint
}

export function publicUrlPlaceholder(app: string): string {
  const name = app.trim().toLowerCase()
  return (PUBLIC_URL_PLACEHOLDERS as Record<string, string>)[name] ?? `https://${name.replace(/^nex/, '') || 'app'}.example.com`
}

/** Since 1.1.0: "Ready for the internet?" (``readiness`` on the server): the common points in their order, the states,
 * the card. */
export const READY_POINTS = ['address', 'factorForAll', 'ownAccount', 'brake', 'cookies', 'proxy'] as const

export const READY_STATES = ['ok', 'warn', 'bad'] as const

export type ReadyState = (typeof READY_STATES)[number]

export interface ReadyPoint {
  key: string
  state: ReadyState
  /** Text keys: the module's ``account.ready.<key>.title`` and ``…<variant>``, or the app's own. */
  title: string
  text: string
  values: Record<string, unknown>
}

export interface Readiness {
  state: ReadyState
  open: number
  points: ReadyPoint[]
}

export const READY_CARD = {
  id: 'sign-in-ready',
  icon: 'ShieldCheck',
  title: 'account.ready.title',
  text: 'account.ready.text',
  open: 'account.ready.open',
  allGood: 'account.ready.allGood',
  /** What a point's symbol says to a reader. */
  state: { ok: 'account.ready.state.ok', warn: 'account.ready.state.warn', bad: 'account.ready.state.bad' },
} as const satisfies { state: Record<ReadyState, string> } & Record<string, unknown>

/** Since 1.1.0: the worst state of the points (the colour of the card's symbol), as the server says it. */
export function readyState(points: readonly Pick<ReadyPoint, 'state'>[]): ReadyState {
  return points.some((point) => point.state === 'bad') ? 'bad' : points.some((point) => point.state === 'warn') ? 'warn' : 'ok'
}
