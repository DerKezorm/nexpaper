# Anbindung der gemeinsamen Konto-Module an nexpaper

Stand 25.11.2026, Zweig `konten` (auf `main` nach „Delete a shared vault from the web app“, nexpaper 1.12.0, Schema 20).
**Gebaut, Stand in Abschnitt 0.** Zielstand der Module (aus `bauplaene`, Zweig `konten`): **auf den Modulen 1.0.0**
(konten 1.0.0, ui 1.0.0, post 1.0.0, oidc 1.1.2, eingefroren; gebaut zuerst auf 0.3.9, dann über 0.3.10 nachgezogen). Maßgeblich sind der Entwurf in nexlore (`Development/nexapps/Baupläne/Entwurf Konten,
Einrichtung und Anmeldung.md`, Tabellen „Entscheidungen“, „Teil 2“, „Beim Bauen entschieden“),
`bauplaene/konten/SCHNITTSTELLE.md` und `README.md` („Was ist neu“ bis 0.3.9), `bauplaene/ui/README.md`,
`bauplaene/post/SCHNITTSTELLE.md`, im Baukasten-Plan der Abschnitt „Begleit-Apps“. Vorlage ist nexnotes
(`nexapps/nexnotes`, `main`, 1.1.0): `backend/app/services/konten_store.py`, `konten_wanderung.py`, `kontenpost.py`,
`post_store.py`, `backend/tests/nexkonten_adapter.py`, `frontend/src/pages/settings/*`, `pages/AuthPages.tsx`. Im Zweifel
die Lösung von nexnotes nehmen.

Die Fassung vom 24.11. war gegen konten 0.2.x geschrieben; was sich seitdem geändert hat, steht in Abschnitt 14. Alle
Stellen im Code sind am 25.11.2026 auf diesem Zweig nachgesehen, die iPhone-App in `nexapps/nexpaper-ios` (`d7be6bf`,
1.3.1).

**Kurz:** nexpaper ist dem Entwurf am nächsten (Einrichtungscode, beide Wege für ein vergessenes Passwort, Adresse mit
Bestätigungslink, Namensregeln wie im Modul, Teil 2 fast vollständig). Drei Dinge sind eigen: **„bestätigt“ heißt in
nexpaper „per Link bewiesen“** und entscheidet, wessen Tresor eine Mail an den Posteingang erreicht (dafür hat das Modul
seit 0.2.0 die zweite Angabe `proven`); **der Benutzername ist Eingangsordner und Plus-Adresse** (alte Namen gelten
dort weiter); und **die iPhone-App hängt am Benutzernamen** (Abschnitt 12). Umbenennen kommt gleich mit dem Umbau.

## 0. Stand (gebaut 25.11.2026, Zweig `konten`)

### Durchgang „Einstellungen“ (25./26.11.2026, Zweig `einst-desktop`)

Nach dem Bauplan in nexlore `Development/nexapps/Baupläne/Bauplan Einstellungen.md` (E1 bis E44). Module aus
`bauplaene-stand` (zuletzt a374e3c, je `tools/sync.py copy`, `check` aller sieben ok): **ui 1.1.0, konten 1.1.0, oidc
1.2.0, post 1.1.0, log 1.0.0 (neu), sicherung 1.0.1 (neu), schluessel 1.0.0 (neu)**. Keine neue Schemanummer: neue
Spalten (`users.deleted_at`, `storage_limit`, `leaving`; Outbox `headers`, `letter_key`) über `_additions_konten`,
Rückweg auf 1.12.0 bleibt. Theme ist `profile.mode` (keine eigene Spalte). E23: bisher unbestätigte Adressen bleiben
unbestätigt (`keeps_unproven_addresses`).

| Bereich | woher jetzt | was gewandert ist (alt → neu) |
|---|---|---|
| Gerüst | ui `SettingsLayout`, `SettingsNav`, `SettingsPage`, `NexuiLanguage` | eigene `SettingsNav`/`SettingsJump` weg, `/settings` auf dem Handy die Liste; Umleitungen `reminders`→`notifications`, `ai-setup`→`ai-provider`, `api`→`general`, `/konto?tab=`, `/einstellungen?tab=`, `/ueber` auf die neuen Slugs |
| Profil | konten `PAGES.profile`, `UnconfirmedEmailBox` (`/auth/me` `email_needs_proof`), `SignOutCard` | Bild in Box, Boxen statt Notice; Rückfrage beim Abmelden, solange Uploads warten; Zeile „Mailadresse bestätigt“ weg (F4) |
| Sicherheit | konten `PAGES.security`, eine Karte mit Kästen (`SecurityBoxes.tsx`) | sieben eigene Karten → Kästen; Anbieter als nexpapers Kasten |
| Darstellung | konten `AppearanceCard` (`PUT /me/theme`, einmal `POST /me/theme/adopt`), dann „Archiv“ | Hell/Dunkel am Konto statt im Browser |
| Hochladen, KI (eigene) | Bausatz | `CheckboxRow`, `Segment`, `Rows` |
| Benachrichtigungen | ui `NotifyWays` (Mail, Dieser Browser mit `POST /push/test`, Browser mit Mitteilungen mit `DELETE /push/devices/{id}`, iPhone und iPad → Verbindungen), dann Wie früh, Welche Tresore, Vorschau | Bereich „Erinnerungen“ umbenannt; „Benachrichtigungen auf deinen Geräten“ aus Verbindungen hierher (in `NotifyWays`, F1) |
| Verbindungen | Geräte (Rows, `sm` danger „Trennen“, QR im Fenster), `InstallCard` (`lib/install.ts`), „Aus anderen Apps auf dem iPhone“, „Kurzbefehl fürs iPhone“, schluessel `ApiKeysCard` | Kurzbefehl aus dem Bereich „API“; kein MCP, also keine Karte „KI-Werkzeuge“ (E27) |
| Allgemein | „Grenzen“ (`Field action`, neu „Speicher für neue Konten“, E44), „Funktionen für alle Konten“, schluessel `InterfacesCard` mit nexpapers Zeilen (OpenAPI, Koppeln, Kopfzeile), „Web Push“, „Sprachen“ (`Chip`) | Schnittstelle aus dem Bereich „API“; API-Schalter aus „Funktionen“ in „Schnittstellen“ |
| Anmeldung | konten `SignInPage` (`/api/v1/server/sign-in`, `/api/v1/server/readiness` mit nexpapers Punkten `secrets`, `backups`, `upload_requests`) + oidc `SignInProviders` | `ReadinessCards.tsx`, `SignInCards.tsx` weg; alter `/api/v1/settings/readiness` bleibt |
| Mail | post `MailCard` unter `/api/v1/server/mail` | `services/mailer.py` weg, jede Mail über die Outbox von post (Fristen und Woche als `app_letters` mit `key`); alte Wege `/api/v1/settings` (smtp_*), `/settings/mail-test` bleiben mit alten Kennungen |
| Speicher und Sicherung | sicherung `StorageArea` unter `/api/v1/server/storage`, Haken `services/backup_hooks.py`, dann „So liegen die Dateien auf der Platte“, „Dateien prüfen“ | Format unverändert; neu Uhrzeit (`backup_time`, 03:00) und „Jeden Monat“; alte Wege `/api/v1/backups` (`x-nexpaper-password`) in alter Form, `/api/v1/storage` bleibt |
| Texterkennung, KI-Anbieter, Ablage, Eingänge, Import | Bausatz | Sprachen als `Segment multiple`; „KI“ unter Server heißt „KI-Anbieter“ (`ai-provider`) |
| Konten | konten Kontenliste (`capsOf`), Offene Einladungen, `WhatYouSeeCard`, schluessel `AllKeysCard` | mehrere Betreiber; Löschen mit 30 Tagen Zurückholen (`POST /accounts/{id}/restore`, Übergabe-Dialog bleibt, Dokumente gehen beim endgültigen Löschen weiter, B2.2); Speichergrenze je Konto (`PUT /accounts/{id}/storage-limit`, zählt die Dokumente, Upload 507 `storage_limit_reached`); „KI erlaubt“ über `manage.set_right`; Schlüssel ruhen, solange ein Konto draußen ist (E41) |
| Log | log `LogCard`, `services/logs.py` als Hülle um `nexlog` | Weg `/api/v1/logs` und Schlüssel unverändert; „Ältere laden“ über `offset` |
| Über | ui `AboutPage` | Logo als Bild, Was ist neu aus `i18n/whatsnew` |
| API-Schlüssel | schluessel `services/schluessel_store.py` über `api_keys` (`npk_`, read/upload, Schalter `api_keys_allowed`) | Karten-Wege `/api/v1/connections`; alte `/api/v1/api-keys`, `/admin/api-keys` in alter Form über `keys.*` (neu `…/unblock`); jeder alte Schlüssel gilt weiter |

Weitere Punkte: kein Push an gesperrte oder gelöschte Konten, Ordner-Eingang wartet für sie (E38); gelöschte Konten
unsichtbar in Mitgliederlisten, nicht wählbar, Mitgliedschaften fallen erst beim endgültigen Löschen weg (E33);
Verweise auf alte Orte in Texten, Mails, Mitteilungen und Doku auf die neuen umgestellt (E39), festgehalten in
`frontend/src/i18n/places.test.ts` und `backend/tests/test_places.py`. Fenster, die auch außerhalb der Einstellungen
aufgehen, bleiben vorerst (F10).

Umwege: keine offen (`TODO sicherung 1.0.1` und der tsconfig-Ausschluss der Modultests sind wieder heraus).
Offene Fragen: `nexapps/einst-fragen/nexpaper.md` (B1.1 bis G6).

Läufe (26.11.2026 früh, `reihe.sh nexpaper ende`, Stand `8f5db31`): ruff sauber; pytest 3800 grün, 5 übersprungen
(zwei Einladungen mit festem Benutzernamen, Schlüssel nach Bereichen, eigener Scanner, ein OCR-Fall), 0 rot (Ausgangsstand:
11 rot, OCR-Zeitgrenzen); `npm run lint` sauber; vitest 1191 grün in 107 Dateien (vorher 1053 in 96); `npm run build`
grün; Playwright `npm run e2e` 2 von 2 grün, darunter `nexoidc.spec.ts` Test 34, vorher rot (Überschrift „Sign-in“
doppelt; jetzt prüft er Pfad, h1 und h2 je einmal und die Knopfnamen). `sync.py check` aller sieben Module ok.

**Gemeinsame Runde (26.11.2026 früh, E45 bis E49).** Module aus `bauplaene-stand` 86a0cce (`322b739`).
- E45: neue Konten (Einrichtung, Einladung, Anbieter, `accounts.create_with_password`) mit `profile.mode = "system"`;
  Konten von vorher übernehmen einmal den Rohwert von `nexpaper.theme`, sonst die Vorgabe (`system`, kein
  `theme_default_before`); die Seite schickt nie `prefers-color-scheme` (`state/auth.tsx`).
- E46/E49: Orte überall „Gruppe › Bereich“ (Texte, Mails, Fehler, Kommentare, README, `docs/`), Karten als letzter
  Teil statt „, Karte …“; in „Was ist neu“ nur die Wegweiser (`where`) auf heute, die alten Texte wie erschienen.
  Wächter: `places.test.ts` (auch die Wegweiser), `test_places.py` (README, `docs/`, jede Zeichenkette des Servers).
- E48: Karte `web-push` (Reihenfolge Grenzen, Funktionen, Schnittstellen, Web Push, Sprachen), Satz unter Grenzen
  „Was nexpaper annimmt … Die Grenze eines Kontos setzt du unter Server › Konten › Verwalten.“, Satz unter Funktionen,
  „Schriften im Abbild“; „Verwalten“ bleibt `sm` wie aus konten.
- E47/E51: `tests/test_bestand.py` wie auf `konten`, nur die Anbindung an die Post wandert in den Block
  `AFTER_THE_CHANGE` (`from app.services import kontenpost as mailer`; eine Zeile Import davor ohne `mailer`), die
  Hülle `services/mailer.py` ist weg, `routers/resets.py` ruft `kontenpost.send_reset`; der Fänger
  `bestand_mail_caught` bleibt (ohne ihn sechs Versuche an mail.example.com:587).
  Speichergrenze an jedem Eingang (`services/quota.py`): Ordner (Datei bleibt liegen), Postfach (Mail bleibt
  ungelesen, `mail_state.full` mit Person, Zahl, Bytes, wird mit Platz geholt), Paperless (`storage_full`, ein späterer
  Lauf holt nach), Upload-Bitten (507 `request_no_room`); Mitteilung „Speicher voll, x Dokumente warten“ über `tell`
  (Push und Mail, DE/EN/FR, höchstens stündlich neu), Logzeile `Storage full: documents wait`.
- Läufe (26.11.2026 früh, Stand `35f8e41`): ruff sauber; pytest gezielt 1048 grün, 2 übersprungen (nexkonten, nexoidc,
  nexpost, Bestand, Orte, Eingänge, Paperless, Upload-Bitten, Mail, Push, Einstellungen); vitest 1199 grün in 107
  Dateien; `npm run lint` sauber; `npm run build` grün; Playwright `npm run e2e` 2 von 2 grün. Volle Backend-Reihe
  macht die Bau-Leitung.

**Modul sprachen 1.0.0 (26.11.2026, E51; `bauplaene-stand` 4f3e75e).** Die eigenen Sprachen kommen aus dem Modul
(`app/vendor/nexsprachen`, `src/vendor/nexsprachen`). `services/locales.py` ist das Modul (`configure` mit
`NEXPAPER_LOCALES_DIR`, also dem Ordner von vorher: vorhandene Dateien gelten weiter; eingebaut `de`, `en`, `fr`; die
Vorlage macht die Seite aus den englischen Texten); dort bleibt nexpapers Lesen von `Accept-Language` (`best_match`,
jetzt über `codes()`). `routers/locales.py` hängt die Wege des Moduls unter `/api/v1/locales` ein, an derselben Stelle
wie bisher. Profilsprache und Sprache der Seite prüft `nexsprachen.known`. Karte „Sprachen“ ist `LanguagesCard` des
Moduls (fünfte Karte unter Allgemein, Satz „Deutsch, Englisch und Französisch sind eingebaut.“, Änderungen mit
`X-Nexpaper-Client` über `tabFetch`), alte Karte und ihre Wörter sind weg; der i18n-Lader nimmt `ownLanguages`, das
Profil `useLanguageOptions`. Die Anmeldeseite hat keine Sprachwahl (Frage S3).
- Alte Wege: dieselben Pfade, Methoden und Felder (`code`, `name`, `keys`; Fehler `{"detail": {"code", "message", …}}`
  mit `not_found`, `locale_unusable`, `too_large`). Anders: die Liste nennt vorne die eingebauten Sprachen
  (`built_in`, `own`; die alte Seite übersprang eingebaute Codes), neu `GET /api/v1/locales/template` (404), der Grund
  einer Ablehnung ist eine feste Kennung statt des Parsersatzes. `test_locales.py::test_old_callers_get_the_same_answers`
  und `order.test.ts` (Liste in der Form von vorher) zeigen es.
- Anders als vorher: Entfernen fragt nicht mehr (Modul wie nexnotes, Frage S2); der OpenAPI-Schnappschuss ist nicht
  erneuert, weil sich neben Zusätzen `operationId`s und eine Zusammenfassung ändern (Frage S1, Test rot). Vorlage
  `nexsprachen.test.tsx`: der englische Satz mit Französisch von Hand (Modulfehler S4).
- schluessel aus 4f3e75e: „Neuer MCP-Schlüssel“ md secondary Plus; Vorlage `nexschluessel.test.tsx` von Hand
  nachgezogen, Werte der App bleiben.
- Läufe (Stand `a279855`): ruff sauber; pytest gezielt 437 grün, 1 übersprungen (nexschluessel ohne Bereiche), 1 rot
  (Schnappschuss, S1) in nexsprachen, nexschluessel, Sprachen, PWA, Wege, Orte, Bestand, Konten, Einladungen, Push,
  Mail; `tests/nexsprachen` 63 grün; vitest 1222 grün in 109 Dateien; `npm run lint` sauber; `npm run build` grün;
  Playwright `npm run e2e` 2 von 2 grün. Neue Tests je gegen eine Mutation rot (Rückgabecode 1).

**sprachen Schritte 9 bis 11 und E52 (26.11.2026, `bauplaene-stand` 68fd070):** Die Wege `/api/v1/locales…` behalten in
`/api/v1/openapi.json` ihre operationIds, Zusammenfassungen und das Schema `LocaleEntry` (`routers/locales.py`
`OPERATION_IDS`, `SUMMARIES`, `SCHEMA_NAMES`, dasselbe im Adapter); der Schnappschuss gewinnt gegen `konten` nur
`built_in`, `own` und `GET /template`. Beim Start direkt nach `configure` `tidy_at_start` (`locales.start`), Adapter
`restart`. Profilsprache (E52): nimmt genau, was 1.12.0 nahm (eingebaut oder hinzugefügte Datei, leer), `known` füllt
nur die Menüs. Endlauf `reihe.sh nexpaper ende5` (Stand `65946b0`): ruff sauber; pytest 3886 grün, 5 übersprungen, 0 rot;
`npm run lint` sauber; vitest 1222 grün in 109 Dateien; `npm run build` grün; danach Modul 68fd070 (nur Vertragstests,
`tests/nexsprachen` und `test_routes.py` 82 grün); Playwright `npm run e2e` 2 von 2 grün.

**E53, alte Namen der API-Beschreibung (26.11.2026, `bauplaene-stand` 130e4e9):** `routers/backups.py` gibt
`routes.router(..., schema_names=routes.FORMER_SCHEMAS)` und `routes.legacy_router(..., **routes.former_names("/api/v1/backups"))`;
die alten Sicherungswege tragen wieder ihre operationIds, Zusammenfassungen und Eingaben (`CreateIn`,
`app__routers__backups__PasswordIn`), `NoteIn` und `RestoreIn` der App heißen wieder so. Neuer Test
`tests/test_openapi_names.py` gegen `tests/schema/names-before-settings.json` (alle 326 Wege und 265 Schemas von
`konten`). Gegen `konten` bleiben nur zwei Zusammenfassungen, die sich mit dem Verhalten geändert haben (Fragen E2, E3).
Endlauf `reihe.sh nexpaper ende6` (Stand `b61acc3`): ruff sauber; pytest 3892 grün, 5 übersprungen, 0 rot; lint sauber;
vitest 1222 grün in 109 Dateien; build grün; Playwright 2 von 2 grün.

**E53 Schritte 9 und 10 (26.11.2026, `bauplaene-stand` 6edff85):** Die alten Sicherungswege prüfen `{name}` wieder mit
Muster und Länge 64 wie auf `konten` (über `former_names`, Adapter `name_pattern`), falsche Namen 404/422 vor der
Passwortfrage; der Schnappschuss hat das Muster wieder, die Wege `/api/v1/backups…` sind in Parametern gleich wie auf
`konten`. Neuer Vertragstest fürs Anlegen grün. Endlauf `reihe.sh nexpaper ende7` (Stand `192f627`): ruff sauber; pytest
3899 grün, 5 übersprungen, 0 rot; lint sauber; vitest 1222 grün in 109 Dateien; build grün; Playwright 2 von 2 grün.

**ui f4ab8ba (E56, `Table` `rowProps` nur `data-…`):** nur kopiert, nexpaper übergibt dort nichts anderes. Endlauf
`reihe.sh nexpaper ende8` (Stand `549b40d`): ruff sauber; pytest 3899 grün, 5 übersprungen, 0 rot; lint sauber; vitest 1223
grün in 109 Dateien; build grün; Playwright 2 von 2 grün.

**Letzte Runde (E57, 26.11.2026, P1 bis P3).**
- P1 (B1.3, `6951456`): eine gescheiterte **geplante** Sicherung meldet sich bei allen Betreibern über den Haken
  `tell("backup_failed")` (`backup_hooks.backup_failed_notice`, Push und Mail, Link `/settings/storage`, Tag
  `backup-failed`), DE/EN/FR; das Modul meldet einmal, bis wieder eine gelingt.
- P2 (B1.5, E26, `76f0cc5`): nexpapers eigene Briefe in der Sprache des Empfängers (`kontenpost.language_for` wie
  `Store.recipient`: Konto, sonst erster Betreiber, sonst Englisch), DE/EN/FR: `tell.Notice.mails` (de/fr neben dem
  englischen `mail_subject`/`mail_body`, `tell.mail_words`) für Sicherung/Wiederherstellen gescheitert, Dateien prüfen,
  Anmeldeweg gelöst, Speicher voll, Upload-Bitte (`upload_requests.request_notice`), Paperless-Import
  (`paperless.import_notice`); Export fertig/gescheitert (`exports.MAILS`); „Absender bestätigen“
  (`mail_senders.confirm_letter(language=…)`, Namen in einem Durchgang eingesetzt). Push dieser Hinweise jetzt auch FR.
  Die Fristen-Briefe bleiben DE/EN (Frage Q1).
- P3 (B3.1, E38, `ac6ee58`): Mail an `paper+<konto>@` eines gesperrten oder gelöschten Kontos, oder nur von dessen
  bestätigter Adresse, geht nie an den Betreiber (`intake_mail.held_for`, `mail_senders.owners(shut_out=True)`): sie
  bleibt ungelesen liegen (`mail_state.held`), kommt nach Entsperren/Zurückholen wie jede andere herein und wird nach
  dem endgültigen Löschen übergangen (`dropped`, nie wieder geholt, niemand bekommt sie). `test_mail_text.py::
  test_a_blocked_account_gets_nothing` prüft jetzt das neue Verhalten (vorher: an den Betreiber, unbekannt). Mail
  danach an den reservierten Namen: Frage Q2.
- Läufe: gezielt 813 grün (berührte Dateien, `tests/nexsicherung`, `tests/nexpost`, `test_bestand.py`,
  `test_places.py`, `test_openapi_names.py`, `test_routes.py`; Schnappschuss unverändert), ruff sauber; neue Tests je
  einmal gegen Mutationen rot (Rückgabecode 1). Oberfläche nicht berührt.

**E57 Nachzug der Module (26.11.2026, `bauplaene-stand` dcbd5d1: sprachen 1.0.1, konten 1.1.1, schluessel 1.0.1):**
Entfernen einer eigenen Sprache fragt wieder (Tests `languagesCard.test.tsx`, `Confirmations.test.tsx` mit `asksFirst`,
TODO weg). P4: unter „Mail bei neuer Anmeldung“ nexpapers Satz „Auch als Mitteilung auf deinen Geräten.“
(`newSignInMailHint`, DE/EN/FR). P5: in `ApiKeysCard` „Jetzt freigeben“ des Betreibers (`offAction`, Rückfrage, schaltet
`api` unter `/api/v1/connections/interfaces`), „Zum Ausprobieren“ mit dem curl-Befehl je Recht (`made`), Ablauf-Hinweise
am Ende (`children`). E58: der Link „Eigene API-Schlüssel anlegen“ (Ziel Mein Konto › Verbindungen) steht am Ende von
„API-Schlüssel aller Konten“ (`AllKeysCard` `children`, schluessel 1.0.2); Fristen-Briefe, Wochenübersicht und ihre
Push-Meldungen auch auf Französisch.
Endlauf `reihe.sh nexpaper ende10` (Stand `3b07018`): ruff sauber; pytest 3927 grün, 5 übersprungen, 0 rot; lint sauber;
vitest 1233 grün in 109 Dateien; build grün; Playwright 2 von 2 grün.
Endlauf `reihe.sh nexpaper ende9` (Stand `f289749`, mit P1 bis P5): ruff sauber; pytest 3925 grün, 5 übersprungen, 0 rot;
lint sauber; vitest 1231 grün in 109 Dateien; build grün; Playwright 2 von 2 grün.

**Fund der Galerie (Vorlage der Sprachen):** Die heruntergeladene Vorlage wurde beim Hochladen mit 422 `not_text`
abgelehnt, weil nexpapers Englisch vier Listen hat (Wochentage, Monate, Suchhilfe des Archivs). `TEMPLATE` ist jetzt
`textsOnly(en)` (`frontend/src/i18n/index.ts`); Tests in `languagesCard.test.tsx` und `test_locales.py`. Endlauf
`reihe.sh nexpaper ende11` (Stand `579cbe9`): ruff sauber; pytest 3928 grün, 5 übersprungen, 0 rot; lint sauber; vitest 1234
grün in 109 Dateien; build grün; Playwright 2 von 2 grün.

**Endlauf (26.11.2026, `reihe.sh nexpaper ende4`, Stand `29ba6c2`, nach Passkeys E49, Grenzen-Satz E46, Bestand E51,
sprachen):** ruff sauber; pytest 3879 grün, 5 übersprungen, 1 rot: `test_routes.py::test_the_description_of_the_interface_is_the_snapshot`
(OpenAPI-Schnappschuss, die alten Wege `/api/v1/locales…` tragen über das Modul andere `operationId` und den Schemanamen
`LanguageEntry`; Frage S1, absichtlich nicht erneuert); `npm run lint` sauber; vitest 1222 grün in 109 Dateien;
`npm run build` grün; Playwright `npm run e2e` 2 von 2 grün. Zuvor eine zufällige Ziffernfolge in einer MIME-Grenze
(`test_reminders.py`, „9876“) gefunden: der Test liest jetzt den entschlüsselten Inhalt statt der rohen Mail (`6d1d708`).


**Gebaut** auf konten 0.3.9, oidc 1.1.0, post 0.1.1, ui 0.1.1, am selben Tag nachgezogen über 0.3.10 **auf den Modulen
1.0.0** (konten 1.0.0, ui 1.0.0, post 1.0.0, oidc 1.1.2; Kopien aus `bauplaene`, Zweig `konten` `3c55402`, `sync.py check`
grün).
Die Abschnitte ab 1 sind die Bestandsaufnahme und der Plan von vorher; was davon abweicht, steht hier.

**Backend**

- Daten: neue Spalten am Ende von `users` (`email_counts`, `avatar_source`, `offered_email`, `offered_email_provider`,
  `declined_email`, `device_key`, `totp_pending`, `totp_pending_until`, `new_password_origin`, `password_changed_at`),
  `invites` (`display_name`, `mailed`), `password_resets` (`origin`); Tabellen `former_names`, `setup_claims`,
  `failed_unknown`, `mail_outbox` (`models_accounts.py`). Alles als `db._additions_konten`, **ohne neue Schemanummer**
  (Rückweg auf 1.12.0 bleibt), Sicherung davor beim ersten Start, Indizes `lower(name)` (eindeutig nach Zählen) und
  `lower(email)` (nicht eindeutig). `two_factor_required` ab Werk aus; eine Datenbank von 1.12.0 mit Konten und ohne
  Zeile bekommt die Zeile `true`. Schema `v20.sql` neu aufgezeichnet, `released/1.12.0.sql` hält den Stand davor.
- Store `services/konten_store.py` (alle Stores von Teil 1 und 2): `email_counts` = zählt, `email_confirmed_at` =
  bewiesen; wartende Adresse in `email_confirmations`; Sitzungen in `auth_sessions` (wartende Anmeldung des Moduls als
  Stufe `waiting`), gekoppelte Geräte in `devices` (Abmelden widerruft); Wiederherstellungscodes mit dem Schlüssel von
  1.12.0 (`h1:` gilt weiter); `user_handle` = Bytes des Hex-Handles von 1.12.0. Sperre **nach 10** (`MAX_FAILURES`).
  `password_changed_at` in `get_account` (Bestand leer: „unbekannt“). Haken `provider_checks_factor`: ein Konto nur
  über Anbieter bekommt bei „Zweiter Faktor für alle“ keinen eigenen (wie 1.12.0); eine Sitzung über einen Anbieter,
  der den Faktor prüft, bleibt Sache der Anmeldung (`second_factor_by_provider`).
- Anmelden über `login.sign_in` (0.3.10): Bremse des Moduls, fünf frei heißt genau fünf; wartet nur der Topf des
  Kontos, antwortet die Anmeldung 401 `wrong_credentials`, 429 nur bei vollem Absendertopf. Antworten mit alter
  Kennung tragen `account_code` (die des Moduls) mit.
- Routen: Anmelden, Einrichtung, Einladung, Passwort vergessen (1 Stunde, über `mailer.send_reset`), Links,
  Profil (`PUT /me/profile` mit `name`, `email`, `password`), Adresse (`PUT /me/email`, `POST /me/email/resend`,
  `POST /me/email/prove` = „Per Link bestätigen“ über `profiles.prove_email`; dieselbe Adresse noch einmal per
  `PUT /me/email` mit Passwort tut dasselbe wie in 1.12.0),
  Faktor (`factor` des Moduls, Seed wartet versiegelt), Sitzungsliste des Moduls, `GET/POST /auth/access…`, Betreiber
  (`PUT /accounts/{id}/name`, `/display-name`, `DELETE /accounts/{id}/email`, Link 1/7/30 Tage, Faktor-Übersicht).
  Passkeys bleiben nexpapers Routen und Dienst (gleiche Tabelle), neu mit Schalter „Passkeys erlaubt“.
- `account_id` (JSON-Zahl) und `account` = **ältester** Benutzername in `/devices/pair`, `/devices`,
  `/devices/sibling`, `/oauth/token`; `GET /api/v1/me` hat `id`. Je Route ein Test (`tests/test_konten.py`).
- Posteingang: Plus-Adresse und Eingangsordner früherer Namen gehen ans Konto (`konten_store.by_any_name`,
  `names_by_account`), gelöschte Namen an niemanden; `GET /me/intake` hat `former`. Nur bewiesene Adressen ziehen Post.
- Mail: Systemmails über `post` (Logo `app/assets/mail-logo.png`, DE/EN/FR); Bescheide über die Outbox (Minutenrunde),
  „Neue Anmeldung“ sofort (wie 1.12.0, mit Link auf Sicherheit nur unter der öffentlichen Adresse).
- Mail „Neue Anmeldung“ (1.0.0): `notices.sign_in_letter` mit Browser auf System, Uhrzeit in der Zeitzone des
  Kontos (`timezones.zone_of`), Knopf zur Seite Sicherheit unter der öffentlichen Adresse, nie eine Netzadresse. Die
  Push-Mitteilung an die eigenen Geräte ebenso nur Browser auf System und Uhrzeit, kein Netz mehr (Entscheidung
  25.11.2026).
- Vertrags-Adapter: `sign_in_from`, `listed_invites`, `forgot_through_route`, `picture_status` (nexkonten),
  `new_sign_in_letter` (nexpost), alle über die echten Routen.
- Notfallbefehl `python -m app.reset_link <name oder adresse> [--days]` über `server_reset_link`.

**Frontend**: `--nexui-*` in Kraftpapier hell/dunkel, Wortlaute `account`/`mail` DE/EN/FR (nexpapers eigene alte
Schlüssel `account` und `mail` umbenannt: `mailAddress`), Anmeldeseiten mit den Feldern von `SCREENS`, Profil nach
`PAGES.profile` (ein Speichern, Passwort-Rückfrage, Knopf `account.emailProve`), Sicherheit ganz aus `PAGES.security`
(je Teil eine Karte mit Titel, Hinweis und Knöpfen des Moduls in seiner Reihenfolge: Passwort mit `passwordChanged`,
zweiter Faktor, Wiederherstellungscodes, Passkeys, angemeldete Geräte mit „Überall sonst abmelden“, Mail bei neuer
Anmeldung; danach nexpapers eigene Anbieter) und „Diese Geräte haben noch Zugriff“; Fehlertexte über
`accountErrorKeyOf`; unter `account.*` keine eigenen Schlüssel. Kontenliste `pages/settings/AccountsTab.tsx` (Haken „KI erlaubt“, Angabe „Dokumente“, eigener Lösch-Dialog,
Karte „Schlüssel aller Konten“ darunter), Schalter „Passkeys erlaubt“, Absendername.

**Bewusst anders als der Plan oben**

- Sperre nach **10** (Entscheidung 25.11.2026); Hinweis an jede alte Adresse, die zählte (Entscheidung 25.11.2026).
- Ein Passkey ohne Authenticator ist nur bei „Zweiter Faktor für alle“ ein zweiter Schritt (Modul); 1.12.0 fragte ihn
  immer nach dem Passwort.
- Seit 0.3.10 lässt die Bremse je Topf genau fünf durch (0.3.9: sechs).
- „Passwort vergessen“ geht sofort über `mailer.send_reset` (`nexpost.send.deliver`), nie über die Outbox.
- `avatar_too_large`: seit 1.0.0 der Satz des Moduls mit `{{mb}}` (nexpapers eigener Satz ist weg).
- Die Mail „Neue Anmeldung“ nennt nur Browser und System (Modul), nicht mehr Netz und Uhrzeit.

## 1. Bestand heute (1.12.0, Schema 20)

### Datenmodell (`backend/app/models.py`)

| Tabelle | Was zum Konto gehört |
|---|---|
| `users` | `id`; `name` (64, `unique`, immer klein, `^[a-z0-9][a-z0-9._-]{1,63}$`); `display_name` (80); `whats_new_seen`; `role` (`operator`/`member`, mehrere Betreiber); `sign_in`; `password_hash` (Argon2id, leer: nur Anbieter); `email` (255, nicht eindeutig); **`email_confirmed_at`** (gesetzt nur durch einen eingelösten Bestätigungslink); `email_from_provider`; `oidc_subject` (Rückweg auf 1.0.1); `language`; `profile` (JSON, darin `notify_login`); `created_at`, `last_seen_at`; `failed_logins`, `locked_until` (5 Fehlversuche, 15 Minuten); `blocked_at`; `totp_secret_enc`, `totp_recovery` (`h1:` + HMAC), `totp_last_step`; `avatar` (WebP), `avatar_at`; `signed_in_before`; `passkey_handle`; `ai_allowed` |
| `auth_sessions` | `token_hash`, `account_id`, `created_at`, `expires_at`, `last_seen_at`, `ip`, `user_agent`, `uid`, `remember`, `stage` (`full`/`setup`/`codes`), `second_factor_by_provider` |
| `invites` | `token_hash`, `email`, `created_by`, `created_at`, `expires_at` (1, 7, 30 Tage) |
| `password_resets` | `account_id`, `token_hash`, `created_by` (NULL: selbst angefordert oder Befehl auf dem Server), `expires_at` (24 Stunden, beide Wege) |
| `email_confirmations` | wartende Adresse: `account_id` (eindeutig), `address`, `token_hash`, `expires_at` (24 Stunden) |
| `mail_senders` | weitere bestätigte Absenderadressen je Person (nur Posteingang, eigener Link), nicht Teil des Kontos |
| `devices` (`npd_…`), `pairings`, `api_keys` (`npk_…`), `passkeys`, `push_devices`, `oidc_links` | an der Konto-ID |
| `vaults`, `vault_members` | je Konto ein persönlicher Tresor (`personal_of`, angelegt in `models._make_personal_vault` im selben Schreibvorgang), `folder` einmal vergeben, nie umbenannt; gemeinsame Tresore mit Verwaltern |
| `settings` | `two_factor_required` (Vorgabe `True`), `password_login`, `public_url`, `smtp_*`, `api_keys_allowed` …; ohne Zeile gilt `DEFAULTS` |

Kein Zustand „gelöscht“: Löschen entfernt die Zeile (Dokumente gehen nach Wahl an andere), der Name wird heute frei.

**Wanderung:** nummerierte Schritte (`db.py`, `SCHEMA_VERSION = 20`, Sicherung vor dem ersten Schritt) **und
`ADDITIONS`**: neue Tabellen und Spalten mit Vorgabe, die bei jedem Start ergänzt werden, ohne die Nummer zu heben; so
startet die Vorfassung weiter auf der Datenbank (Rückweg eine Fassung lang, so gebaut für die Anbieterliste in 1.1.0).

### Dienste und Router (Präfix `/api/v1`)

| Ort | Was |
|---|---|
| `routers/auth.py` | `GET/POST /setup` (`name`, `password`, `language`, `code`), `POST /auth/login` (`name` ≤ 64, `password`, `remember`), `/auth/setup/done`, `/auth/setup/codes`, `/auth/logout(-all)`, `/auth/me`, `/auth/sessions`, `PUT /auth/password`, `PUT /me/profile` (`display_name`), `/me/language`, `/me/preferences`; Betreiber: `GET /accounts`, `GET /accounts/{id}/leaving`, `DELETE /accounts/{id}` (`current_password`, `confirm_name`, `documents`, `target_user_id`, `target_vault_id`), `sign-out`, `block`, `unblock`, `permissions` (`ai_allowed`), `role` |
| `services/accounts.py` | `by_name`, `check_name`, `authenticate` (Blindhash, Sperre am Konto, bekannter Browser ausgenommen, eine Prüfung je Konto), Einrichtungscode, Einladungen |
| `routers/invites.py` | `GET/POST /invites` (`days`, `email`, `send`), `DELETE /invites/{id}`, `GET/POST /invite/{token}` (`name`, `password`) |
| `routers/resets.py`, `services/resets.py` | `POST /auth/forgot` (`name`: Name oder Adresse, jede Adresse auf dem Konto, bis 5 Konten, 24 h, im Hintergrund über `notices.later`), `GET/POST /reset/{token}`, `POST /accounts/{id}/reset-link` (eigenes Passwort; Mail an die Adresse, sonst einmal gezeigt; nicht für gesperrte) |
| `routers/emails.py`, `services/emails.py` | `PUT /me/email` (`email`, `password`; **ohne Mailserver 409 `mail_off`**; dieselbe noch nicht bewiesene Adresse noch einmal: neuer Link), `DELETE /me/email/pending`, `GET/POST /email/confirm/{token}`; **Bescheid an die alte Adresse**, wenn sie bewiesen war (Ändern per Link, Entfernen) |
| `routers/oidc.py`, `services/oidc_store.py`, `vendor/nexoidc` 1.0.14 | Anbieter; Adresse vom Anbieter unbewiesen, folgt dem Anbieter, bis die Person eine eigene setzt |
| `routers/intake.py`, `services/intake.py`, `intake_folder.py`, `intake_mail.py`, `mail_senders.py` | Posteingang: Unterordner `<eingang>/<name>/`, Plus-Adresse `<postfach>+<name>@…`, sonst eine **bewiesene** Absenderadresse genau einer Person, sonst Betreiber als „unbekannt“ |
| `routers/pairing.py`, `routers/devices.py` | Koppeln per QR-Code und OAuth 2 mit PKCE; Antworten mit `account` = Benutzername; `POST /devices/sibling` für das iPad |
| `security.py` | Sitzung (Cookie `nexpaper_session` + Suffix), `end_all_sessions` (Browser **und gekoppelte Geräte**), Gerätecookie mit Konto-ID, Bremse je Absender, `MAX_FAILURES = 5`, `LOCK_MINUTES = 15` |
| `services/notices.py`, `mailer.py` | Mail und Web Push bei neuer Anmeldung (`profile.notify_login`); Mails **nur englisch** |
| `app/reset_link.py` | `python -m app.reset_link <account>` |

### Frontend

Seit 1.11.0 Einstellungen wie nexnotes (`pages/settings/areas.ts`: Mein Konto mit Profil, Sicherheit, …; Server mit
Allgemein, Anmeldung, Mail, …, Konten, Log). `pages/AuthPages.tsx` (Einrichtung, Anmelden, Code, Einladung, Passwort
vergessen, neues Passwort, Adresse bestätigen), `pages/settings/AccountArea.tsx` (`ProfileCard`: Bild, „Name“ =
Anzeigename, E-Mail mit Bestätigungszeile und „Link schicken“, Zeile „Rolle · Anmeldename“, Sprache; `Security`),
`pages/settings/ServerCards.tsx` (`AccountsCard` als Tabelle mit Drei-Punkte-Menü, `DeleteAccount`, `InviteDialog`,
`AllApiKeysCard`), `SignInCards.tsx`. Eigene Bausteine nach nexnotes (`AuthFrame`, `Input`, `Primary`, `Card`,
`Dialog`, `useConfirm`, `CopyLink`). Wortlaute DE/EN/**FR**. Akzent Kraftpapier `#9a6a3a`, hell und dunkel.

## 2. Wo der Benutzername mehr ist als Anzeige (im Code geprüft)

**bricht** = ein Umbenennen machte etwas kaputt; **lösen** = mit dem Umbau anfassen; **harmlos** = Anzeige, Protokoll,
Momentaufnahme.

| Stelle | Rolle des Namens | Bewertung und Lösung |
|---|---|---|
| `services/intake_folder.py` `scan` (`people`, `blocked` aus `Account.name`), `prepare`, `folder_name`; `routers/intake.py` `my_intake`, Betreiberliste `FolderPerson`, `put_intake` | **Eingangsordner** `<eingang>/<name>/` gehört dem Konto mit diesem Namen | **bricht** ohne Lösung (Dokumente landeten als „unbekannt“ beim Betreiber). **Lösung:** `people` und `blocked` nehmen auch die früheren Namen des Kontos (`former_names` mit `account_id`); `prepare` legt nur den Ordner des aktuellen Namens an, ein alter Ordner wird weiter gelesen; der Ordner eines gelöschten Kontos bleibt „unbekannt“ wie heute. Nach dem Umbenennen (`notify(renamed)`) legt die App den neuen Ordner sofort an |
| `services/intake.py` `account_named`, `services/intake_mail.py` `assign` | **Plus-Adresse** `<postfach>+<name>@…` | **bricht** ohne Lösung. **Lösung:** `account_named` sucht aktuellen Namen, dann `find_by_former_name` (nur Konten, nicht gesperrt); ein früherer Name eines gelöschten Kontos findet niemanden. Frühere Namen sind für immer reserviert (Entwurf), also landet nie fremde Post beim Falschen |
| `routers/intake.py` `MyIntakeOut` (`plus_address`, `folder`) | Anzeige in „Mein Posteingang“ | zeigt den aktuellen Namen; neu `former` (Liste der früheren Ordner und Plus-Adressen, die weiter gelten), Hinweis darunter |
| `routers/pairing.py` `pair`, `token`; `routers/devices.py` `bring_in` → **nexpaper-ios** `Connection.account` | Schlüssel in der App | **bricht (mittel)**: Abschnitt 12 |
| `services/accounts.py` `by_name`, `authenticate`; `LoginIn.name` `max_length=64` | Anmelden | ersetzen durch `login.authenticate` (Feld bis 254) |
| `services/resets.py` `accounts_for` | Name oder Adresse, bis 5 Konten | ersetzen durch `forgot_in_background` (Regel 3) |
| `app/reset_link.py` | Kommandozeile nach Name | über `server_reset_link` (aktueller Name oder Adresse, die zählt) |
| `routers/auth.py` `delete_account` (`confirm_name` gegen `row.name`) | Abtippen zur Sicherheit | harmlos: verglichen wird mit dem aktuellen Benutzernamen; beim Löschen kommt der Name als früherer Name ohne Konto in `former_names` (für immer reserviert) |
| `models._make_personal_vault` (`name = display_name or name`, `folder`) | Kopie beim Anlegen | harmlos: Tresor und Ordner bleiben, wie sie sind |
| `routers/v1.py` `/api/v1/me` (`name`) → nextime (Beschriftung beim Verbinden), nexdeck (Verbindungstest) | Antwortfeld | harmlos: Momentaufnahme; bekommt zusätzlich `id` |
| `routers/schemas.py` `PersonRef(name, display_name)`, `routers/apikeys.py` (`account`), `services/paperless.py` (Import: Besitzer nach Name vorschlagen) | Anzeige, einmaliger Vorschlag | harmlos |
| `services/passkeys.py` `user_name`, `routers/totp.py` `provisioning_uri` | Beschriftung im Passwortmanager bzw. Authenticator | harmlos (`passkey_handle` zufällig) |
| `deps.py`, `logs.set_actor`, alle `name=%s`, `notices.py`, `mailer.py` | Protokoll, Text | harmlos; die neue Logzeile „Username changed“ nennt beide |
| Sitzungen, Geräte, API-Schlüssel, Passkeys, Push, OIDC, Links, Sicherungen, Verlauf (`events.user_id`), Freigaben | an der ID | harmlos |

## 3. Store-Adapter: was er abbildet

Neue Datei `services/konten_store.py` (Vorlage nexnotes), eine Instanz je Anfrage.
`nexkonten.configure(AppConfig(app_name="nexpaper", setup_token=lambda: get_settings().setup_token,
logger_name="nexpaper.auth", error_codes=OLD_CODES, second_factor_off=…))`, `nexpost.configure(AppConfig(app_name=
"nexpaper", logo=<PNG>))`.

### `Store`

| Modul | nexpaper |
|---|---|
| `Account.id`, `username`, `display_name`, `language` | `users.id`, `users.name` (Feldname der Schnittstellen bleibt `name`), `display_name`, `language` |
| `email` | `users.email` |
| `email_confirmed` (zählt) | neu `users.email_counts` |
| `email_proven` (bewiesen) | `users.email_confirmed_at IS NOT NULL` (unverändert in Bedeutung und Spalte) |
| `email_source` | `"provider"` wenn `email_from_provider`, sonst `""` |
| `pending_email` | `email_confirmations.address` |
| `offered_email`, `offered_email_provider`, `declined_email` | neue Spalten |
| `has_password`, `blocked`, `operator`, `picture` | `sign_in == 'password' and password_hash != ''`; `blocked_at IS NOT NULL`; `role == 'operator'`; `avatar` leer → `""`, sonst `avatar_source or "own"` |
| `find_by_username`, `find_by_email` | ohne Groß/Klein, alle Treffer, gesperrte eingeschlossen |
| `name_reserved`, `find_by_former_name` | neue Tabelle `former_names` (`name` klein eindeutig, `account_id` NULL für gelöschte, `until`) |
| `display_name_taken` | über `names.display_key` |
| `add_account` | über das ORM wie heute (der persönliche Tresor entsteht im selben Schreibvorgang), `whats_new_seen` |
| `set_username` | Name setzen, alten in `former_names`; **in derselben Transaktion** nichts weiter nötig (Ordner und Plus-Adresse lesen `former_names`) |
| `set_email(id, address, *, confirmed, proven, source)` | `email`, `email_counts = confirmed`, `email_confirmed_at = now if proven else NULL`, `email_from_provider = (source == "provider")` |
| `check_password`, `set_password` | Argon2 der App, Blindhash `accounts._dummy_hash`; `set_password`: Hash, `sign_in = password`, Sperre weg |
| `is_locked`, `note_failure`, `note_success` | `failed_logins`/`locked_until` (5, 15 Minuten, Frage 1); `note_failure(None)` in neue Tabelle `failed_unknown` |
| `end_sessions` | Browser-Sitzungen aller Stufen, wartende Anmeldungen, neuer `device_key`; **gekoppelte Geräte bleiben** (Entwurf; heute widerruft ein neues Passwort sie) |
| `list_access`, `revoke_access` | gekoppelte Geräte (`devices`, nicht widerrufen), API-Schlüssel, Passkeys |
| `second_factor` | `factor.state`, aber `none` für Konten ohne eigenes Passwort |
| Einladungen, wartende Adressen, Links | `invites` (+ `display_name`, `mailed`), `email_confirmations`, `password_resets` (+ `origin`) |
| `claim_setup` | neue Tabelle `setup_claims` |
| `notify` | `renamed`: Eingangsordner für den neuen Namen anlegen, Logzeile; `email_changed`: nichts Eigenes |

### Teil 2 (`FactorStore`, `PasskeyStore`, `SessionStore`, `PictureStore`)

Wie nexdiary (gleiche Herkunft): `totp_secret_enc` (versiegelt wie heute), `claim_step` über **`totp_last_step`**,
`totp_recovery`, `recovery_key` = `sha256(b"nexpaper-recovery-codes:" + server_key()).digest()` (der Schlüssel, mit
dem `totp.hash_recovery` heute `h1:` bildet; dann gelten die Codes von 1.12.0 unverändert); neue Spalten `totp_pending`, `totp_pending_until`, `device_key`, `avatar_source`; `factor_required` =
Einstellung `two_factor_required`; neu `passkeys_allowed` (Vorgabe an); `passkeys` und `passkey_handle` unverändert;
Sitzungen aus `auth_sessions` (`address` = `ip`, Bezeichnung aus `user_agent`) und **gekoppelte Geräte aus `devices`**
(Art `device`, Name `name`); Mail bei neuer Anmeldung je Person = `profile.notify_login`.

### `post`

`services/post_store.py` über `smtp_*` (dazu `smtp_sender_name`, `mail_last_*` als Vorgaben, keine Zeile beim Start),
Tabelle `mail_outbox`, Arbeiter jede Minute neben dem vorhandenen. Was nur nexpaper mailt (Erinnerungen, Fristen,
Exporte, Upload-Bitten, Absenderadressen des Posteingangs, Bescheide) bleibt in `mailer.py`.

## 4. Wanderung (nur ergänzend, als `ADDITIONS`)

Alles als neue `ADDITIONS` (`_additions_konten`) **ohne neue Schemanummer**: 1.12.0 startet dann weiter auf der
Datenbank (Rückweg eine Fassung lang, Bestand Regel 10), Aufzeichnung wie in `tests/schema/released/`. Davor wie immer
`backups.create(kind=UPDATE)`.

| Neu | Vorgabe für den Bestand | Bedeutung |
|---|---|---|
| `users.email_counts` | `1` für **jede** Bestandsadresse, auch die vom Anbieter (Entwurf „Bestand: Anbieteradresse“) | zählt fürs Anmelden und „Passwort vergessen“; so behalten Konten mit der Adresse ihrer Einladung (`ben`, `carla`) „Passwort vergessen“ per Adresse |
| `users.avatar_source`, `offered_email`, `offered_email_provider`, `declined_email` | `''` | |
| `users.device_key` | zufällig, beim Start für jede Zeile ohne Wert | bekannter Browser |
| `users.totp_pending`, `totp_pending_until` | `''`, NULL | |
| `users.new_password_origin` (wie nexnotes) | `''` | Hinweise nach einem Link |
| `invites.display_name`, `invites.mailed` | `''`, `0` | |
| `password_resets.origin` | `'self'` ohne `created_by`, sonst `'operator'` | |
| Tabellen `former_names`, `setup_claims`, `failed_unknown`, `mail_outbox` | leer | |
| Index `lower(name)` eindeutig | erst nach Zählen; im Bestand unmöglich doppelt, ein Doppel bricht den Start nie ab | |
| Index `lower(email)` | nicht eindeutig | Doppel gibt es (`carla`/`dora`) |
| Einstellung `two_factor_required` | nur auf einer Datenbank **mit Konten und ohne Zeile**: Zeile mit `true`; danach Vorgabe `False` | laufende Installationen behalten ihre Einstellung. Die Fixture hat die Zeile (`false`), dort kommt nichts dazu |

Folgen für 1.12.0 auf der neuen Datenbank (Rückweg): umbenannte Konten melden sich mit dem neuen Namen an, alte Ordner
und Plus-Adressen gehen an den Betreiber als „unbekannt“, Anmelden mit E-Mail geht nicht. In den Hinweis zur Fassung.

## 5. Routen

**Feldnamen und Fehlerkennungen bleiben**, Antworten bekommen nur Felder dazu. **Keine Route fällt weg**, also keine
410: der Betreiber setzt in nexpaper schon heute kein Passwort selbst.

| Route | Heute | Künftig |
|---|---|---|
| `GET /setup` | `needs_setup`, `code_required`, `min_password` … | gleich |
| `POST /setup` | `name`, `password`, `language`, `code` | `setup.setup`; dazu `display_name` (fehlt er, nimmt die Route `name`), `email`, `password_confirm` (nur geprüft, wenn geschickt); `language` gilt als Sprache des Browsers |
| `POST /auth/login` | `name` ≤ 64 | `name` bis 254, `login.authenticate` mit Bremse und `known_browser`; Antworten gleich; gesperrt nach richtigem Passwort `403 account_blocked` (der Test „Bestand“ nimmt 401 oder 403); `password_login_off` bleibt Sache der Route |
| `POST /auth/login/totp`, `/cancel`, `/auth/setup/done`, `/auth/setup/codes` | | über `factor`; Pfade und Felder bleiben |
| Passkey-Routen | | über `nexkonten.passkeys`, Hinzufügen mit Passwort bzw. frischer Anmeldung |
| `POST /auth/forgot` | `name`, 202 | `forgot_in_background` (Abschnitt 0, Punkt 1); Link **1 Stunde**; `reset_off` ohne Mailserver bleibt |
| `GET /reset/{token}` | `name`, `min_password` | `reset_state`, Felder bleiben |
| `POST /reset/{token}` | 204 | `use_reset`, **bleibt 204**; Geräte bleiben; was noch Zugriff hat, zeigt `GET /auth/access` bei der nächsten Anmeldung |
| `POST /accounts/{id}/reset-link` | `current_password` | dazu `days` (1/7/30, ab Werk 1) und `send`; **auch für gesperrte Konten**; Mail nur an eine Adresse, die zählt; ohne öffentliche Adresse Link über `request_base` |
| `PUT /me/profile` | `display_name` | dazu `name`, `email`, `password` (ein Knopf Speichern wie nexnotes) |
| `PUT /me/email` | `email`, `password`; ohne Mailserver 409 `mail_off` | `profiles.change_email`; **ohne Mailserver gilt die Adresse sofort** (zählt, ist aber nicht bewiesen: der Posteingang traut ihr nicht); dieselbe, noch nicht bewiesene Adresse noch einmal schickt weiter einen Link (nexpaper legt dafür selbst eine wartende Adresse an, Abschnitt 15, Fund 3) |
| `DELETE /me/email/pending`, `GET/POST /email/confirm/{token}` | | `withdraw_email_change`, `email_change_state`, `confirm_email` (setzt `email_confirmed_at`); Felder `name`, `address` bleiben |
| neu `POST /me/email/resend` | – | `resend_email_link` |
| neu `POST /oidc/me/address`, `DELETE /oidc/me/address` (wie nexnotes) | – | angebotene Anbieteradresse |
| `GET /auth/me` | `email_confirmed` (= bewiesen), `email_pending`, `oidc_linked` … | `email_confirmed` behält seine Bedeutung; dazu `email_counts`, `offered_email`, `offered_email_provider`, `factor_state`, `second_factor_off`, `former_name` |
| neu `GET /auth/access`, `POST /auth/access/disconnect`, `POST /auth/access/seen` | – | „Diese Geräte haben noch Zugriff“, „Alle trennen“ |
| `POST /invites` | `days`, `email`, `send` | dazu `display_name`; `GET /invites` auch abgelaufene (`expired`) |
| `GET /invite/{token}` | `min_password`, `signed_in_as` | dazu `display_name`, `name` (Vorschlag), `email` |
| `POST /invite/{token}` | `name`, `password` | dazu `display_name`, `email`, `password_confirm`; ohne `display_name` `older_request=True`, Adresse aus der Einladung (der Test „Bestand“ prüft beides) |
| `GET /accounts` | Konto, `locked`, `blocked`, `has_password` | dazu `email_counts`, `email_duplicate`, `self`, `documents` (Zahl, wie `/leaving`) |
| neu `PUT /accounts/{id}/name`, `/display-name`, `DELETE /accounts/{id}/email` | – | Betreiber, eigenes Passwort |
| `DELETE /accounts/{id}`, `GET /accounts/{id}/leaving` | | **bleiben unverändert** (Übergabe-Dialog) |
| `block`, `unblock`, `role`, `totp/reset`, `sign-out`, `permissions` | | bleiben; Faktor-Rücksetzen über `reset_overview`/`operator_reset` (`GET /accounts/{id}/totp/reset` neu wie nexnotes) |
| Koppeln: `POST /devices/pair`, `POST /oauth/token`, `POST /devices/sibling`, `POST /devices` | `account` (Name) | dazu **`account_id`** (Zahl); `account` = ältester Name des Kontos (Abschnitt 12) |
| `GET /me/intake` | `plus_address`, `folder` | dazu `former` |
| `GET /api/v1/me` | `name`, `display_name`, `scope`, `version` | dazu `id` |
| `GET/PUT /settings` | | dazu `passkeys_allowed`, `smtp_sender_name`, `mail_last_*` |
| `python -m app.reset_link <account>` | Name | bleibt, über `server_reset_link`; Benutzername oder E-Mail; `--days` |

**Alte Fehlerkennungen** (`OLD_CODES`): `username_invalid` → `invalid_account_name`, `username_taken` → `name_taken`,
`email_invalid` → `invalid_email`, `fresh_sign_in_needed` → `sign_in_again`. Bleiben: `wrong_credentials`,
`wrong_password`, `setup_code_wrong`, `already_set_up`, `invite_invalid`, `reset_invalid`, `reset_off`,
`email_link_invalid`, `email_same`, `invalid_days`, `display_name_taken`, `password_too_short`, `password_login_off`,
`account_blocked`, `use_account_page`, `name_mismatch`, `too_many_attempts`. `mail_off` kommt bei `PUT /me/email` nicht
mehr vor (die Adresse gilt dann sofort). Neu vom Modul: `email_taken`, `display_name_empty`, `*_expired`, Teil 2.

## 6. Teil 2 gegen den heutigen Stand

| Teil | Heute | Mit dem Modul | Sichtbar anders |
|---|---|---|---|
| **Zweiter Faktor** | Pflicht ab Werk (`two_factor_required`, Schalter mit Passwort beim Ausschalten); Konten nur über Anbieter und Anbieter mit „prüft selbst“ ausgenommen | `factor`; **Bestand behält seinen Wert** (Abschnitt 4), neue Installationen aus; Passkey zählt; Codes sofort zeigen (Stufe `codes` bleibt); halb eingerichteter Authenticator in der Datenbank; Betreiber-Rücksetzen mit „Passkeys auch entfernen“, „Geräte auch trennen“ | neue Installationen ohne Pflicht; `NEXPAPER_SECOND_FACTOR_OFF` neu |
| **Passkeys** | immer erlaubt | Schalter „Passkeys erlaubt“ (an); frische Anmeldung 5 statt 10 Minuten | ein Schalter mehr |
| **Sitzungen** | Liste mit Abmelden je Eintrag, „Angemeldet bleiben“, „Überall abmelden“ (Browser und Geräte); Geräte zusätzlich unter Verbindungen | `sessions`: „Angemeldete Geräte“ mit Browsern **und** gekoppelten Geräten, „Überall sonst abmelden“ (beide); Kopplungsliste unter Verbindungen bleibt (wie nexnotes) | Wortlaute; Geräte auch in der Liste der Sicherheit |
| **Neues Passwort** | Browser **und gekoppelte Geräte** enden | Browser und wartende Anmeldungen enden, **Geräte, API-Schlüssel, Passkeys bleiben**; danach „Diese Geräte haben noch Zugriff“ mit „Alle trennen“. Das eigene Passwort ändern (`PUT /auth/password`) bleibt wie heute und wie nexnotes: andere Browser und gekoppelte Geräte enden | ein iPhone bleibt nach „Passwort vergessen“ und nach dem Link des Betreibers gekoppelt |
| **Bekannter Browser** | Gerätecookie mit Konto-ID | `device_key`, altes Format über `older=` eine Fassung lang | nichts |
| **Bremse** | je Absender 5, Sperre am Konto nach 5 | `brake.BRAKE` (Absender 30, Konto/Eingabe 5, dann wachsend), Türen `confirm:`, `code:`, `mail:`, `forgot:`; Sperre am Konto **5** (Frage 1); App-Bremsen fürs Koppeln (`pairing_guard`), Einladungsmails und Absenderadressen bleiben | mehr Versuche je Absender |
| **Mail** | `mailer.py`, englisch | `post` (Outbox mit Wiederholung, Absendername, Warnung ohne Verschlüsselung, Logo, **DE/EN/FR** nach Sprache des Kontos); „Passwort vergessen“ sofort über `mailer.send_reset` | Mails in der Sprache des Kontos, mit Logo |
| **Bescheid an die alte Adresse** | bei Bestätigung per Link und beim Entfernen, nur an eine bewiesene alte Adresse | `EmailChanged.notice` des Moduls (`email_changed`, `email_removed` über `post`); nexpaper schickt ihn weiter **nur an eine bewiesene** alte Adresse (Frage 2) | nichts |
| **Mail bei neuer Anmeldung** | Mail und Web Push, Schalter `notify_login` in `PushCards.tsx` (Mitteilungen) | `post`-Mail, Web Push bleibt Zusatz am selben Schalter, Schalter unter Sicherheit | Ort des Schalters |
| **Profilbilder** | WebP quadratisch, alle Angemeldeten | `avatars` (WebP 256), Bilder von 1.12.0 bleiben, Anbieterbild nur ohne Bild | neue Bilder 256 px |
| **Notfallbefehl** | `python -m app.reset_link <account>` | gleich, `server_reset_link` | nimmt auch eine E-Mail |

## 7. Oberfläche aus dem Bausatz `ui`

Module nach `frontend/src/vendor/nexui/`, `nexkonten/`, `nexpost/`, `nexoidc/` (`sync.py copy`). `--nexui-*` (auch die
Avatar-Variablen) aus den Tokens von `index.css`, hell und dunkel. Knöpfe nur über einen Helfer aus `BUTTONS`. i18next
mit `kontenVariables('nexpaper')`, `oidcVariables`, `postVariables`. vitest-Vorlagen `nexkonten.test.ts`,
`nexpost.test.ts`, `nexui.test.tsx` (`APP_RENDER`, `APP_PAGES`, `APP_CAPS`, `APP_OWN`).

| Bildschirm | Heute | Künftig | Sichtbar anders |
|---|---|---|---|
| **Einrichtung** | Code, Name, Passwort | `SETUP_PAGE`: Code, Anzeigename, Benutzername (folgt), E-Mail, Passwort, Passwort wiederholen | vier Felder mehr |
| **Anmelden** | „Name“, Passwort, Angemeldet bleiben, Passwort vergessen?, Passkey, Anbieter | „Benutzername oder E-Mail“, sonst gleich; `account.wrong` | Beschriftung |
| **Passwort vergessen** | „Name oder Mailadresse“, „… 24 Stunden“ | „Benutzername oder E-Mail“, `account.forgotSent`; ohne Mailserver `account.forgotNoMail` | Wortlaute, 1 Stunde |
| **Neues Passwort**, **Adresse bestätigen** | | gleich, Wortlaute aus dem Modul | kaum |
| **Einladung** | Name, Passwort, Anbieter | Anzeigename, Benutzername (Vorschlag), E-Mail, Passwort zweimal, „oder“, Anbieter | drei Felder mehr |
| **Profil** | Bild, „Name“ (= Anzeigename), E-Mail mit „bestätigt/nicht bestätigt“ und „Link schicken“, „Rolle · Anmeldename“, Sprache | `PAGES.profile`: Bild, Anzeigename, **Benutzername**, E-Mail, angebotene Adresse, Sprache, Rolle klein; ein Knopf Speichern mit Passwort-Rückfrage. Die Zeile „Mailadresse nicht bestätigt“ mit „Link schicken“ bleibt als nexpapers Zusatz unter der E-Mail (sie sagt, ob der Posteingang die Adresse kennt) | „Anmeldename“ verschwindet, Benutzername wird Feld |
| **Sicherheit** | Passwort, Faktor, Passkeys, Geräte, „Überall sonst abmelden“ | `PAGES.security`, danach nexpapers eigene Teile (`pageOrder`) | Reihenfolge, Wortlaute |
| **Mein Posteingang** (Hochladen) | Ordner und Plus-Adresse | dazu Zeile „Frühere Namen gelten hier weiter: …“ nach einer Umbenennung (neuer Wortlaut DE/EN/FR) | Hinweis nach Umbenennung |
| **Kontenliste** | Tabelle mit Menü | Abschnitt 9 | ganz neu |

**Wortlaute auch französisch:** `konten`, `post` und `oidc` liefern FR; nexpapers eigene neue Sätze (frühere Namen im
Posteingang, Hinweise der Kontenliste) in `de.json`, `en.json` **und `fr.json`**; `i18n`-Test auf Vollständigkeit
bleibt grün. Alte Schlüssel (`auth.name*`, `auth.forgot.label`, `me.profile.name`, `me.profile.roleLine`,
`server.table.*`, `server.confirm.*` der Liste) fallen weg, sobald nichts sie mehr liest.

## 8. Posteingang, Bescheid, „bestätigt“

- Wem eine Mail gehört (`intake_mail.assign`): Plus-Adresse mit aktuellem oder früherem Namen, sonst bewiesene
  Absenderadresse genau einer Person (`mail_senders.owners` liest `email_confirmed_at` und `mail_senders`), sonst
  Betreiber. Eine Adresse, die nur zählt (ohne Mailserver gesetzt, aus einer nicht gemailten Einladung), zieht nie Post
  in einen Tresor.
- Einladung per Mail und Adresse unverändert angenommen: `accept_invite(..., proven=True)` (die Person hat den Link aus
  diesem Postfach) → `email_confirmed_at` gesetzt. Neu gegenüber heute, aber genau der Beweis, den der Link sonst bringt.
- Erinnerungen, Fristen, Exporte, Upload-Bitten gehen wie heute nur an eine bewiesene Adresse (strenger als „zählt“,
  das Modul erlaubt das).

## 9. Kontenliste nach konten 0.3.9

**Schalter** (`AccountCaps`, nach dem Umbau):

| `rename` | `roles` | `emailRemove` | `resetLink` | `factorReset` | `signOut` | `unlink` | `blocking` | `remove` | `restore` |
|---|---|---|---|---|---|---|---|---|---|
| ✓ (neu, gleich mit dem Umbau) | ✓ | ✓ (neu) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | – |

**`ListedAccount`** aus `GET /accounts` und `oidcApi.links()`: `username` = `name`, `emailConfirmed` = `email_confirmed`
(bewiesen: so heißt „bestätigt“ für nexpapers Nutzer), `emailDuplicate`, `operator`, `self`, `hasPassword`,
`authenticator` = `totp`, `passkeys`, `providers` (Verknüpfungen), `blocked`, `blockedAt`, `locked`, `lastSeenAt`,
`picture`.

| Heute | Künftig |
|---|---|
| Tabelle: Person (Bild, Anzeigename, klein Adresse oder Name), Anmeldung (Anbieter, Passwort mit Faktor), Rolle, KI, Zuletzt (gesperrt, vorübergehend gesperrt) | Zeile: Bild, Anzeigename, Marken (Betreiber, Du, Zweiter Faktor, Gesperrt, Vorübergehend gesperrt, Adresse doppelt, je Anbieter), klein „Benutzername · E-Mail“, „Verwalten“; im Fenster die Angaben Benutzername, E-Mail, Rolle, Anmeldung, Zuletzt angemeldet, Gesperrt seit |
| Spalte „KI“ (Haken, sofort gespeichert) | `OwnCheck` „KI erlaubt“ in **Rechte**; `server.permissionsHint` als Hinweis darunter |
| – | eigene Angabe (`FactShown`) **„Dokumente: N“** (Zahl aus `documents`, eigener Wortlaut DE/EN/FR) |
| Menü: Rolle, Link (neues bzw. erstes Passwort), Faktor zurücksetzen (nur mit Faktor), Überall abmelden, Lösen je Anbieter, Sperren/Entsperren, Konto löschen | Knöpfe aus `accountActions` in Ändern, Zugang, Beenden; dazu neu „Anzeigenamen ändern“, „Benutzernamen ändern“, „Adresse entfernen“ |
| **Löschen:** eigener Dialog mit Zahl der Dokumente (samt Papierkorb), Übergabe an eine Person (in deren Tresor), in einen gemeinsamen Tresor oder mitlöschen, Hinweis „das siehst du danach“, **Sperre, solange das Konto alleiniger Verwalter eines gemeinsamen Tresors ist**, **Kontoname eintippen**, eigenes Passwort | Knopf „Konto löschen“ aus dem Modul öffnet **nexpapers `DeleteAccount`** statt `ConfirmDialog` (SCHNITTSTELLE „Seit 0.3.9“, Punkt 4); innen aus `ui` gebaut (`Dialog`, `Field`, `SelectField`, `Button` mit `account.remove`), Satz `account.askRemove`, dann die Zahlen, dann `removeLines(CAPS)` („lässt sich nicht rückgängig machen“); Route und Felder unverändert |
| Am eigenen Konto nichts | `NOT_ON_SELF`; der Haken „KI erlaubt“ darf am eigenen Konto stehen |
| Offene Einladungen als eigene Karte, „Zurücknehmen“ mit Rückfrage | `OPEN_INVITES` (auch abgelaufene) |
| Karte „Schlüssel aller Konten“ (`AllApiKeysCard`) | bleibt eigene Karte unter den Karten des Moduls |

## 10. Test „Bestand“

`backend/tests/test_bestand.py` mit `tests/bestand/bestand-1.12.0.sql.gz` (gebaut von 1.12.0, `build.py`, Konten in
`bestand-1.12.0.json`). Start:

    cd backend && .venv/Scripts/python.exe -m pytest tests/test_bestand.py -q

Prüft (57 Fälle grün heute): Start ergänzt nur (Spalten; Zeilen in `users`, `vaults`, `vault_members`,
`auth_sessions`, `invites`, `password_resets`, `email_confirmations`, `api_keys`, `devices`, `oidc_providers`,
`oidc_links`, **`settings`**); Konten mit Name, Adresse, `email_confirmed_at`, Passwort, Faktor, Sperre, Rolle und
Tresorordner wie vorher; Anmelden mit Name (auch groß und mit Leerzeichen), falsches Passwort 401, Code und
Wiederherstellungscode; gesperrt 401 oder 403; gelöscht 401; Passwort-Anmeldung aus; **Sperre nach `MAX_FAILURES`**;
Konten ohne Passwort; Anbieter; Sitzung; gekoppeltes iPhone (`Bearer npd_…` an `/auth/me`); API-Schlüssel; offene
Einladungen mit `name` und `password`; offene Links beider Arten (204); wartende Adresse per Link; „Passwort vergessen“
per Name an die eigene Adresse (auch unbewiesen und geteilt), per eindeutiger Adresse (auch unbewiesen), nie an ein
anderes Konto, nichts ohne Weg (`emil`, `fritz`, `hans`, `ida`, unbekannt).

Strikte `xfail` (`AFTER_THE_CHANGE`), deren Marker mit dem Umbau gehen: Anmelden mit eindeutiger bewiesener Adresse;
geteilte Adresse findet bei „Passwort vergessen“ kein Konto. **Nichts sonst in der Datei wird angepasst.**

Was er festlegt: `MAX_FAILURES` 5 (Abschnitt 0), `mailer.send_reset` mit dieser Unterschrift, `notices.later`/`settle`,
`totp.code_at`, keine neue Zeile in `settings`, `email_confirmed_at` unverändert, Tresorordner = Name bei der Anlage.

Vor dem Aufspielen dieselbe Probe auf einer **Kopie** der Live-Datenbank: doppelte Adressen zählen, die Fassung gegen
die Kopie starten, prüfen, ob `two_factor_required` eine Zeile hat.

## 11. Reihenfolge beim Bau

1. Module kopieren (`konten`, `oidc`, `post`, `ui`), `requirements.txt`, `check`.
2. `ADDITIONS` (Abschnitt 4), Store-Adapter, Vertragsadapter (`blocking=True`, `required_second_factor=True`,
   `reusable_invites=False`, `legacy()` mit der Datenbank von 1.12.0), Vertragstests grün.
3. Anmelden, Code, Passkey, Einrichtung, Einladung, „Passwort vergessen“, Links, Notfallbefehl über das Modul; Marker
   für Adresse und Regel 3 weg.
4. `former_names` im Posteingang (Ordner, Plus-Adresse, „Mein Posteingang“, Betreiberliste), dann Profil mit
   Benutzername und Adresse, Betreiber-Routen.
5. Koppel-Antworten mit `account_id` und ältestem Namen (Abschnitt 12, Server-Teil).
6. `post`, OIDC 1.1.0.
7. Oberfläche aus `ui` (Abschnitte 7 und 9), Wortlaute DE/EN/FR, Playwright-Texte anpassen (nicht ausführen),
   `npm run lint`.
8. `docs/api.md` (`account_id`, `account` = ältester Name, `former`, neue Routen), README (`NEXPAPER_SECOND_FACTOR_OFF`,
   Setup-Code mindestens 16 Zeichen, Anmelden mit E-Mail, Link 1 Stunde, frühere Namen im Posteingang).
9. nexpaper-ios nach Abschnitt 12 (eigener Auftrag, eigenes Repo).

## 12. Begleit-App nexpaper-ios

**Heute (1.3.1, `d7be6bf`):** Die App koppelt per QR-Code (`POST /devices/pair`) oder Browser-Anmeldung
(`ASWebAuthenticationSession`, `POST /oauth/token`), ein weiteres Gerät holt sich über iCloud einen eigenen Schlüssel
(`POST /devices/sibling`). Jede Antwort trägt `account` = Benutzername, die App speichert ihn in `Connection.account`.

| Datei | Stelle | Rolle des Namens |
|---|---|---|
| `app/Shared/APIClient.swift` | `struct Connection { address, token, account, deviceId }`, Schlüsselbund-Eintrag „connection“ (`Shared/Keychain.swift`, JSON über `JSONDecoder()`) | gespeicherte Verbindung, auch für die Teilen-Erweiterung |
| `app/Shared/Models.swift` | `PairedDevice { token, device, account }`, `OAuthToken { accessToken, tokenType, deviceId, account? }` | Koppel-Antworten |
| `app/NexPaper/Model/Connecting.swift` | `Connection(..., account: paired.account, ...)` (QR) und `account: answer.account ?? ""` (OAuth) | Übernahme |
| `app/NexPaper/Model/AppModel.swift` `connected(_:byHand:)` | `Keychain.load()?.account != c.account` → `store.clear()`, `queue.clear()`, `catalog.clear()` | **leert lokalen Speicher, Warteschlange und Katalog**, wenn sich der Name ändert |
| `app/NexPaper/Model/AppModel.swift` `disconnect()`, `declinedSetup` | `SharedSetup.key(c.address, c.account)` | „von Hand getrennt“, kommt nicht über iCloud zurück |
| `app/NexPaper/Model/SharedSetup.swift` | `SharedSetup.account`, `key = "<adresse>#<account>"`, `follows(...)` vergleicht den Schlüssel | iCloud-Abgleich iPhone ↔ iPad (Schalter Face ID, Erinnerungen; neues Gerät übernimmt die Verbindung) |
| `app/NexPaper/Views/ConnectViews.swift` | „Angemeldet als“ = `me.shown ?? connection.account` | Anzeige (frisch aus `/auth/me`, nur offline der gespeicherte Name) |
| `app/Shared/Models.swift` `struct Me { id, name, displayName, … }` | `GET /api/v1/auth/me` mit dem Geräte-Schlüssel | **hat `id` schon** |

**Was bricht:** Wer umbenennt und danach neu koppelt (Gerät verloren, App neu installiert, Verbindung von Hand
getrennt), verliert nicht hochgeladene Scans der Warteschlange, den lokalen Speicher (angeheftet, zuletzt, offline
behalten) und den Katalog. iPhone und iPad mit unterschiedlichem gespeichertem Namen gleichen ihre Schalter nicht mehr
ab, und ein von Hand getrenntes Gerät mit dem alten Namen kommt über iCloud zurück. (Nach „Passwort vergessen“ bleibt
das Gerät mit dem Umbau gekoppelt, Abschnitt 6; der häufigste Anlass zum Neukoppeln fällt damit weg.)

### Vorschlag Server (Teil des nexpaper-Umbaus)

1. `account_id` (Zahl, `users.id`) zusätzlich in `PairedOut` (`routers/pairing.py`, `routers/devices.py` für
   `POST /devices`), `BroughtOut` (`/devices/sibling`) und in der JSON-Antwort von `/oauth/token` samt `_TOKEN_BODY`.
2. **Brücke für App-Fassungen vor dem Update:** `account` nennt den **ältesten Benutzernamen** des Kontos (erster
   Eintrag in `former_names`, sonst der aktuelle). Für nie umbenannte Konten ändert sich nichts. Weil frühere Namen nie
   neu vergeben werden, ist der Wert eindeutig und fest; eine App 1.3.x vergleicht ihn beim Neukoppeln mit dem
   gespeicherten und leert nichts, und der iCloud-Schlüssel bleibt gleich. `docs/api.md` beschreibt das Feld so
   („the account's first username, stable across renames; the current one is in `/auth/me`“).
3. Tests in nexpaper: Koppeln nach Umbenennen antwortet mit gleicher `account_id` und gleichem `account`; ein Gerät von
   vor dem Umbenennen spricht weiter für das Konto (`/auth/me` mit `Bearer npd_…` nennt den neuen Namen).

### Vorschlag App (nexpaper-ios, nächste Fassung)

1. `Connection.accountId: Int?` (optional, damit der Schlüsselbund-Eintrag älterer Fassungen ohne das Feld weiter
   gelesen wird; ein nicht optionales Feld mit Vorgabe würde der synthetisierte Decoder verlangen). `PairedDevice` und
   `OAuthToken` bekommen `accountId: Int?` (die Antworten werden mit `convertFromSnakeCase` gelesen); `Connecting.swift`
   und `SharedSetup.connection(_:)` reichen sie durch.
2. **Nachtragen:** Nach jedem `refreshMeta` gilt `me.id`; fehlt `connection.accountId`, schreibt die App ihn in den
   Schlüsselbund. Weicht `me.name` vom gespeicherten `account` ab, frischt sie den Namen auf (Schlüsselbund und
   `SharedSetup`). So kennt jede Verbindung ihre ID, bevor jemand umbenennt.
3. **Gleiches Konto** an einer Stelle (`Connection.sameAccount(as:)`): gleiche Adresse und, wenn beide eine ID haben,
   gleiche ID; sonst gleicher `account`. `AppModel.connected` leert Speicher, Warteschlange und Katalog nur, wenn das
   **nicht** gilt.
4. **iCloud:** `SharedSetup` bekommt `accountId: Int?`; `follows` und der Vergleich mit `declinedSetup` gehen über
   dieselbe Regel (ID wenn beide sie haben, sonst Name). `declinedSetup` speichert zusätzlich die ID. So folgen iPhone
   (neu) und iPad (noch alte Fassung, ohne ID) einander weiter, solange der Name gleich ist, und nach dem Update beider
   auch über eine Umbenennung hinweg.
5. Anzeige „Angemeldet als“ bleibt `me.shown`; ein Wortlaut „Benutzername“ ist dort nicht nötig.

### Wie es getestet wird

- **Unit-Tests** (Swift Testing, `app/NexPaperTests`, Lauf auf dem Mac mini mit `tools/mac.sh test`):
  `SharedSetupTests`: gleiche ID mit neuem Namen folgt; andere ID mit gleichem Namen folgt nicht; Eintrag ohne ID
  (ältere Fassung) folgt über den Namen; ein JSON ohne `accountId` liest sich. `AppTests`: Neukoppeln mit gleicher ID
  und neuem Namen behält Warteschlange, Speicher und Katalog; andere ID leert alles; Verbindung ohne ID bekommt sie nach
  `refreshMeta` aus `/auth/me` (`FakeTransport`); Koppel-Antwort mit und ohne `account_id` (nexpaper vor und nach dem
  Umbau). Jede Gegenprobe einmal rot (Rückgabecode).
- **Gegen eine Testinstanz** (nexpaper vom Zweig `konten`, `tools/testinstanz`): koppeln, offline zwei Scans in die
  Warteschlange, im Browser umbenennen, in der App trennen und neu koppeln, Warteschlange geht hoch; iPad über iCloud
  übernehmen, Schalter Face ID am iPhone umlegen, iPad folgt. Dasselbe einmal mit der App 1.3.1 aus TestFlight gegen den
  neuen Server (Brücke `account`).
- **TestFlight** (Gruppe „Intern“), dann App Store.

## 13. Risiken

1. **Posteingang vertraut „bewiesen“.** Legt der Store `email_confirmed` (zählt) auf `email_confirmed_at`, ziehen
   Adressen ohne Link fremde Mails in einen Tresor. Mit zwei Spalten ausgeschlossen; Test: Adresse ohne Mailserver
   gesetzt, Mail von dort landet beim Betreiber als „unbekannt“.
2. **Frühere Namen im Posteingang:** ohne `former_names` in `scan` und `assign` landen Dokumente nach einer Umbenennung
   beim Betreiber. Tests für Ordner und Plus-Adresse mit altem Namen, gesperrtem Konto und gelöschtem Konto.
3. **Sperre 5/10** (Frage 1) und **Bremse** des Moduls: der Test „Bestand“ zeigt, was geht.
4. **Zweiter Faktor:** Zeile `two_factor_required` beim Bestand ohne Zeile; sonst verliert eine Installation die Pflicht.
5. **Neue Zeilen in `settings` beim Start** machen den Test „Bestand“ rot.
6. **Gekoppelte Geräte nach neuem Passwort** bleiben jetzt; wer nach einem Diebstahl „Passwort vergessen“ nimmt, muss
   „Alle trennen“ drücken. Der Hinweis danach sagt es.
7. **Rückweg auf 1.12.0** geht mit `ADDITIONS`, aber ohne frühere Namen, ohne Anmelden mit E-Mail.
8. **Französisch:** jeder neue eigene Satz in drei Sprachen.

## 14. Was sich gegenüber dem Plan vom 24.11. geändert hat

| Damals | Jetzt |
|---|---|
| „Passt das Modul?“ 1: ein `email_confirmed` für zwei Dinge | Modul hat `email_confirmed` und `email_proven` (`set_email(..., proven=)`) |
| Bestand: Adressen vom Anbieter zählen nicht | Entwurf: jede Bestandsadresse zählt; Herkunft getrennt |
| „Passt das Modul?“ 2: keine Sperre am Konto | im Modul (`is_locked`, `note_failure`) |
| 3: gesperrt verrät nichts | entschieden: nach richtigem Passwort „gesperrt“ (403) |
| 4: frühere Namen | im Modul (`name_reserved`, `find_by_former_name`), für immer reserviert, auch gelöschte |
| 5: kein Bescheid an die alte Adresse | im Modul (`EmailChanged.notice`, `post` `email_changed`/`email_removed`) |
| 6: `forgot` schreibt im Aufruf | `forgot_in_background` |
| 7: Einladung fest 7 Tage | entschieden: 1/7/30 wählbar wie heute |
| 8: Anzeigename Pflicht bricht alte Anfragen | `older_request` |
| 9: kein Französisch | Modul liefert FR |
| Umbenennen erst nach iPhone-Update | entschieden: gleich mit dem Umbau; iPhone-App im selben Zug (Abschnitt 12), Brücke über `account` |
| Wanderung „nur als Schemaschritt“ | als `ADDITIONS`, Rückweg auf 1.12.0 bleibt offen |
| Neues Passwort beendet Geräte | entschieden: Geräte bleiben, „Alle trennen“ |
| Teil 2, Kontenliste, `ui` | neu in diesem Plan |

## 15. Funde am Modul (nicht hier behoben)

1. **Bremse am Konto gegen Sperre nach 10:** Der Topf `account:<id>` (5 frei) antwortet ab dem siebten Fehlversuch mit
   429, bevor die Sperre am Konto nach 10 (Entwurf Teil 2) greift. nexpapers Test „Bestand“ prüft die Sperre mit
   `MAX_FAILURES` Versuchen und jedem Mal 401; mit 10 wird er rot. Entweder bleibt nexpaper bei 5 (Vorschlag), oder
   Entwurf und Bremse werden aufeinander abgestimmt.
2. **Bescheid an die alte Adresse:** Das Modul schickt ihn an eine alte Adresse, die **zählte**. nexpaper schickt ihn
   heute nur an eine **bewiesene** (eine nie bestätigte Einladungsadresse kann vertippt sein und einem Fremden gehören).
   Vorschlag: das Modul nimmt `email_proven`, wo die App beweist, oder sagt im `notice`, ob die alte bewiesen war.
3. **Eine Adresse, die zählt, nachträglich beweisen:** nexpaper schickt auf Wunsch einen Link an die **jetzige**,
   noch nicht bewiesene Adresse (für den Posteingang). `change_email` mit derselben Adresse ist im Modul `email_same`,
   `resend_email_link` gilt nur für eine wartende. nexpaper legt die wartende Adresse dafür selbst über den Store an;
   besser wäre eine Funktion `prove_email` im Modul.
4. **„Passwort vergessen“ und Outbox:** `forgot_in_background` erwartet, dass `send` bei einem Fehler wirft; über die
   Outbox von `post` wirft es nie. Die Doku sollte sagen: dieser Weg sendet sofort.
5. **Anbieter prüft den zweiten Faktor selbst** (`trusts_second_factor`, `second_factor_by_provider`): kennt
   `factor.state`/`next_step` nicht; die App hält es im OIDC-Weg.
6. **Gekoppelte Geräte als Begleit-App-Schlüssel:** `Account` hat keine feste Kennung außer der ID; die Brücke
   „ältester Name“ für alte iPhone-Apps ist App-Sache. Für Stufe 2 (Geräte koppeln) sollte das Modul `account_id` in
   allen Koppel-Antworten vorschreiben.
7. **Tabelle der Schalter** in `konten/README.md` zeigt für nexpaper `rename` und `emailRemove` als „–“ (Stand vor dem
   Umbau).

## 16. Offene Fragen (entscheidet der Besitzer der Apps)

1. **Wie viele falsche Passwörter, bis ein Konto gesperrt wird?** nexpaper sperrt heute nach 5 Versuchen für 15 Minuten.
   Der Entwurf sagt „10, überall“. Mit dem neuen Modul würde nexpaper bei 10 aber schon ab dem siebten Versuch „zu viele
   Versuche“ sagen, und der Pflichttest für laufende Installationen schlägt dann an. Soll nexpaper bei 5 bleiben?
   Vorschlag: ja, bei 5.
2. **Hinweis an die alte Mailadresse:** Wenn jemand seine Adresse ändert oder entfernt, schickt nexpaper heute nur dann
   einen Hinweis an die alte Adresse, wenn diese einmal per Link bestätigt wurde (eine nur vom Betreiber eingetippte
   Adresse kann vertippt sein und einem Fremden gehören). Das neue Modul würde ihn an jede alte Adresse schicken, mit der
   man sich anmelden konnte. Soll es bei „nur bestätigte“ bleiben? Vorschlag: ja.
