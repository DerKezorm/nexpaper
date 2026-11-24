# Anbindung des Kontenmoduls (`nexkonten`) an nexpaper

Stand 24.11.2026, Zweig `konten`. Vorbereitung, noch nichts angebunden. Maßgeblich sind der Entwurf in nexlore
(`Development/nexapps/Baupläne/Entwurf Konten, Einrichtung und Anmeldung.md`) und die Schnittstelle des Moduls
(`bauplaene/konten/SCHNITTSTELLE.md`, Zweig `konten`, Fassung 0.1.0, dazu `oidc` 1.1.0). Wo dieser Plan von beiden
abweicht oder etwas offen lässt, steht es unter „Passt das Modul?“ und „Offene Fragen“.

Grundsatz: **Für niemanden, der nexpaper 1.12.0 benutzt, fällt ein Weg hinein weg.** Der Test „Bestand“ beweist das
(Abschnitt 10). nexpaper ist die App, die dem Entwurf schon am nächsten ist (Einrichtungscode, beide Wege für ein
vergessenes Passwort, Adresse mit Bestätigungslink, Namensregeln wie im Modul). Die Reibung liegt woanders: **Eine
bestätigte Adresse entscheidet in nexpaper, wessen Tresor eine Mail an den Posteingang erreicht**, und **der
Benutzername ist Ordnername und Plus-Adresse des Eingangs**.

## 1. Bestand heute (1.12.0, Schema 20)

### Datenmodell

| Tabelle | Was zum Konto gehört |
|---|---|
| `users` | `id` (Integer, an ihm hängt alles), `name` (String 64, `unique`, **immer klein**, Muster `^[a-z0-9][a-z0-9._-]{1,63}$`, gleich den Regeln des Moduls), `display_name` (80, leer: der Name wird gezeigt), `role` (`operator`/`member`, mehrere Betreiber möglich), `sign_in` (`password`/`oidc`), `password_hash` (Argon2id, leer: nur Anbieter), `email` (255, **nicht eindeutig**), `email_confirmed_at` (gesetzt nur durch den Bestätigungslink), `email_from_provider`, `language` (am Konto, leer: Browser), `failed_logins`/`locked_until` (Sperre nach 5 Fehlversuchen für 15 Minuten), `blocked_at` (gesperrt), `totp_*`, `avatar`/`avatar_at` (WebP), `passkey_handle`, `ai_allowed`, `profile` (JSON) |
| `invites` | `token_hash`, `email` (frei), `created_by`, `expires_at` (Betreiber wählt **1, 7 oder 30 Tage**). Kein Anzeigename, kein Name |
| `password_resets` | `token_hash`, `account_id`, `created_by` (leer: selbst angefordert), `expires_at` (**24 Stunden**, beide Wege) |
| `email_confirmations` | wartende Adresse: `account_id` (eindeutig), `address`, `token_hash`, `expires_at` (24 Stunden) |
| `mail_senders` | weitere bestätigte Absenderadressen je Person (nur Posteingang, eigener Link), nicht Teil des Kontos |
| `auth_sessions`, `devices` (`npd_…`), `api_keys` (`npk_…`), `passkeys`, `push_devices`, `pairings`, `oidc_links` | alle an `account_id`/`user_id` |
| `vaults` | je Konto ein persönlicher Tresor (`personal_of`), angelegt im selben Schreibvorgang wie das Konto (`models._make_personal_vault`): `name` = Anzeigename oder Name, `folder` = Ordner auf der Platte, **einmal vergeben, nie umbenannt** |

Es gibt keinen Zustand „gelöscht“: Löschen entfernt die Zeile (Dokumente gehen nach Wahl an andere), der Name wird frei.

### Dienste und Router

| Ort | Was |
|---|---|
| `routers/auth.py` | `GET/POST /api/v1/setup` (`name`, `password`, `language`, `code`; Code aus `NEXPAPER_SETUP_TOKEN` oder Log), `POST /auth/login` (`name` ≤ 64, `password`, `remember`), `/auth/me` (`name`, `display_name`, `email`, `email_confirmed`, `email_pending`, `language` …), `PUT /me/profile` (`display_name`), `PUT /me/language`, Betreiber: `/accounts`, Sperren, Rolle, Löschen (mit `confirm_name`) |
| `services/accounts.py` | `by_name` (klein), `check_name`, `authenticate` (Blindhash, Sperre je Konto, bekannte Browser ausgenommen, eine Prüfung je Konto zugleich), Einladungen |
| `routers/invites.py` | `POST /invites` (`days`, `email`, `send`), `GET/POST /invite/{token}` (`name`, `password`) |
| `routers/resets.py`, `services/resets.py` | `POST /auth/forgot` (`name`: Name **oder Adresse**), `GET/POST /reset/{token}`, `POST /accounts/{id}/reset-link` (Betreiber, eigenes Passwort; mit Mail an die Adresse, sonst einmal gezeigt) |
| `routers/emails.py`, `services/emails.py` | `PUT /me/email` (`email`, `password`; **ohne Mailserver abgelehnt**, `mail_off`), `DELETE /me/email/pending`, `GET/POST /email/confirm/{token}`; Bescheid an die alte bestätigte Adresse |
| `routers/oidc.py`, `services/oidc_store.py`, `vendor/nexoidc` 1.0.14 | Anbieter; Adresse vom Anbieter **unbestätigt**, folgt dem Anbieter, bis die Person eine eigene setzt |
| `routers/intake.py`, `services/intake.py`, `intake_folder.py`, `intake_mail.py`, `mail_senders.py` | Posteingang: Unterordner `<eingang>/<name>/`, Plus-Adresse `<postfach>+<name>@…`, sonst eine **bestätigte** Absenderadresse genau einer Person |
| `app/reset_link.py` | Kommandozeile: Link für ein Konto nach Name |

### iPhone-App (nexpaper-ios, im App Store)

Kein eigenes Anmeldeformular: Koppeln per QR-Code oder Browser-Anmeldung (`ASWebAuthenticationSession`, OAuth2 mit
PKCE). Der Server antwortet beim Koppeln mit `account` = **Benutzername** (`routers/pairing.py:108, 231`,
`routers/devices.py:79`). Die App speichert ihn in `Connection.account` und nutzt ihn **als Schlüssel**
(Abschnitt 2).

### Tests

`cd backend && .venv/Scripts/python.exe -m pytest` (pytest-xdist ist nicht installiert). Konten:
`test_accounts.py`, `test_invites.py`, `test_password_links.py`, `test_reset_link.py`, `test_emails.py`,
`test_profile.py`, `test_hardening_auth.py`, `test_oidc_*.py`, Vertrag `tests/nexoidc/`, Wächter
`test_no_attribution.py`, `test_nothing_real_in_the_repo.py`. Frontend `cd frontend && npx vitest run
--maxWorkers=2`.

## 2. Wo der Benutzername mehr ist als Anzeige

**bricht** = ein Umbenennen machte etwas kaputt; **lösen** = vor dem Ändern-Knopf anfassen; **harmlos** = Anzeige,
Protokoll, Momentaufnahme.

| Stelle | Rolle des Namens | Bewertung |
|---|---|---|
| `services/intake_folder.py:191, 203, 429`, `routers/intake.py:121, 323` | **Eingangsordner**: `<eingang>/<name>/` gehört dem Konto mit diesem Namen; Scanner und Kopierer legen dort ab | **bricht**: Nach dem Umbenennen landet alles im alten Ordner beim Betreiber („unbekannt“); nimmt später jemand den alten Namen, landen die Dokumente **in dessen Eingang**. Lösung: alte Namen bleiben dem Konto als Ordner-Name erhalten (Tabelle früherer Namen, die auch nie neu vergeben werden) oder der Ordner hängt an der ID; neuer Ordner wird angelegt, alter bleibt gültig |
| `services/intake_mail.py:695-708`, `services/intake.py:50-59`, `routers/intake.py:303-305, 320` | **Plus-Adresse** `<postfach>+<name>@…` ordnet Mails dem Konto zu | **bricht** wie oben: alte Plus-Adresse liefe zum Betreiber oder zum neuen Träger des Namens (fremde Dokumente im falschen Tresor). Gleiche Lösung: frühere Namen gelten weiter und sind gesperrt |
| `users.name unique` (`models.py:85`), `accounts.by_name` | eindeutig; Namen sind immer klein, also auch ohne Groß/Klein eindeutig | harmlos; Index auf `lower(name)` kommt trotzdem (Vertrag des Moduls), ein Doppel ist im Bestand unmöglich |
| `routers/pairing.py:108, 231`, `routers/devices.py:79` → **nexpaper-ios** `Connection.account` | Schlüssel in der App: `AppModel.swift:170` (anderer `account` beim Koppeln = **lokaler Speicher, Warteschlange und Katalog werden geleert**), `SharedSetup.swift:23-43` (iCloud-Abgleich iPhone ↔ iPad über `address + account`), `AppModel.swift:191` | **bricht (mittel)**: Wer umbenennt und dann ein Gerät neu koppelt (etwa nach „Passwort vergessen“, das alle Geräte abmeldet), verliert noch nicht hochgeladene Scans der Warteschlange; iPad und iPhone gleichen ihre Einrichtung nicht mehr ab. Lösung: Server schickt zusätzlich `account_id` (nur ergänzend), App vergleicht über die ID und frischt den Namen aus `/auth/me` auf. Muss **vor** dem Ändern-Knopf in den Store |
| `models.py:847` persönlicher Tresor `name = display_name or name` | Name des Tresors = Kopie beim Anlegen | harmlos: bleibt wie er ist (Tresore sind umbenennbar). `folder` ändert sich nie |
| `routers/v1.py:67` `/api/v1/me` `name` → **nextime** (`services/nexpaper.py:274`, nimmt `display_name or name` als Beschriftung beim Verbinden), **nexdeck** (`adapters/nexpaper.py:129`, Text des Verbindungstests) | Antwortfeld | harmlos: Momentaufnahme. Die Fristen (`/api/v1/deadlines`) tragen keinen Namen |
| `routers/schemas.py:175` `PersonRef(name, display_name)` in Dokumenten, Teilen, Verlauf | Anzeige | harmlos (live aus der Zeile) |
| `services/passkeys.py:235` `user_name` | Name im Passwortmanager | harmlos: alte Passkeys zeigen den alten Namen, gelten weiter (`passkey_handle` ist zufällig) |
| `routers/totp.py:103` `provisioning_uri(name)` | Beschriftung im Authenticator | harmlos |
| `services/paperless.py:642` | Import aus Paperless: Besitzer nach Name/Anzeigename zuordnen | harmlos (einmaliger Vorgang, Vorschlag) |
| `app/reset_link.py:83-106` | Kommandozeile sucht nach Name | harmlos: nimmt dann den neuen |
| `routers/auth.py:744` Löschen mit `confirm_name` | Abtippen zur Sicherheit | harmlos |
| `services/notices.py:237, 297`, Mails in `mailer.py` (Name im Text), `routers/apikeys.py:130` (`account` in der Schlüsselliste) | Text, Anzeige | harmlos |
| `deps.py:178, 217, 245`, `logs.set_actor` und alle `name=%s` im Log | Protokoll | harmlos: alte Zeilen behalten den alten Namen; die neue Zeile „Username changed“ nennt beide |
| Sitzungen, Geräte, API-Schlüssel, Passkeys, Push, OIDC-Verknüpfung, Rücksetz- und Bestätigungslinks, Sicherungen, Verlauf (`events.user_id`), Freigaben | alle an der ID | harmlos |

Ergebnis: **Zwei Stellen brechen beim Umbenennen**, beide im Posteingang (Ordner und Plus-Adresse), und eine dritte in
der iPhone-App (Warteschlange). Bis sie gelöst sind, bekommt nexpaper keinen Knopf „Benutzername ändern“.

## 3. Zuordnung nexpaper ↔ Modul

| Modul | nexpaper |
|---|---|
| `id` (`int`) | `users.id` |
| `username` | `users.name` |
| `display_name` | `users.display_name` |
| `email` | `users.email` |
| `email_confirmed` | **nicht** `email_confirmed_at`. Für das Modul (Anmelden, Passwort vergessen) gilt eine Adresse, wenn sie **eigen** ist (`email_from_provider = 0`) oder per Link bestätigt wurde. Siehe unten und „Passt das Modul?“ 1 |
| `email_source` | `provider`, wenn `email_from_provider`, sonst `""` |
| `pending_email` | `email_confirmations.address` |
| `has_password` | `sign_in == 'password' and password_hash != ''` |
| `blocked` | `blocked_at IS NOT NULL` |
| `operator` | `role == 'operator'` |
| `picture` | `avatar` leer → `""`, sonst neu `avatar_source or "own"` |
| `language` | `users.language` |
| `Invite` | `invites` (Rechte: keine, `rights` = Zeile), neu `display_name` |
| `Reset` | `password_resets` |
| `EmailChange` | `email_confirmations` |

**Zwei Bedeutungen von „bestätigt“.** Heute heißt `email_confirmed_at` nur: *die Person hat einen Link an diese
Adresse geöffnet*. Daran hängen Posteingang (`mail_senders.owners`), Erinnerungsmails, Bescheide und der Versand von
Exporten. Das Modul meint mit `email_confirmed`: *die Adresse zählt zum Anmelden und für „Passwort vergessen“*, und es
setzt sie auch ohne Link als bestätigt (Einladung, Ersteinrichtung, Änderung ohne Mailserver, Bestand). Würde der Store
beides auf `email_confirmed_at` legen, könnte jede selbst getippte Adresse ohne Mailserver fremde Mails in den eigenen
Tresor ziehen. Deshalb:

- `email_confirmed_at` bleibt „per Link bewiesen“ und wird nur gesetzt, wenn das Modul einen Bestätigungslink
  einlöst (`confirm_email`) oder die Adresse aus dem Bestand schon so war.
- Neue Spalte `email_counts` (Boolean, Vorgabe **wahr**): die Adresse zählt für das Modul. Bestand: eigene Adressen
  zählen (sonst verlören Konten mit der Adresse ihrer Einladung „Passwort vergessen“, was 1.12.0 kann), Adressen vom
  Anbieter nicht (`email_from_provider = 1` → falsch).
- `Account.email_confirmed = email_counts`. `set_email(confirmed=…)` schreibt `email_counts`; ob der Aufruf aus einem
  eingelösten Link kommt, merkt sich der Store in `consume_email_change` (dieselbe Transaktion) und setzt dann auch
  `email_confirmed_at`. Sauberer wäre ein Feld im Protokoll („Passt das Modul?“ 1).

Store `services/konten_store.py` (neu), eine Instanz je Anfrage wie `oidc_store.SqlStore`. `check_password(None, …)`
mit `accounts._dummy_hash`; `set_password` hasht, setzt `sign_in = 'password'`, hebt `failed_logins`/`locked_until`
auf, löscht alle offenen Links; `end_sessions` = `security.end_all_sessions` (Browser **und** Geräte, wie heute) plus
`totp.forget_account`. `add_account` legt wie heute über das ORM an (der persönliche Tresor entsteht im selben
Schreibvorgang), setzt `whats_new_seen`. Mails baut nexpaper aus `Mail` mit `mailer.send_reset`/`send_confirm`
(Vorlagen und Sprache wie heute) und neu `send_username_changed`.

`nexoidc` 1.1.0 im selben Zug: `clean_name` → `nexkonten.clean_username`, `name_taken` →
`nexkonten.username_taken`, `create_account(…, display_name, picture)` setzt den Anzeigenamen aus dem Claim `name`
(heute bleibt er leer), `provider_picture` im Hintergrund über `services/avatars.py` (WebP, quadratisch) mit
`UPDATE users SET avatar=…, avatar_source='provider' WHERE id=? AND avatar IS NULL`.

## 4. Wanderung (nur ergänzend, Schema 21)

Ein Schritt `_step_accounts` in `db.py` (`SCHEMA_VERSION = 21`); davor macht `_init` schon heute eine Sicherung
(`backups.create(kind=UPDATE)`).

| Neu | Typ, Vorgabe | Bedeutung |
|---|---|---|
| `users.email_counts` | Boolean, `server_default 1`; im Schritt `UPDATE users SET email_counts = 0 WHERE email_from_provider = 1` | eigene Bestandsadressen zählen (Regel 2), Adressen vom Anbieter nicht |
| `users.avatar_source` | String(16), `server_default ''` | vorhandene Bilder gelten als eigene |
| `invites.display_name` | String(80), `server_default ''` | Anzeigename, den der Betreiber vorgibt |
| `account_names` (neu) | `name` (eindeutig, klein), `account_id`, `until` | frühere Benutzernamen: bleiben dem Konto für Eingangsordner und Plus-Adresse und werden nie neu vergeben (Abschnitt 2). Leer im Bestand |
| Index `uq_users_name_lower` auf `lower(name)` | eindeutig | erst nach Zählen (`GROUP BY lower(name) HAVING count(*) > 1`); im Bestand kann es kein Doppel geben, die Zählung bleibt trotzdem, ein Doppel bricht den Start nie ab |
| Index auf `lower(email)` | **nicht** eindeutig | doppelte Adressen gibt es im Bestand (Familien, Test „Bestand“) |

Rückweg auf 1.12.0 eine Fassung lang: 1.12.0 verweigert Schema 21 (`check_version`); Rückweg also nur über die
Sicherung vor der Wanderung, wie bei jedem Schemaschritt in nexpaper. Alternative ohne Schemaschritt gibt es nicht,
weil neue Spalten in nexpaper immer einen Schritt brauchen.

## 5. Routen

**Feldnamen bleiben** (`name`, `password`, `email`, `display_name`, `code`, `days`). Antworten bekommen nur Felder dazu.

| Route | Heute | Künftig |
|---|---|---|
| `GET /api/v1/setup` | `needs_setup`, `code_required`, `min_password` | gleich |
| `POST /api/v1/setup` | `name`, `password`, `language`, `code` | dazu `display_name` (Pflicht laut Entwurf; fehlt er, nimmt die Route `name`, damit Skripte nicht brechen), `email` (frei) → `nexkonten.setup`. Code über `nexkonten.setup_code` (gleiche Variable `NEXPAPER_SETUP_TOKEN`) |
| Sicherung einspielen vor der Einrichtung | gibt es nicht (Wiederherstellen nur als Betreiber) | nichts zu tun; kommt es, ruft es `check_code` |
| `POST /api/v1/auth/login` | `name` ≤ 64 | `name` ≤ **254** (Adresse), Inhalt „Benutzername oder E-Mail“. **Nicht** `nexkonten.authenticate` allein: nexpaper behält die Sperre je Konto mit Ausnahme bekannter Browser und die eine Prüfung je Konto zugleich (`accounts.authenticate`); es ersetzt nur `by_name` durch `nexkonten.resolve_login`. Gesperrte Konten antworten wie heute wie ein falsches Passwort (offene Frage 3) |
| `POST /api/v1/auth/forgot` | `name`: Name oder Adresse; an jede Adresse auf dem Konto, bis zu 5 Konten je Adresse, Link 24 h | Feldname bleibt; `nexkonten.forgot` **im Hintergrundauftrag** (`notices.later`, wie heute, damit die Zeit nichts verrät), eigene Bremse je Konto bleibt; Link **1 Stunde**; eine geteilte Adresse findet kein Konto mehr |
| `GET/POST /api/v1/reset/{token}` | 24 h | `reset_state`/`use_reset`; offene Links der Vorfassung gelten (gleiche Tabelle, gleicher Hash) |
| `POST /api/v1/accounts/{id}/reset-link` | `current_password`; Mail an jede Adresse | `reset_link`; Mail nur an eine Adresse, die zählt, sonst angezeigt; 24 h |
| `PUT /api/v1/me/email` | `email`, `password`; ohne Mailserver 409 | `change_email`; ohne Mailserver gilt die Adresse sofort (zählt fürs Anmelden, **nicht** für den Posteingang, Abschnitt 3); Bescheid an die alte bestätigte Adresse bleibt (App) |
| `DELETE /api/v1/me/email/pending`, `GET/POST /api/v1/email/confirm/{token}` | | `withdraw_email_change`, `email_change_state`, `confirm_email` |
| `PUT /api/v1/me/profile` | `display_name` | gleich, `change_display_name` |
| neu `PUT /api/v1/me/username` | – | `name`, `password` → `change_username`; **erst nach** Abschnitt 2 |
| `POST /api/v1/invites` | `days`, `email`, `send` | dazu `display_name`; `days` bleibt (offene Frage 2) |
| `GET /api/v1/invite/{token}` | `min_password`, `signed_in_as` | dazu `display_name`, `name` (Vorschlag), `email` aus `invite_form` |
| `POST /api/v1/invite/{token}` | `name`, `password` | dazu `display_name`, `email` (frei). Fehlt `display_name` (Anfrage von 1.12.0), nimmt die Route den Namen; der Test „Bestand“ prüft das |
| `GET /api/v1/auth/me`, `GET /api/v1/accounts` | `name`, `display_name`, `email`, `email_confirmed` | `email_confirmed` bleibt „per Link“; dazu `email_counts`, `email_duplicate` (Betreiber) |
| neu `PUT /api/v1/accounts/{id}/username`, `/display-name`, `DELETE /api/v1/accounts/{id}/email` | – | Betreiber, eigenes Passwort |
| Koppeln (`/devices/pair`, `/oauth/token`, `/devices`, `/devices/sibling`) | `account` (Name) | dazu `account_id` (für nexpaper-ios) |

## 6. Oberfläche

Vorgabe: optisch so wenig wie möglich ändern; was sich ändert, überall gleich, Vorbild nexnotes. nexpaper hat seit
1.11.0 schon die Bausteine von nexnotes (`AuthFrame`, `Input` mit `label`/`hint`, `Primary`, `Problem`, `Card`,
`Dialog`, `Toggle`, `Select`, `CopyLink`, `useConfirm`). Kein neuer Baustein.

| Bildschirm | Heute | Künftig | Sichtbar anders |
|---|---|---|---|
| **Anmelden** (`AuthPages.tsx` `LoginPage`) | „Name“, „Passwort“, „Angemeldet bleiben“, „Passwort vergessen?“, Passkey, Anbieter | gleich | Beschriftung „Benutzername oder E-Mail“, Fehlertext `account.wrong` |
| **Einrichtung** (`SetupPage`) | Einrichtungscode, Name, Passwort | Einrichtungscode, Anzeigename, Benutzername (folgt dem Anzeigenamen), E-Mail, Passwort, Passwort wiederholen, Sprache | vier Felder mehr, Reihenfolge nach `SCREENS.setup` |
| **Einladung** (`InvitePage`) | Name (mit Regelhinweis), Passwort, darunter Anbieter | Anzeigename (aus der Einladung), Benutzername (Vorschlag), E-Mail (aus der Einladung), Passwort, Passwort wiederholen, „oder“, Anbieter | drei Felder mehr |
| **Passwort vergessen** (`ForgotPage`) | „Name oder Mailadresse“, Satz „… 24 Stunden“; ohne Mailserver Hinweis `reset_off` | „Benutzername oder E-Mail“, `account.forgotSent`; ohne Mailserver `account.forgotNoMail` | Wortlaute; Link gilt eine Stunde |
| **Neues Passwort** (`ResetPage`) | zwei Felder, Satz mit Name | gleich | nichts |
| **Profil** (Einstellungen › Mein Konto › Profil) | Karte: Bild, „Name“ (= Anzeigename), E-Mail mit Bestätigungszeile, Zeile „Rolle · Anmeldename“, Sprache | Bild, Anzeigename, **Benutzername** (Feld mit Passwortabfrage im `Dialog`), E-Mail, Sprache, Rolle klein | Benutzername sichtbar und änderbar (erst nach Abschnitt 2); „Anmeldename“ verschwindet; Zeile „Mailadresse nicht bestätigt“ bleibt für den Posteingang |
| **Konten** (Server › Konten) | Zeile: Anzeigename, klein Adresse oder Name; Menü: Link, Sperren, Rolle, KI, Löschen | klein „Benutzername · E-Mail“, Hinweis bei doppelter Adresse; Menü dazu Anzeigename/Benutzername ändern, Adresse entfernen | neue Menüpunkte, eine Plakette |
| **Person einladen** (Dialog) | Gültig für (1/7/30 Tage), Mailadresse, Senden | dazu Anzeigename (frei) | ein Feld mehr |
| **Mein Posteingang** (Hochladen) | Ordner `<eingang>/<name>/`, Plus-Adresse | zeigt den aktuellen Namen; frühere gelten weiter (Hinweis) | Hinweiszeile nach einer Umbenennung |

Wortlaute: Namensraum `account` aus `vendor/nexkonten` in `de.json`/`en.json`/`fr.json` (Französisch fehlt dem Modul,
wie bei `oidc`: eigene `i18n/konten.fr.json`). Die alten Schlüssel `auth.name`, `auth.nameHint`,
`auth.forgot.label`, `me.profile.name`, `me.profile.roleLine` fallen weg, sobald nichts sie mehr liest. Vor dem
Festschreiben wird jede geänderte Ansicht gezeigt und abgenommen.

## 7. Passwort vergessen

Beide Wege gibt es schon. Was sich ändert: der selbst angeforderte Link gilt **1 statt 24 Stunden**; eine Adresse,
die mehrere Konten haben, findet keins mehr (per Benutzername geht der Link weiter an die eigene Adresse); eine
Adresse vom Anbieter zählt nicht. Der Betreiber-Link bleibt 24 Stunden.

## 8. Einrichtungscode

Gibt es schon (`NEXPAPER_SETUP_TOKEN`, Code im Log). Er wandert ins Modul (`nexkonten.setup_code`), Wortlaut und
Variable bleiben gleich. Einen Weg „Sicherung einspielen vor der Einrichtung“ hat nexpaper nicht.

## 9. Einladungen

Der Betreiber gab nie einen Namen vor; künftig zusätzlich einen Anzeigenamen. Die Dauer wählt er heute (1/7/30 Tage);
das Modul liest nur `expires_at` und lässt das zu, der Entwurf sagt „7 Tage überall“ (offene Frage 2). Offene
Einladungen von 1.12.0 gelten weiter und nehmen die Anfrage von 1.12.0 an (nur `name` und `password`).

## 10. Test „Bestand“

`backend/tests/test_bestand.py` mit `backend/tests/bestand/bestand-1.12.0.sql.gz`, gebaut von 1.12.0 selbst mit
`tests/bestand/build.py` (erfundene Konten in `bestand-1.12.0.json`). Start:

    cd backend && .venv/Scripts/python.exe -m pytest tests/test_bestand.py -q

Konten: `betreiber` (eigene bestätigte Adresse, zweiter Faktor, Wiederherstellungscodes), `anna` (bestätigt,
API-Schlüssel, gekoppeltes iPhone, selbst angeforderter offener Link), `ben` (Adresse der Einladung, **nicht
bestätigt**, offener Link vom Betreiber), `carla`/`dora` (eine Adresse in zwei Schreibweisen, eine bestätigt, eine
nicht), `emil` (keine Adresse, wartende neue Adresse, offene Browsersitzung), `fritz` (nur Anbieter, Adresse vom
Anbieter), `greta` (Passwort und Anbieter), `hans` (gesperrt), `ida` (gelöscht), zwei offene Einladungen (mit und
ohne Adresse). Geprüft (57 Fälle): Start ergänzt nur (keine Spalte, keine Zeile verloren), Adressen und ihr
Bestätigt-Zustand bleiben, Tresorordner bleiben, Anmelden mit Name in jeder Schreibweise, zweiter Faktor und
Wiederherstellungscode, Anbieter, Sitzung, Gerät, API-Schlüssel, offene Einladungen mit der Anfrage von 1.12.0,
offene Links beider Arten, wartende Adresse per Link, „Passwort vergessen“ per Name (auch mit unbestätigter und mit
geteilter Adresse) und per eindeutiger Adresse (auch unbestätigt), nichts ohne Weg, Sperre nach fünf Fehlversuchen
je Konto, „Anmeldung mit Passwort aus“, gesperrt und gelöscht bleiben draußen.

`xfail(strict=True)` (werden mit der Anbindung grün, dann Marker weg): Anmelden mit eindeutiger bestätigter Adresse;
eine geteilte Adresse findet bei „Passwort vergessen“ kein Konto mehr.

Gegen Mutationen geprüft (jede Rückgabecode 1): Name mit Groß/Klein verglichen; „vergessen“ nur an per Link bestätigte
Adressen (so würde ein naiver Store auf `email_confirmed_at` brechen); Start löscht offene Einladungen, beendet
Sitzungen, löscht Anbieterverknüpfungen, bestätigt alle Adressen, sperrt Geräte; keine Sperre nach Fehlversuchen;
Einladung verlangt einen Anzeigenamen; Rücksetzlinks mit anderem Hash; Anmelden mit Adresse eingebaut, Marker
vergessen (strenges xfail wird rot).

Vor dem Aufspielen dieselbe Probe auf einer **Kopie** der Live-Datenbank: doppelte Adressen zählen, die Fassung gegen
die Kopie starten.

## 11. Risiken

1. **Posteingang vertraut „bestätigt“.** Legt der Store `email_confirmed` auf `email_confirmed_at`, ziehen Adressen
   ohne Link (Einladung, ohne Mailserver) Mails in fremde Tresore. Abschnitt 3.
2. **Umbenennen und Eingang**: Ordner und Plus-Adresse hängen am Namen (Abschnitt 2). Ohne Tabelle früherer Namen
   landen Dokumente beim Falschen.
3. **iPhone-App** leert ihre Warteschlange, wenn sich der Name beim Neukoppeln ändert. Erst Server mit `account_id`,
   dann App-Update, dann Ändern-Knopf.
4. **Sperre je Konto**: `nexkonten.authenticate` hat keine. Wer es naiv einsetzt, verliert die Sperre nach fünf
   Fehlversuchen (Test „Bestand“ fängt das).
5. **„Passwort vergessen“ per Adresse** wird enger: geteilte Adressen und Adressen vom Anbieter finden kein Konto mehr.
   Betroffene merken es nur, wenn sie die Adresse statt des Namens tippen.
6. **Zeit**: heute wird der Link im Hintergrund gemacht; `nexkonten.forgot` schreibt im Aufruf. Deshalb im Hintergrund
   aufrufen.
7. **Schema 21** hat wie jeder Schritt keinen Rückweg außer der Sicherung.
8. **Einladung nur mit Name und Passwort** (offene Browser-Tabs, Kurzbefehle) braucht den Rückfall in der Route.
9. **Französisch**: das Modul hat keine französischen Wortlaute.

## 12. Passt das Modul?

Ja, mit Reibung. Namensregeln, Einrichtungscode, Abläufe der Links und die Tabellen passen fast eins zu eins. Lücken:

1. **Ein einziges `email_confirmed`** für zwei Dinge. Das Modul setzt eine Adresse ohne Link als bestätigt
   (Einladung, Ersteinrichtung, ohne Mailserver, Bestand) und ruft für den eingelösten Link und die Sofort-Änderung
   dieselbe `Store.set_email(confirmed=True, source="")`. nexpaper braucht „zählt fürs Anmelden“ getrennt von „per Link
   bewiesen“ (Posteingang). Vorschlag fürs Modul: `set_email(…, proven: bool)` oder eine eigene Quelle `"link"`.
2. **`authenticate` ohne Sperre je Konto**: keine Stelle für Fehlversuch zählen/Sperre prüfen/bekannte Browser. nexpaper
   nimmt `resolve_login` und behält den Rest; das Modul sollte das als vorgesehenen Weg nennen oder Haken anbieten.
3. **Gesperrt nach richtigem Passwort sagt `account_blocked`**; nexpaper verrät heute nichts. Ob das überall so sein
   soll, entscheidet der Entwurf nicht.
4. **Frühere Benutzernamen** kennt das Modul nicht: `username_taken` fragt nur `find_by_username`. Apps mit Namen als
   Adresse (Eingang hier, CalDAV in nextime) brauchen „alter Name bleibt reserviert“. Geht heute nur, indem der Store
   frühere Namen in `find_by_username` mitliefert (dehnt den Vertrag).
5. **Kein Bescheid an die alte Adresse**: `confirm_email`/`change_email`/`remove_email` liefern weder die alte Adresse
   noch eine `Mail` für sie; nexpaper hat diesen Bescheid heute. Vorschlag: `MAIL_EMAIL_CHANGED` an die alte
   bestätigte Adresse.
6. **`forgot` schreibt im Aufruf** (Link anlegen, `commit`): nur im Hintergrund zeitneutral. Doku sagt es, Signatur
   zwingt es nicht.
7. **Einladungsdauer fest 7 Tage** im Entwurf; nexpaper lässt 1/7/30 wählen. Das Modul liest nur `expires_at`, die
   Entscheidung ist also nur eine des Entwurfs.
8. **Anzeigename Pflicht bei Einladung und Einrichtung**: alte Anfragen ohne ihn scheitern mit `display_name_empty`.
   Jede App braucht denselben Rückfall in der Route; besser im Modul („leer: Benutzername“) oder als ausdrücklicher
   Bestandsfall.
9. **Kein Französisch** in den Wortlauten (nexpaper liefert Französisch fest aus).
10. **`Picture` als PNG/JPEG**: nexpaper speichert WebP quadratisch; geht über die eigene Bildstrecke, nur ein
    Hinweis.

## 13. Offene Fragen

1. **Adressen der Einladung im Bestand** sind in nexpaper nicht bestätigt. Sollen sie zum Anmelden zählen (Vorschlag:
   ja, `email_counts`; so behalten diese Konten „Passwort vergessen“), oder nur per Link bestätigte?
2. **Einladungsdauer**: 1/7/30 Tage behalten oder überall 7?
3. **Gesperrtes Konto**: wie heute „falsches Passwort“ oder nach richtigem Passwort „gesperrt“ (Modul)?
4. **Benutzername ändern** erst nach Tabelle früherer Namen und iPhone-Update – einverstanden mit dieser Reihenfolge?
   Und: dürfen frühere Namen für immer reserviert bleiben?
5. **Anmelden mit Adresse ohne Mailserver**: eine selbst getippte Adresse zählt sofort. Für den Posteingang zählt sie
   nicht (Abschnitt 3). Reicht das?
