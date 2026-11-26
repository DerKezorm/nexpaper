/**
 * Since 1.1.0: the kit's own words, in German, English and French. Everything else (titles, labels, the app's sentences)
 * comes from the caller. Which language: the one a `NexuiLanguage` above says, else the page's (`<html lang>`), else
 * English. A caller may still hand over its own words for a part (`texts` on `AboutPage` and `NotifyWays`).
 *
 * `{app}`, `{version}`, `{name}` are filled by the kit; `{things}` is the app's word for what its accounts keep as
 * subject or object ("Kalender"), `{thingsDative}` the same after a word that asks for the dative ("Kalendern"; since
 * E34; in English and French both the same: "calendars").
 *
 * `areas` holds the title and line of each shared area of the settings (plan "Einstellungen", the table under
 * "Navigation"); an app's own areas keep their own words.
 */
import { createContext, createElement, useContext, type ReactNode } from 'react'

export type NexuiLanguageCode = 'de' | 'en' | 'fr'

const DE = {
  copy: 'Kopieren',
  copied: 'Kopiert',
  remove: 'Entfernen',
  removeName: '{name} entfernen',
  settings: 'Einstellungen',
  groupAccount: 'Mein Konto',
  groupServer: 'Server',
  aboutApp: 'Über {app}',
  backToList: 'Einstellungen',
  themeLabel: 'Hell oder dunkel',
  themeLight: 'Hell',
  themeDark: 'Dunkel',
  themeSystem: 'Wie das System',
  themeHint: 'Gilt auf allen deinen Geräten. „Wie das System“ folgt dem Gerät.',
  appearance: 'Aussehen',
  aboutVersion: 'Version',
  aboutNewer: 'Version {version} ist erschienen',
  aboutWhatsNew: 'Was ist neu',
  aboutWhatsNewButton: 'Neu in {app} {version}',
  aboutLicence: 'Lizenz',
  aboutSource: 'Quelltext',
  aboutReleases: 'Veröffentlichungen',
  aboutReleasesLink: 'Alle Versionen und was sich geändert hat',
  aboutProject: 'Projektseite',
  aboutReport: 'Einen Fehler gefunden?',
  aboutReportLink: 'Auf GitHub melden',
  updatesTitle: 'Aktualisierungen',
  updatesText: 'Ob es eine neuere Version von {app} gibt.',
  updatesDaily: 'Einmal am Tag nachsehen',
  updatesDailyHint: 'Fragt GitHub nach der neuesten Veröffentlichung. Aus: nur, wenn du den Knopf drückst.',
  updatesNow: 'Jetzt nachsehen',
  updatesNotYet: 'Noch nicht nachgesehen.',
  updatesOff: 'Das tägliche Nachsehen ist aus.',
  updatesCurrent: 'Das ist die neueste Version.',
  updatesNone: 'Noch keine Veröffentlichung gefunden.',
  updatesToRelease: 'Was neu ist',
  updatesCheckedAt: 'zuletzt nachgesehen {when}',
  updatesWhatGoesOut:
    'Hinaus geht nur die Frage: eine Anfrage an api.github.com nach der neuesten Veröffentlichung von {app}, ohne Namen, Inhalte oder Einstellungen. Es ist der einzige Ruf, den {app} von sich aus macht.',
  builtWith: 'Gebaut mit',
  whatsNewWhere: 'Wo:',
  whatsNewDone: 'Verstanden',
  close: 'Schließen',
  // Since 1.1.2 (E65): a moment of today or yesterday (`formatMoment`).
  today: 'heute',
  yesterday: 'gestern',
  notifyTitle: 'Auf welchem Weg',
  notifyMail: 'Mail',
  notifyConfirmed: 'bestätigt',
  notifyUnconfirmed: 'nicht bestätigt',
  notifyChangeInProfile: 'Im Profil ändern',
  notifyThisBrowser: 'Dieser Browser',
  notifyOn: 'An',
  notifyOff: 'Aus',
  notifyTurnOn: 'Mitteilungen einschalten',
  notifyTurnOff: 'Ausschalten',
  notifyProbe: 'Probemeldung schicken',
  notifyBrowsers: 'Browser mit Mitteilungen',
  notifyNoBrowsers: 'Noch kein Browser.',
  notifyCurrent: 'Dieser Browser',
  notifyDevices: 'iPhone und iPad',
  notifyDevicesHint: 'Mitteilungen aufs iPhone und iPad kommen über die App; verbunden wird sie unter „Verbindungen“.',
  notifyToConnections: 'Zu den Verbindungen',
  areas: {
    'profile': { title: 'Profil', text: 'Bild, Name, Mailadresse, Sprache und Rolle deines Kontos.' },
    'security': { title: 'Sicherheit', text: 'Passwort, zweiter Faktor, Passkeys, Anmeldeanbieter und wo du angemeldet bist.' },
    'appearance': { title: 'Darstellung', text: 'Hell oder dunkel und wie {app} bei dir aussieht.' },
    'notifications': { title: 'Benachrichtigungen', text: 'Was dich auf welchem Weg erreicht.' },
    'connections': { title: 'Verbindungen', text: 'Geräte, andere Apps, API-Schlüssel und KI-Werkzeuge, die mit deinen {thingsDative} arbeiten.' },
    'general': { title: 'Allgemein', text: 'Grenzen, Funktionen für alle Konten, Schnittstellen und eigene Sprachen.' },
    'sign-in': { title: 'Anmeldung', text: 'Wie sich alle anmelden: Passwort, öffentliche Adresse, zweiter Faktor und Anbieter.' },
    'mail': { title: 'Mail', text: 'Der Mailserver, über den {app} Einladungen, Links und Benachrichtigungen verschickt.' },
    'storage': { title: 'Speicher und Sicherung', text: 'Der belegte Platz und die Sicherungen des Servers.' },
    'accounts': { title: 'Konten', text: 'Wer {app} nutzt, mit Rolle, offene Einladungen und die API-Schlüssel aller Konten.' },
    'log': { title: 'Log', text: 'Was der Server mitschreibt, zum Nachsehen bei Fehlern.' },
    'about': { title: 'Über {app}', text: 'Version, Lizenz, Herkunft und ob es eine neuere Version gibt.' },
    'ai-provider': { title: 'KI-Anbieter', text: '' },
  },
}

export type NexuiTexts = typeof DE

const EN: NexuiTexts = {
  copy: 'Copy',
  copied: 'Copied',
  remove: 'Remove',
  removeName: 'Remove {name}',
  settings: 'Settings',
  groupAccount: 'My account',
  groupServer: 'Server',
  aboutApp: 'About {app}',
  backToList: 'Settings',
  themeLabel: 'Light or dark',
  themeLight: 'Light',
  themeDark: 'Dark',
  themeSystem: 'As the system',
  themeHint: 'Applies on all your devices. “As the system” follows the device.',
  appearance: 'Look',
  aboutVersion: 'Version',
  aboutNewer: 'Version {version} is out',
  aboutWhatsNew: "What's new",
  aboutWhatsNewButton: 'New in {app} {version}',
  aboutLicence: 'Licence',
  aboutSource: 'Source code',
  aboutReleases: 'Releases',
  aboutReleasesLink: 'All versions and what changed',
  aboutProject: 'Project page',
  aboutReport: 'Found a problem?',
  aboutReportLink: 'Report it on GitHub',
  updatesTitle: 'Updates',
  updatesText: 'Whether a newer version of {app} is out.',
  updatesDaily: 'Check once a day',
  updatesDailyHint: 'Asks GitHub for the newest release. Off: only when you press the button.',
  updatesNow: 'Check now',
  updatesNotYet: 'Not checked yet.',
  updatesOff: 'The daily check is off.',
  updatesCurrent: 'This is the newest version.',
  updatesNone: 'No release found yet.',
  updatesToRelease: 'What is new',
  updatesCheckedAt: 'last checked {when}',
  updatesWhatGoesOut:
    'Only the question goes out: a request to api.github.com for the newest release of {app}, with no names, content or settings. It is the only call {app} makes on its own.',
  builtWith: 'Built with',
  whatsNewWhere: 'Where:',
  whatsNewDone: 'Got it',
  close: 'Close',
  // Since 1.1.2 (E65): a moment of today or yesterday (`formatMoment`).
  today: 'today',
  yesterday: 'yesterday',
  notifyTitle: 'Which way',
  notifyMail: 'Mail',
  notifyConfirmed: 'confirmed',
  notifyUnconfirmed: 'not confirmed',
  notifyChangeInProfile: 'Change in profile',
  notifyThisBrowser: 'This browser',
  notifyOn: 'On',
  notifyOff: 'Off',
  notifyTurnOn: 'Turn on notifications',
  notifyTurnOff: 'Turn off',
  notifyProbe: 'Send a test notification',
  notifyBrowsers: 'Browsers with notifications',
  notifyNoBrowsers: 'No browser yet.',
  notifyCurrent: 'This browser',
  notifyDevices: 'iPhone and iPad',
  notifyDevicesHint: 'Notifications on iPhone and iPad come through the app; it is connected under “Connections”.',
  notifyToConnections: 'To connections',
  areas: {
    'profile': { title: 'Profile', text: 'Picture, name, email address, language and role of your account.' },
    'security': { title: 'Security', text: 'Password, second factor, passkeys, sign-in providers and where you are signed in.' },
    'appearance': { title: 'Appearance', text: 'Light or dark and how {app} looks for you.' },
    'notifications': { title: 'Notifications', text: 'What reaches you, and which way.' },
    'connections': { title: 'Connections', text: 'Devices, other apps, API keys and AI tools that work with your {thingsDative}.' },
    'general': { title: 'General', text: 'Limits, features for every account, interfaces and added languages.' },
    'sign-in': { title: 'Sign-in', text: 'How everyone signs in: password, public address, second factor and providers.' },
    'mail': { title: 'Mail', text: 'The mail server {app} sends invitations, links and notifications through.' },
    'storage': { title: 'Storage and backups', text: 'The space in use and the backups of the server.' },
    'accounts': { title: 'Accounts', text: 'Who uses {app}, with role, open invitations and the API keys of all accounts.' },
    'log': { title: 'Log', text: 'What the server writes down, to look into problems.' },
    'about': { title: 'About {app}', text: 'Version, licence, where it comes from and whether a newer version is out.' },
    'ai-provider': { title: 'AI provider', text: '' },
  },
}

const FR: NexuiTexts = {
  copy: 'Copier',
  copied: 'Copié',
  remove: 'Retirer',
  removeName: 'Retirer {name}',
  settings: 'Réglages',
  groupAccount: 'Mon compte',
  groupServer: 'Serveur',
  aboutApp: 'À propos de {app}',
  backToList: 'Réglages',
  themeLabel: 'Clair ou sombre',
  themeLight: 'Clair',
  themeDark: 'Sombre',
  themeSystem: 'Comme le système',
  themeHint: 'S’applique sur tous tes appareils. « Comme le système » suit l’appareil.',
  appearance: 'Apparence',
  aboutVersion: 'Version',
  aboutNewer: 'La version {version} est parue',
  aboutWhatsNew: 'Nouveautés',
  aboutWhatsNewButton: 'Nouveau dans {app} {version}',
  aboutLicence: 'Licence',
  aboutSource: 'Code source',
  aboutReleases: 'Publications',
  aboutReleasesLink: 'Toutes les versions et ce qui a changé',
  aboutProject: 'Page du projet',
  aboutReport: 'Un problème ?',
  aboutReportLink: 'Le signaler sur GitHub',
  updatesTitle: 'Mises à jour',
  updatesText: 'Si une version plus récente de {app} est parue.',
  updatesDaily: 'Vérifier une fois par jour',
  updatesDailyHint: 'Demande à GitHub la dernière publication. Désactivé : seulement quand tu appuies sur le bouton.',
  updatesNow: 'Vérifier maintenant',
  updatesNotYet: 'Pas encore vérifié.',
  updatesOff: 'La vérification quotidienne est désactivée.',
  updatesCurrent: 'C’est la version la plus récente.',
  updatesNone: 'Aucune publication trouvée pour l’instant.',
  updatesToRelease: 'Les nouveautés',
  updatesCheckedAt: 'dernière vérification {when}',
  updatesWhatGoesOut:
    'Seule la question sort : une requête à api.github.com pour la dernière publication de {app}, sans noms, contenus ni réglages. C’est le seul appel que {app} fait de lui-même.',
  builtWith: 'Construit avec',
  whatsNewWhere: 'Où :',
  whatsNewDone: 'Compris',
  close: 'Fermer',
  // Since 1.1.2 (E65): a moment of today or yesterday (`formatMoment`).
  today: 'aujourd’hui',
  yesterday: 'hier',
  notifyTitle: 'Par quel moyen',
  notifyMail: 'E-mail',
  notifyConfirmed: 'confirmée',
  notifyUnconfirmed: 'non confirmée',
  notifyChangeInProfile: 'Modifier dans le profil',
  notifyThisBrowser: 'Ce navigateur',
  notifyOn: 'Activé',
  notifyOff: 'Désactivé',
  notifyTurnOn: 'Activer les notifications',
  notifyTurnOff: 'Désactiver',
  notifyProbe: 'Envoyer une notification d’essai',
  notifyBrowsers: 'Navigateurs avec notifications',
  notifyNoBrowsers: 'Aucun navigateur pour l’instant.',
  notifyCurrent: 'Ce navigateur',
  notifyDevices: 'iPhone et iPad',
  notifyDevicesHint: 'Les notifications sur iPhone et iPad passent par l’app ; elle se connecte sous « Connexions ».',
  notifyToConnections: 'Vers les connexions',
  areas: {
    'profile': { title: 'Profil', text: 'Photo, nom, adresse e-mail, langue et rôle de ton compte.' },
    'security': { title: 'Sécurité', text: 'Mot de passe, second facteur, clés d’accès, fournisseurs de connexion et où tu es connecté.' },
    'appearance': { title: 'Apparence', text: 'Clair ou sombre et l’allure de {app} chez toi.' },
    'notifications': { title: 'Notifications', text: 'Ce qui te parvient, et par quel moyen.' },
    'connections': { title: 'Connexions', text: 'Appareils, autres apps, clés API et outils d’IA qui travaillent avec tes {thingsDative}.' },
    'general': { title: 'Général', text: 'Limites, fonctions pour tous les comptes, interfaces et langues ajoutées.' },
    'sign-in': { title: 'Connexion', text: 'Comment tout le monde se connecte : mot de passe, adresse publique, second facteur et fournisseurs.' },
    'mail': { title: 'E-mail', text: 'Le serveur de messagerie par lequel {app} envoie invitations, liens et notifications.' },
    'storage': { title: 'Stockage et sauvegardes', text: 'L’espace occupé et les sauvegardes du serveur.' },
    'accounts': { title: 'Comptes', text: 'Qui utilise {app}, avec son rôle, les invitations ouvertes et les clés API de tous les comptes.' },
    'log': { title: 'Journal', text: 'Ce que le serveur consigne, pour examiner les erreurs.' },
    'about': { title: 'À propos de {app}', text: 'Version, licence, provenance et si une version plus récente est parue.' },
    'ai-provider': { title: 'Fournisseur d’IA', text: '' },
  },
}

export const NEXUI_TEXTS: Record<NexuiLanguageCode, NexuiTexts> = { de: DE, en: EN, fr: FR }

const Chosen = createContext<NexuiLanguageCode | null>(null)

/** Sets the kit's language for everything below it ("de", "en", "fr"; any other: English). */
export function NexuiLanguage({ language, children }: { language: string; children: ReactNode }) {
  return createElement(Chosen.Provider, { value: languageOf(language) }, children)
}

/** "de-CH" -> "de"; a language the kit has no words for -> "en". */
export function languageOf(language: string | null | undefined): NexuiLanguageCode {
  const base = (language ?? '').toLowerCase().split(/[-_]/)[0]
  return base === 'de' || base === 'fr' ? base : 'en'
}

/** The kit's words in the language that counts here. */
export function useNexuiTexts(): NexuiTexts {
  const chosen = useContext(Chosen)
  const page = typeof document === 'undefined' ? null : document.documentElement.lang
  return NEXUI_TEXTS[chosen ?? languageOf(page)]
}

/** Fills `{name}` and the like in one of the kit's sentences. */
export function fill(text: string, values: Record<string, string | number>): string {
  return text.replace(/\{(\w+)\}/g, (whole, key: string) => (key in values ? String(values[key]) : whole))
}

/** The slugs of the areas every app shares (`/settings/<slug>`). */
export type SharedAreaSlug = keyof NexuiTexts['areas']

/** Title and line of a shared area, filled with the app's name and word for its things; null for an app's own area. */
export function areaText(
  texts: NexuiTexts,
  slug: string,
  values: { app: string; things?: string; thingsDative?: string },
): { title: string; text: string } | null {
  const area = (texts.areas as Record<string, { title: string; text: string } | undefined>)[slug]
  if (!area) return null
  // Since E34 two forms: `things` ("Deine Kalender") and `thingsDative` ("mit deinen Kalendern"); without the second
  // the first stands in.
  const filled = { app: values.app, things: values.things ?? '', thingsDative: values.thingsDative ?? values.things ?? '' }
  return { title: fill(area.title, filled), text: fill(area.text, filled) }
}
