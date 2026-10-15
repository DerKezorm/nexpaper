# The nexpaper API

Everything the web app does goes through `/api/v1`; the web app has no routes of its own. What is under `/api/v1`
stays as it is: new fields may come, nothing is renamed or taken away. A change that would break a program goes to
`/api/v2` beside it.

- **The description**: `/api/v1/docs` lists every route on one page (no script, nothing loaded from elsewhere). The
  machine-readable description is `/api/v1/openapi.json` (OpenAPI 3).
- **The snapshot**: the description is kept in `backend/tests/schema/openapi.json`, and a test fails when the interface
  changes without the snapshot being renewed on purpose.

## Ways to sign in

| Who | How | Used for |
|---|---|---|
| A browser | The session cookie, plus the header `X-Nexpaper-Client` on every changing request | The web app |
| A device (phone, later app) | `Authorization: Bearer npd_…` | Everything the account may do, except changing the way into the account |
| A program | `Authorization: Bearer npk_…` (an API key) | Reading (scope `read`), or bringing files in (scope `upload`) |

A request that carries `Authorization: Bearer` is judged by that token alone; the cookie is not looked at, and a wrong
token never falls back to it. A changing request with a token needs no `X-Nexpaper-Client`: a page on another site can
set neither header.

### Sign-in providers (a browser)

Sign-in through an OpenID Connect provider is a browser's way, under `/api/v1/oidc`, the same in every nex app:
`GET /providers` (the buttons of the sign-in page, open), `GET /<short name>/start[?invite=…][&next=<page>]` and
`GET /<short name>/callback` (`/callback` for the entry `oidc`, the address of 1.0.1). After the provider the browser holds
the session cookie, or lands on `/login?step=code` when the code of nexpaper's own second factor is due; a page given as
`next` (the authorization page of an app being paired) comes back after either. Linking, unlinking and the operator's
list (`/me`, `/<short name>/link`, `/me/address`, `/admin/…`, `/authentik/…`) answer `403 browser_only` to a token.

### Devices

Made in the web app (**My account, Devices and apps**, or `POST /api/v1/devices` from a signed-in browser):

- The token is shown once; nexpaper keeps only a checksum. It acts with the rights of its account.
- Only a signed-in browser may pair, list or revoke devices, make API keys, change the password, the second factor or
  the passkeys, change or take away the mail address, or link or unlink a sign-in provider: these routes answer `403
  browser_only` to a token. The same goes for **every route of the operator** (settings, accounts, invitations, links to
  set a new password, backups, the log, the mail and push setup): the operator's side is the browser's, even for the
  operator's own token, so a lost phone is no way into the server. The second factor was met when the device was paired.
- A device stops working at once when it is revoked, when its account is blocked, locked or deleted, when "sign out
  everywhere" is used, and while the operator requires a second factor the account has not set up yet.
- A device can also pair itself with a code the web app shows (QR code) or, for an app, with OAuth 2 and PKCE: see
  [Pairing a device](#pairing-a-device).

### API keys

Off until the operator switches them on (**Settings, API**). A key reads as its account, never more (`scope: read`); a
key of scope `upload` (a scanner, a script, the iPhone shortcut), which only the routes that take files accept, can
upload and reads nothing: `GET /uploads` lists only the uploads this key started, and an upload of another key or of a
browser answers `404`; a file the account has already answers `exists: true` with no `document` (no title, no id), and
an accepted file carries no `duplicate`. A key of one scope is turned away on the routes of the other (`403
key_scope`). It runs out after 30, 90 or 365 days, or never, and can be blocked for good by the operator.
A request that carries an `Origin` header is refused: a key is for programs, not web pages.

## Errors and limits

Errors look like `{"detail": {"code": "token_invalid", "message": "No valid device token."}}`. The code is stable; the
message is English.

| Answer | Code | Meaning |
|---|---|---|
| 401 | `sign_in_required` | No session. |
| 401 | `token_invalid` | A device token that does not exist, was revoked, or whose account is blocked or locked. |
| 401 | `key_invalid` / `api_off` | An API key that does not hold, or keys are switched off. |
| 401 | `token_wrong_kind` | An API key where a device token belongs, or the other way round. It does not count as a wrong guess. |
| 403 | `browser_only` | The route needs a signed-in browser, not a token. |
| 403 | `second_factor_setup_required` | The operator requires a second factor this account has not set up. |
| 429 | `too_many_attempts` | Five wrong tokens, keys or passwords from one address: it rests a quarter of an hour. |
| 413 | `too_large` | A file (or the request) is larger than the limit the operator set; `max_mb` says how large. |
| 415 | `unsupported_type`, `xml_not_invoice`, `xml_doctype` | The content of a file is not one of the kinds that are taken. |
| 429 | `too_many_uploads`, `upload_space` | The account has as many uploads in pieces, or as many bytes of them, open as it may. |
| 429 | `slow_down` | More than 120 requests a minute with one key; `Retry-After` says when to go on. |
| 429 | `upload_limit` | A key of scope `upload` brought in 50 files this hour (`per_hour`); `Retry-After` says when to try again. |

A wrong token counts against the sender like a wrong password.

## Routes for programs

### `GET /api/v1/me`

With an API key: who the key speaks for: `name`, `display_name`, `scope` and the nexpaper `version`.

### `GET /api/v1/dashboard`

With an API key of scope `read`: the numbers for a dashboard card, counted among what the key's account may read (its
vaults and what was shared with it), the trash left out. Counts, a few titles, dates and links; no text, sender,
amount or tag leaves.

```json
{
  "version": "1.0.1",
  "inbox": 7,
  "inbox_oldest": [{"id": 12, "title": "Invoice utilities", "added_at": "2026-10-01T08:12:00+00:00",
                    "url": "https://paper.example.com/eingang/12"}],
  "inbox_oldest_at": "2026-10-01T08:12:00+00:00",
  "filed": 412,
  "total": 419,
  "added_week": 9,
  "processing": 1,
  "deadlines": [{"id": 40, "title": "Car insurance", "date": "2026-10-20", "kind": "due",
                 "url": "https://paper.example.com/dokument/40"}]
}
```

- `inbox`: the inbox of the account as the menu shows it: documents waiting in the vaults where it may change things
  (not filed, not being read, not in the trash). Somebody who may only read a vault has no inbox there. `inbox_oldest`
  holds the five oldest of them, the oldest first; `inbox_oldest_at` is the arrival of the oldest, or `null` when
  nothing waits.
- `filed`: filed documents. `total`: everything not in the trash. `added_week`: those that came in during the last
  seven days. `processing`: those whose text is being read. All four are counted among everything the account reads.
- `deadlines`: the dated terms of documents (`kind`) that fall from today to 14 days ahead, by day, at most 20. Three
  kinds count: `due` (a payment falls due), `contract_end` (a contract ends or renews) and `warranty_end` (the last day
  to claim under a warranty). `keep_until` is not a deadline and is left out, as is the date printed on a document. A
  contract with a notice period shows once more as `notice`, on its last day to cancel. A deadline marked done (paid,
  cancelled, claimed) is left out. A document with two such terms shows twice. "Today" is today in the time zone of the
  account.
- `url`: the page of the document in the web app: `/eingang/<id>` while it waits in the inbox, `/dokument/<id>` once
  filed. It starts with the public address when the operator set one (**Settings**), else with the address the request
  came to.

A key of scope `upload` gets `403 key_scope`. The other answers are those of every route for programs (see the table
of errors): `403 origin_refused`, `401 api_off`, `401 key_invalid`, `401 token_wrong_kind`, `429 slow_down`.

### `GET /api/v1/auth/me`

With a session or a device token: the account, its profile and what this server offers it.

### `GET /api/v1/health`

`{"status": "ok", "version": …}`, open to everybody (the container's health check uses it).

## Vaults, documents and sharing

Every route below is under `/api/v1`. Reading (`GET`) works with a browser session, a device token and an API key; every
route that changes something needs a browser or a device (a key only reads). A vault or document the caller may not see
answers `404 not_found`, exactly like one that does not exist; one they see but may not change answers `403 forbidden`.

- **Vaults** (`/vaults`): every person has one of their own, made with the account; shared vaults are made by the operator
  (`POST /vaults`, browser only). Rights in a vault: `read`, `edit`, `manage`. Changing members, renaming and deleting a
  vault need a signed-in browser. `PUT /vaults/{id}/members` sets everybody at once (`{"members": [{"user_id", "right"}]}`,
  one write: a refusal changes nothing); `PUT`/`DELETE /vaults/{id}/members/{user}` change one. A vault keeps a manager,
  and the owner of a personal vault always manages it. Nobody sees the personal vault of another person, the operator
  included, unless it was shared. The list comes with the caller's own vault first, then other personal vaults, then the
  shared ones in the order they were made; members with the owner first, then by right.
- **Documents** (`/documents`): list (by id, `after`, `limit`; filters `vault_id`, `status`, `via_share=true|false`,
  `sender=<name>`, `tag=<name>`), read, change fields (`PATCH`: title, sender by name, `kind_id`, `date`, `amount` in cents,
  `tags`, `dates`, `status` inbox or filed), move to another vault (`edit` in both; sender and tags follow as the target
  vault's own), trash for 30 days (`DELETE`), restore, delete for good from the trash before the 30 days are over (`POST
  /documents/{id}/purge`: a manager of the vault, or the person it belongs to while they may change it, and only from a
  signed-in browser, since it cannot be undone (a device token gets `403 browser_only`); `409 not_in_trash` for one that
  is not in the trash; nothing of it stays, the history neither, the log notes it). Notes and the history (`/events`: who, when, what, which fields,
  never contents; notes added, changed, deleted; changes made through a sender, tag or kind; a change of the status also
  says where it went, `status`: `filed` or `inbox`). A document is made by an upload (below). Ids are never given twice.
  `suggest` on a document says, per field, where a proposal of the inbox came from (`rule`, `ai`, `einvoice`, `text`,
  `default`, `last_time`); empty while nothing proposes. `share_count` and `link_count` (people it is shared with,
  links that work now) are filled only for a caller who may share it (`can_share`), else empty. A title holds no
  characters that turn the direction of text (U+202A to U+202E, U+2066 to U+2069, U+200E, U+200F, U+061C): they are
  taken out, from a title made of a file name too. A title made of a file name has no folder and no ending, and is made
  once, when the file is taken (`Rechnung 1.2 Strom.pdf` is `Rechnung 1.2 Strom`, sent at once or in pieces); a name
  or a mail subject with nothing else in it (only such characters, only an ending) gives the title `Document`.
  A date outside 1900 to 2200, or no date at all, answers `422 invalid_date` with `field`: `date`, or `dates[n]` for the
  n-th term of `dates` (counted from 0 as sent), so a page can mark the field.
- **Sharing**: one document with a person (`PUT /documents/{id}/shares/{user}`, right `read` or `edit`) or with somebody
  without an account by a link (`POST /documents/{id}/links`: recipient, `days`, `allow_download`). Only the managers of the
  vault and the person the document belongs to share, and only they learn whom it is shared with
  (`GET /documents/{id}/shares` and `GET /documents/{id}/links`: `403` for readers, editors and recipients of a share,
  `404` for who may not see the document). The token is kept sealed with the server's secret (the database
  alone tells nobody a token); `POST /documents/{id}/links/{link}/address` gives the address again to the person who made
  the link and to the managers of the vault (`404` for everybody else) and puts `link_copied` in the history (at most
  once in ten minutes per person and link). `GET /l/{token}` does not count an opening when the request carries the
  session of somebody who may see the document anyway (the preview of the person who made it).
  `GET /l/{token}` and `GET /l/{token}/file` need no sign-in and answer `404` for every kind of dead link: revoked, run
  out, the document in the trash, links switched off, or its maker no longer allowed to share it (taken out of the vault,
  blocked, deleted). `link_max_days` is the longest a link may last, counted again when the operator lowers it. Without
  `allow_download` the file is never handed out (`403 download_not_allowed`, also for a `Range` request). Wrong tokens
  count on a brake of their own (twenty free per address), apart from the sign-in.
- **Senders and tags** (`/senders`, `/tags`) belong to a vault: one row per name and vault, names compared with case and
  Unicode folded. The lists gather a name across the vaults the caller is in and the documents shared with them
  (`[{"name", "items": [{"id", "vault_id"}]}]`, filter `vault_id`). Renaming and
  deleting act on one row and need `edit` in its vault. Renaming onto a name the vault has already merges the two and
  needs `manage` there; with only `edit` the answer is `409 name_taken`, as for any taken name. Deleting a sender that
  documents use needs `manage` too: with only `edit` it is `409 in_use` with `documents`, and `403 forbidden` with
  `?force=true`, which is no way round the right. A row no document uses goes, for anybody with `edit`.
- **Kinds** (`/kinds`) are of two sorts: the ones that come with nexpaper, for the whole server (`vault_id` empty; only
  the operator in a browser makes, renames and deletes them), and the ones a vault makes for itself (`vault_id`, like its
  senders and tags: anybody with `edit` in the vault makes and renames them, and deletes them; while documents use a
  kind that is `409 in_use` with `documents` unless a manager or `?force=true`). `GET /kinds` lists the server's kinds and those of the
  caller's vaults (a name may repeat across vaults); `?vault_id=` gives the choice for a document of that vault, the
  server's and the vault's, one entry per name. `POST /kinds` `{name, hue, vault_id}`: a name the vault can already choose
  (its own kind, or one of the server's) answers `200` with that kind instead of making a second one, any other `201`.
  A document has a kind of the server or of its own vault (`422 kind_unknown` otherwise, the same answer as for a kind that
  does not exist); a document that moves to another vault takes its kind along by name (the server's kind stays, the
  target's kind of that name is taken, else one is made there). Nothing about the kinds of another vault shows anywhere:
  not in the lists, not in an answer for a name, not for an id. `kind_id` as a filter (`/search`, exports) matches that
  kind and its namesakes in the vaults the caller is in; `art:` matches by name anyhow. A rule of a vault names the
  server's kinds and that vault's; a rule for the whole server the server's only. The import from Paperless makes the
  kinds it needs in the vault a document comes to.
- **Order** (`GET /order/senders`, `/order/tags`, `/order/kinds`): the entries with the number of documents behind each,
  for a page that tidies them. `{"items": [{"id", "name", "vault_id", "right", "documents", "in_trash", "can_change"}],
  "total"}` (kinds also `key`, `hue`, `position`); filters `vault_id`, `q` (part of the name, case and accents aside),
  `order` (`name`, or `documents` for the most used first), `limit` (at most 500) and `offset`. Only the vaults the caller
  is in are looked at: nothing of another vault is listed or counted, and a `vault_id` the caller is not in answers like an
  empty one. `documents` leaves out what is in the trash (`in_trash`). `can_change` says whether the caller may rename,
  merge and delete the entry (`manage` in its vault; the operator for a kind of the server, which is counted over the
  caller's vaults only). `POST /senders/{id}/merge`, `/tags/{id}/merge` and `/kinds/{id}/merge` with `{"into": id}` move
  all documents to another entry of the same vault and delete the first one (`manage` there; a kind of the server needs
  the operator in a browser and merges only into another kind of the server, a kind of a vault into one of the server's or
  of the same vault; rules that named it name the other one). `422 merge_same`, `422 merge_other_vault`; an entry in a
  vault the caller is not in answers `404` like one that does not exist.
- **The inbox as a list** (`GET /inbox`): what waits to be filed, in the vaults where the caller may change things
  (`edit` or `manage`, or a share with `edit`): a member with `read` only has no inbox in that vault, nothing of it is
  listed or counted. Filters `vault_id`, `q` (part of the title or of a sender's name, case and accents aside),
  `sender` (a name), `kind_id`, `source`, `owner_id` (who brought it in); `sort` (`new`, `old`, `date`); `limit` (at most
  200) and `offset`. Documents being read come first. `{"items", "total", "counts", "shared", "all", "reading"}`: `total`
  follows all the filters, `counts` says how many each vault would show under the same filters apart from the vault
  itself (vault id as text to number, only vaults the caller is in with `edit` or `manage`), `shared` how many more they
  may change through a share of the document alone (no vault number is given for those; `?shared=true` lists just
  them), `all` is the sum of both. `GET /counts` gives `{"inbox", "reading", "trash", "deadlines",
  "deadlines_overdue"}`, the numbers the menu shows (`deadlines`: open deadlines that are overdue or come in the next
  14 days, see "Deadlines"; both are 0 for somebody who switched deadlines off, `profile.deadlines`). `POST /inbox/file` `{"ids" (at most 200), "vault_id", "kind_id", "add_tags" (at most 10)}` files many at
  once: the proposals stay as they are and filing takes them over, `vault_id` moves each document first (`edit` in both
  vaults), `kind_id` and `add_tags` apply to all. Every document is checked on its own, as a single change would be;
  the answer is `{"filed": [ids], "failed": [{"id", "code"}]}` with the code a single change would have given
  (`forbidden`, `still_processing`, `not_in_inbox`, `kind_unknown` ...); a document the caller may not see fails as
  `not_found`, exactly like one that does not exist. A kind or a tag the target does not accept is found before anything changes, so the document stays untouched in its old vault.
- **Deleting an account** (operator, browser): `GET /accounts/{id}/leaving` says how many documents its own vault holds and
  which shared vaults it manages alone. `DELETE /accounts/{id}` takes the operator's password, `confirm_name` (the
  account's name as it is) and, when there are documents, `documents`: `transfer_to_user` (with `target_user_id`: into
  that person's own vault, who becomes the owner), `transfer_to_vault` (with `target_vault_id`, a shared vault) or
  `delete_documents` (for good, the files in the background). Without a choice: `409 personal_vault_not_empty` with
  `documents`. One write; the links the person made end, the shares to them go. The operator may choose themselves
  or a vault they are in (`leaving` names them: `heirs_you_see`, `shared_vaults[].you_see`); every document taken over
  gets `taken_over` in its history with the account's name and the operator.
- **Following along** (`GET /changes?since=<n>&limit=`): the documents the caller may see whose `change_seq` is above `n`,
  oldest first, plus markers without contents: `gone` (a document is no longer visible), `vault_lost` (drop the vault's
  documents; the ones still visible through a share follow with a newer number), `vault_refresh` (fetch them anew). Ask
  again with `next` while `more` is true. A page is read in one read transaction, and a number appears only after every
  smaller one, whatever else writes at the same time. `since=0` brings no markers (a program that starts has nothing to
  drop). Markers are kept 90 days; a number older than the oldest kept answers `410 sync_from_start`: start again from 0.
- **Files on the disk**: `<data>/dokumente/<vault>/<year>/<sender>/<date> <kind>.pdf`. The files follow the fields in the
  background; the original is never overwritten and its checksum stays.

## Bringing files in

A file becomes a document in the vault named by `vault_id` (one the caller may add to: `403` when they may only read
there, `404` for a vault they cannot see), else in the vault they chose for their uploads (My account), else in their own.
The kind of a file is read from its **content**, never from its name or the type a browser claims: PDF, JPEG, PNG, TIFF,
HEIC, WebP, AVIF (an animation counts by its first frame), and XML only when it is an e-invoice (UBL or CII; reading it comes later). Anything else is `415`, a program called
`.pdf`, a web page called `.png` and an SVG included. The name is only a proposal for the title. A new document stands
as `processing` until the worker has read it (pages counted, a preview drawn, a picture turned into a PDF); then it
waits in the inbox. A browser, a device and a key of scope `upload` may upload; a key that only reads may not.

- **One request** (`POST /documents?vault_id=`, `multipart/form-data`, one or more files, at most ten): each file has its
  own result (`items`: `status` accepted or rejected, the `document`, an `error` with code and message, and `duplicate` when
  the caller already has this very file). If no file was taken the answer is the error of the first one (`415`, `413`, …)
  with all results in `items`. A request carries at most ten files of the size limit each; bigger things go in pieces. The
  body is written to the disk while it arrives; nothing large is held in memory. More than ten file parts (or more than 50
  parts of any kind) turn the whole request away at once (`413 too_many_files`, `400 too_many_parts`); a body that stops before
  its closing boundary is `400`. File names are read as the browser sent them (UTF-8, also `filename*=UTF-8''...`), so a name
  with `€`, an emoji or a narrow space is fine; a header that cannot be read spoils its own file only (`400` in its result).
- **In pieces, with resumption** (for apps and large files): `POST /uploads` with `{"filename", "size", "sha256",
  "vault_id"}`. When the caller already has a document with this checksum (one they may see; the trash does not count)
  the answer is `200 {"exists": true, "document": {...}}` and **nothing is sent**. Else `201` with the upload: `id`,
  `received` (0), `chunk_size` (the proposal), `max_piece` (64 MB), `expires_at`. Announcing the same file again (same
  checksum, size and vault) while an upload of it waits answers `200` with that upload and how far it is, so a person who
  closed the tab goes on where it stopped; `GET /uploads` lists the own uploads that wait. Then `PUT /uploads/{id}?offset=<n>` with
  the raw bytes, each piece at the offset where the last one ended (a gap or an overlap answers `409 offset_mismatch` with
  `received`); `GET /uploads/{id}` says how far the server is (to go on after a break; a piece still on its way counts once it is
  complete, and asking meanwhile leaves it alone; a second piece for the same upload at the same time is `409 upload_busy`); `POST /uploads/{id}/finish` checks
  the whole file against the SHA-256 and its kind (`422 checksum_mismatch` or `415`: the upload is thrown away) and makes
  the document; asking twice gives the same document (`created: false`). `DELETE /uploads/{id}` cancels. An upload ends 24
  hours after its last piece (`410 upload_expired`). An id belongs to the account that made it; for everybody else it
  does not exist (`404`).
- **Never across vaults**: whether the caller already has a file is decided only from the documents they may see. A
  file somebody else keeps where the caller cannot look is treated like a new one, in the answer, in the time it takes and in
  the errors.
- **Limits** (the operator, **Settings, Storage**): the size of a file (200 MB), the pages of a document (2000), the pixels
  of a picture (100 million), how many uploads in pieces and how many bytes of them an account may have open (10, 4 GB),
  the time the worker may take for one document (5 minutes) and its memory (2 GB, where the system allows a limit), and the
  size of the cache of page pictures (1 GB; the pictures used longest ago go first). The accounts take turns for the worker:
  one who uploads a thousand files does not hold up the others.
- **The worker**: a document is read in a process of its own, one document at a time, with a time limit (the process is
  killed with everything it started) and no access to the database or any secret. A PDF with a password, a damaged file, a
  PDF with too many pages or a picture with too many pixels leaves the document in the inbox with `process_error`
  (`encrypted`, `broken`, `too_many_pages`, `too_large`); a failure of the run itself (`timeout`, `failed`) is tried three
  times first. `POST /documents/{id}/retry` (edit) reads it again. A document that looks like one the caller already has
  carries `duplicate: {document_id, title, kind}` (`same`: the very same file, found by its SHA-256); it is shown only to
  somebody who may see that document, and the history never mentions it. `similar`: the same sheet scanned or photographed
  again, when the first pages look alike **and** the texts hold nearly the same words and numbers (a picture hash alone
  calls most follow-up invoices of one form a copy; the numbers tell them apart). See "Text and search".

### Inputs: the intake folder and the mailbox

- `GET /me/intake` (any way in): where the own documents can be sent: whether the mailbox is on, its address and the own
  `name+<account>@` form of it, the confirmed address of the account, the addresses forwarded from (`senders`: `id`,
  `address`, `confirmed`, `until` while the link waits), whether the intake folder is on and the own subfolder.
- `POST /me/mail-senders` `{"address"}` (a browser): mails a link to the address; it counts once the link was opened
  (`409 sender_exists`, `409 sender_is_account`, `409 mail_off` without a mail server, `429` after five in a while).
  `DELETE /me/mail-senders/{id}` removes one of the own. `GET`/`POST /mail-senders/confirm/{token}` (no sign-in): whom the
  link is for, and confirming it (once, within 24 hours; `404 sender_link_invalid`).
- `GET /documents/{id}/origin` (read): `source`, `unknown` (it went to the operator because nobody could be told from
  it), and for the owner and the managers of the vault `sender`, `subject`, `folder`, `file` and `at`.
- The operator's side, from a browser only: `GET`/`PUT /settings/intake` (`folder_on`, `folder_path`, `mail_on`,
  `mail_host`, `mail_port`, `mail_security` `tls|starttls|none`, `mail_user`, `mail_password` (never given back),
  `mail_address`, `mail_folder`, `mail_after` `read|move|delete`, `mail_private`, `mail_drop_unknown`,
  `mail_auth_server`: the server whose `Authentication-Results` count, only `dmarc=fail`; empty: the mailbox domain),
  `POST /settings/intake/mail/test` (`{"mails", "after"}`: how many are new, and what "afterwards" really does on this
  server; nothing is taken) and `POST /settings/intake/mail/fetch` (`{"mails", "files", "unknown", "passed", "more",
  "skipped", "flagged", "deferred", "dropped", "after"}`). The folder's `problem` is also `folder_readonly` when
  nexpaper may not move or remove files there; each person in `people` carries the same for their subfolder. Refusals: `folder_invalid`, `folder_forbidden`, `folder_missing`, `mailbox_off`,
  `mail_incomplete`, `mail_host_invalid`, `mail_plain_not_local`, `mail_address_refused`, `mail_address_private` (`422`
  or `409`); `mail_unreachable`, `mail_tls_failed`, `mail_login_failed`, `mail_folder_missing`, `mail_timeout`,
  `mail_protocol` (`502`); `mail_busy` (`409`) while a run is going on.

### Files and pictures of a document

Under `/documents/{id}/versions/{n}` (every version has addresses of its own, so a new version never shows an old picture
from a cache): `GET …/file` (the original, as it came), `GET …/archive` (the PDF made from a picture, later the searchable
copy; `404` while there is none), `GET …/preview` (the first page, 360 pixels, WebP), `GET …/pages/{page}?size=small|large`
(720 or 1600 pixels wide, WebP, page counted from 1). `GET /documents/{id}/versions` lists the versions, each with `path`:
where its original lies, from the folder for documents on (vault, year, sender, file), never more; who sees the
document only through a share gets it without the vault (year, sender, file), and a place that would lead out of the
folder is given as an empty `path`. A document of
more than 30 pages has its small pictures drawn in the background after it was read (the job `pages`, in batches of 20,
only while no document waits to be read), up to the operator's limit `prerender_max_pages` (**Settings, Storage**, 500;
0: none); the pages after it are drawn when somebody asks. The same rights
as reading the document; the pictures are `Cache-Control: private, no-cache` with an `ETag`, so a browser asks again and
is told "unchanged" (the tag is made with the server's secret, never from the checksum of the file). The preview and the small
pages of a document of up to 30 pages are drawn when it is read; any other picture is drawn when it is asked for, by a worker
process, and at most two at a time for one person or one link: more answer `503` with `Retry-After` at once instead of
waiting. A page of an absurd size (over 20,000 points a side) is `too_large`. A download carries `Content-Disposition` with
`filename` (ASCII) and `filename*=UTF-8''...`. A link (`GET /l/{token}/preview`, `GET /l/{token}/pages/{page}`) shows the pages of its one document
as long as it works, with or without downloading; the file itself only with `allow_download`.

## Text and search

### The text of a document

Reading a file has a second step: the text. A page that carries text of its own (30 letters and digits or more) keeps
it (read with PDFium); a page with less (a scan, a photo, a scan with a page number or a footer as text) is recognised by
Tesseract through ocrmypdf, in the worker process, with the languages the operator chose (`deu`, `eng`, `fra`, `nld`,
`pol`, `tur`, all in the image; nothing is loaded at run time), straightened and turned upright when that is on. The
result is a searchable copy beside the original (`GET …/archive`); the original and its checksum stay as they came. The
time limit of this step: per page ten times the average of the last documents (the operator's limit per ten pages
while nothing was read), at most `max_seconds` for a document (one hour from the start). When only the text could not
be read the document keeps its pages and preview and waits with `process_error` `ocr_timeout` or `ocr_failed` (`retry`
reads it again). The history says how many pages had text and how many were recognised, never the text. A database
from before the text gets a job `text` for every document that was read: it reads the text (history `text_read`) and
changes nothing else.

`GET /api/v1/documents/{id}/versions/{n}/text`: `{version, state, pages, ocr_pages, languages, long_document_pages}`,
`pages` the text of each page (the first first); `long_document_pages` the number of pages from which the text takes a
while (the inbox says so while the text is `pending`). `state`: `done`, `pending` (not read yet), `none` (an e-invoice that is XML only). The rights of
reading the document. Through a link: `GET /api/v1/l/{token}/text`, only when the link allows downloading (`403
download_not_allowed` else).

### `GET /api/v1/search`

What the caller may see (a browser, a device, a program with a read key), newest first (the document's date, else the
day it came in; then the id), with the total and a cursor. At most 120 searches a minute per person, whichever way they
come (`429 search_too_often` with `Retry-After`). An answer leaves at the next multiple of 25 ms after the search
began, and up to 25 ms later by chance, errors too: its time tells nothing about documents the caller cannot see.

- `q`: the search as typed (at most 500 characters and 12 terms; `422 query_too_long`, `too_many_terms`):
  - words: each must be found in the title, the sender, the text, the notes or the tags; a word of three letters and more
    anywhere in a word (`werke` finds `Stadtwerke`), a shorter one at the start of a word, one letter as a whole word.
    Case, accents and `ß`/`ss` do not count. `R-2026-17`, `12.30`, `e-mail` are their pieces in a row.
  - `"a phrase"`: these words in this order (an unclosed quote runs to the end).
  - `art:` / `kind:` (the kind's name or key begins so), `absender:` / `sender:` (the sender's name holds it), `tag:` (a tag
    begins so), `betrag:` / `amount:` with `>`, `<` or `=` (or none: equal), in euros, comma or point (`betrag:>1.234,56`;
    `422 invalid_amount`). Values with blanks in quotes: `absender:"am weiher"`.
  - `frist:` / `deadline:` with `offen`/`open`, `überfällig`/`overdue`, `erledigt`/`done`, or `<30` (open and due within
    that many days, overdue ones included; `422 invalid_deadline` for anything else): a deadline of the document, as
    "Deadlines" below works it out, in the caller's time zone.
  - `aufbewahren:abgelaufen` / `keep:expired`: the keeping time is over; `aufbewahren:läuft` / `keep:running`: it is
    not over yet (the server's day). Another word after `aufbewahren:` finds nothing.
  - Nothing else is syntax: FTS5's operators (`NEAR`, `OR`, `*`, `-`, `^`, brackets, `column:`) are characters, and words
    like any other.
- Filters as parameters: `vault_id`, `kind_id`, `owner_id`, `sender` and `tag` (a name, exactly), `date_from`, `date_to`,
  `status` (`processing`, `inbox`, `filed`; without it everything but the trash), `trash=true` (the trash instead, and only
  the caller's own documents in it), `via_share=true` (only what was shared with the caller one by one) or `false` (only
  what lies in the caller's vaults), `deadline` (`open`, `overdue`, `done`, or a number of days, as `frist:`),
  `keep=expired` (only filed documents whose keeping time is over, in the vaults where the caller may change things:
  what `GET /keeping` lists, with the other filters, the sort and the pages of the archive's table).
- `limit` (1 to 100, 50), `cursor` (the `next` of the page before; `422 invalid_cursor` for anything else).
- Numbered pages instead of the cursor (the archive's table): `page` (from 1, at most 100,000) and `sort`: `-date` (the
  usual), `date`, `title`, `-title`, `sender`, `-sender`, `amount`, `-amount`; a minus is the largest (the newest, Z)
  first. Documents without a sender or an amount come last either way; equal ones keep the newest first. `next` is
  empty then; a cursor with a page or another order is `422 cursor_and_page`. A page past the end is empty, with the
  total.

Answer: `{items, total, next, understood}`. Each item: `document` (as `GET /documents/{id}`), `title_marks` and
`sender_marks`, and `excerpt` `{text, marks, source}` (a piece of the text around the first place found, or of a note:
`source` `text` or `notes`). Marks are ranges `[start, end)` in **UTF-16 code units** of the text they belong to (as
JavaScript, Swift's NSString and Kotlin count), never HTML. `understood` is the search as it was read (folded words,
phrases, filters, amounts in cents).

The rights are in the index lookup (each entry carries the tokens of its vault and of the people it is shared with, and
the search asks only for the caller's) and again in the query that finds and counts: the number, the order and the
excerpts are the same whether or not documents the caller cannot see match too, and the index never reads their
entries. A search that takes longer than ten seconds in the database is stopped (`503 search_too_slow`); the excerpts of
one answer get one second, the rest show the start of their text.

### `GET /api/v1/search/overview`

How the documents the caller may see spread, for the start of the archive: `{total, senders, kinds, years, tags}`, each
list most first (`years` the newest first). `senders` and `tags` are `{name, count}`; a name in two vaults counts once.
`kinds` are `{kind, count}`, kinds of the same name together; `kind.id` as the search's `kind_id` finds them all.
`years` are `{year, count}` by the document's date; one without a date is only in `total`. Filters: `vault_id`,
`status`, `via_share`, as for the search. The same rights as the search, and its brake.

### Deadlines

A date of a document is a deadline when it is `due`, `contract_end` or `warranty_end` (`keep_until` is none). A contract
may carry its notice period and renewal: `PATCH /documents/{id}` takes in `dates` per entry `notice` (`{"n": 1 to 24,
"unit": "weeks" | "months"}`) and `renew_months` (1 to 120); left out they stay, `null` takes them away; on any other kind
`422 invalid_terms` naming the field. A page that may be behind sends single terms instead of the whole list:
`set_dates` (at most 4, `[{kind, date?, notice?, renew_months?}]`: only the kinds named, and of them only what is sent; a
left-out `date` keeps the day, a new term needs one) and `remove_dates` (`[kind]`); not together with `dates`
(`422 invalid_input`), a refused day names `set_dates[n]`. A contract that renewed by itself keeps its new end when the
end it renewed from comes back in `dates` (a page that is behind); another day is taken as meant, and it ends that
protection: the old end set later on takes effect. Each date in an answer carries `notice`, `renew_months`, `last_to_cancel` (the end
minus the period, to the day of the calendar: 31.12. minus 3 months is 30.09.), `done` (`{at, by}`), `renewed_from` and
the caller's own `snoozed_until`.

`GET /deadlines` lists the deadlines of the documents the caller may change (`edit` or `manage` in the vault, or a share
with `edit`; somebody who may only read gets none), in the inbox or filed, by the day to act:
`{today, soon_days, overdue, soon, later, done, counts, shared}`, each section `{total, items}` with at most `limit`
items (1 to 500, 200). Filters `vault_id`, `shared=true`, `what` (`pay`, `cancel`, `warranty`), `done=true` (else
`done` is empty). An item: `document_id`, `title`, `status`, `vault_id`, `via_share`, `sender`, `amount`, `currency`,
`kind`, `what` (`pay`, `cancel`, `ends`, `warranty`), `date` (the day to act), `days` (from today, below 0 overdue),
`end`, `notice`, `renew_months`, `renews_to`, `missed`, `done`, `snoozed_until`. A contract is due on its last day to
cancel; once that has passed, its end is the deadline (`what: ends`, `missed` the passed day, `renews_to` where it
moves without notice).

`POST /documents/{id}/dates/{kind}/done` marks it done for everybody, `DELETE` opens it again (both `edit`, a number for
`/changes` and a line in the history; `404 no_such_date`, `409 in_trash`). `PUT …/snooze` `{"days": 1 | 3 | 7}` puts it
off for the caller alone and answers `{until}`; `DELETE …/snooze` ends that (`edit`; `409 deadline_done`; no number, no
history). A key reads the list and changes nothing.

A contract that renews and that nobody cancelled moves its end on by itself once it has passed: to the first end that
is today or later, once per end (`renewed` in the history with `from` and `to`, a new number for `/changes`). The terms
are counted from the end a person last set (or the end when the renewal changed), so 30.01. plus a month each time is
28.02., 30.03., 30.04.

### Reminders

`GET /api/v1/me/reminders` says how the own account is reminded of deadlines: `rhythm` (`single`, one message per
deadline; `weekly`, a mail on Mondays; `both`), `push`, `mail`, `lead` (`{due, cancel, warranty}`, days ahead, of
`options`: 1, 3, 7, 14 for a bill, 7, 14, 30, 60 for the last day to cancel and the end of a warranty), `same_day`,
`muted` (vault ids), `muted_shared` (nothing about documents reached through a share alone), and what that needs:
`hour` and `time_zone` (8 o'clock in the person's zone), `push_devices`, `mail_address` (confirmed, else empty),
`mail_problem` (`no_server`, `no_address`, `unconfirmed` or null), `vaults` (edit or manage: `{id, name, icon, personal,
personal_of_other, muted, others}`), `read_only` (never reminded), `shared` (documents shared with `edit`), `may_go`
(how many documents the weekly mail would say may go, their keeping time is over, the muted vaults left out), `trashed`
(how many documents nexpaper put in the trash by itself in the last seven days, same vaults) and `deadlines` (whether
the caller uses deadlines at all: `profile.deadlines`, changed with `PUT /api/v1/me/preferences {"deadlines": false}`,
on from the start). With deadlines off nothing is reminded (no single reminder, no weekly mail), `POST …/test` is
`409 deadlines_off`, and `GET /deadlines` still answers (the switch is about the web app and the messages, not about
the data); the renewal of a contract does not depend on any person.
`PUT /api/v1/me/reminders` changes what it is sent and answers the same; switching mail or the weekly mail on without a
way to mail is `409 mail_unavailable`, a vault the caller may not change things in (or none) `422 bad_reminder`. A
field sent as `null` is left as it is; `lead` takes whole numbers from `options` (`true` is `422`). `muted` lists only
vaults the person is still reminded about: a mute whose right is gone is not listed, and a list that still names it is
saved without it. `time_zone` is the one the browser reported, else the server's (its IANA name when it can be found).
The first look after an update from a version without reminders marks the leads already open as reminded, without a
message; the day itself still comes.
`POST /api/v1/me/reminders/test` sends a test message on every way that is on (`{push: {sent, gone, failed}, mail,
by_push, by_mail}`; `409 reminders_no_way`). A browser or a device; a key is turned away.

A reminder names the kind of deadline, its day and the title of the document, never an amount, the text, notes or tags,
and opens the document. It goes from 8 o'clock in the person's zone, once per deadline and stage: ahead by the lead,
on the day itself (when chosen), and when a "later" ends; missed ones up to 2 days late. At most 20 a day per person,
the rest in one message. The weekly mail goes on Mondays when something comes up: the deadlines of the week, what is overdue, how many documents may go (see keeping, below) and how many nexpaper put in the trash by itself in the last seven days; a muted vault counts in none of these.

### Settings (the operator, in a browser)

`GET /api/v1/settings/ocr`, `PUT /api/v1/settings/ocr` `{languages, straighten, blank_pages, jobs, max_seconds}`: the
languages of the recognition (at least one, of `offered`), straightening, blank pages as separators (acted on by the page
tools), pages worked on at once (1 to 4), the longest one document may take (60 to 86,400 seconds; the card shows and
takes it in minutes). The answer also
says from how many pages a document waits long for its text (`long_document_pages`, 300). The answer also says whether this server has the recognition (`available`), the queue
(`running`, `waiting`) and the seconds per page of the last documents read.

## Pairing a device

A device (a phone, a later app, a script) gets a token of its own (`npd_…`) for an account. Only a signed-in browser with a
full session makes a code or allows an app, so the second factor was met there; the device never needs it. Every paired
device stands with the signed-in devices under **My account, Security** and in `GET /api/v1/devices` (`via`: `qr`,
`app:<client_id>` or `token`), and can be revoked one by one.

### With a code (QR code)

1. The person opens **My account, Devices and apps, Pair a device** in the browser: `POST /api/v1/devices/pairing` (browser
   only) makes a code of twelve letters and digits (`code`, e.g. `KRAF-T7Q2-K9XW`), valid for **5 minutes and once**; a new
   code ends the one before. The QR code holds `nexpaper://pair?server=<address>&code=<code>`; the page shows address and code
   for typing as well.
2. The device sends `POST /api/v1/devices/pair` with `{"code": "...", "name": "iPhone of Jule"}`: no sign-in, no tab header.
   The answer (`201`) has `token` (shown once), the `device` and the `account` it speaks for. Upper or lower case, spaces and
   dashes in the code do not matter.
3. The browser follows with `GET /api/v1/devices/pairing` (`state`: `open`, `used` with the `device`, `expired`, `none`).
   `POST /api/v1/devices/pairing/cancel` ends an open code.

A wrong, used or expired code is `400 pairing_code_invalid` and counts against the sender: five, and the address rests
a quarter of an hour on this route and on `/oauth/token` (a brake of their own: the sign-in of the address stays
open). A request a web page made (`Origin`, or `Sec-Fetch-Site` other than `none`) is refused with `403
origin_refused` before anything is counted: these routes are for devices and apps. Of two devices with the same code
at the same moment, one gets the token.

### With OAuth 2 and PKCE (apps)

For native apps (RFC 6749, RFC 7636, RFC 8252). The registered apps and where their code may go back to:

| `client_id` | `redirect_uri` |
|---|---|
| `nexpaper-mobile` | `nexpaper://oauth/callback` |
| `nexpaper-desktop` | `http://127.0.0.1:<port>/callback` or `http://[::1]:<port>/callback`, any port from 1024 |

1. The app makes a `code_verifier` (43 to 128 characters) and opens the browser at
   `<address>/oauth/authorize?response_type=code&client_id=…&redirect_uri=…&code_challenge=<BASE64URL(SHA-256(verifier))>&code_challenge_method=S256&state=…`
   (optionally `device_name=…`). The person signs in as always (password and second factor, or the provider; both come back to this
   page) and allows it.
   `S256` is required; `plain` and a missing challenge are refused. An unknown app or an address not in its list is never
   answered (the page says so and sends nothing anywhere); every other problem goes back as `error=` to the app. The
   addresses are compared as written (`HTTP://` is not `http://`).
2. The browser goes to `redirect_uri?code=…&state=…` (or `error=access_denied` when the person refuses). The code is valid
   for **2 minutes and once**.
3. The app sends `POST /api/v1/oauth/token` as `application/x-www-form-urlencoded` (JSON is taken too) with `grant_type=
   authorization_code`, `code`, `redirect_uri`, `client_id` and `code_verifier`. The answer is `{"access_token": "npd_…",
   "token_type": "Bearer", "device_id": …, "account": …}`. Errors are OAuth's: `{"error": "invalid_grant"}` (a wrong,
   used or expired code, another app or address, or a verifier that does not fit; any try uses the code up),
   `invalid_request`, `unsupported_grant_type`. A verifier that is not 43 to 128 characters of the allowed kind is
   refused before the code is looked at and leaves it as it was. Wrong codes count on the brake of pairing (above); a
   request with `Origin` is `403 invalid_request`.

There is no refresh token: the device token holds until it is revoked.

## The phone

- `GET /api/v1/quick`: what the quick upload of a phone shows: `target_vault_id` (where a file goes when none is named),
  `vaults` (the ones the caller may add to, own first, `mine`), `recent` (the caller's latest documents that are being read,
  wait in the inbox, or were filed in the last 24 hours, at most five) and the counts `inbox` and `processing`, all over what
  the caller may see. A key of scope `read` reaches it too.
- `POST /documents?source=camera` (or `share`), and `"source"` in `POST /uploads`: the document says it was photographed in
  the app or sent from another app.
- **Android**: nexpaper on the home screen stands in the share menu (`share_target` of the manifest). The service worker takes
  the files on the phone and the page uploads them through this API once the person taps "Upload"; leaving the page
  throws them away, and every page that starts clears all shared files but the ones it shows (those too after 15
  minutes). A form that reaches the server (`POST
  /teilen`) is never read, because it carries the cookie and no header of nexpaper's own.
- **iPhone**: a shortcut sends shared PDFs and pictures to `POST /api/v1/documents?source=share` with a key for
  uploading (scope `upload`). iOS takes
  only shortcuts signed by Apple, so nexpaper cannot ship the file; **My account, Devices and apps** explains how to build it
  in a few steps (see `docs/iphone-shortcut.md`), and the operator may share a finished one by an iCloud link
  (`PUT /api/v1/settings/shortcut`, read by everybody at `GET /api/v1/shortcut`).

## Taking documents over from Paperless-ngx

The operator, from a browser only (`403 browser_only` for a token): the token of Paperless sees everything there, and
the run puts documents into the vaults of other people.

- `GET`/`PUT`/`DELETE /settings/paperless`: the address (`url`, `/api/` at its end is dropped), the token (`token`, never
  given back: `token_set`; a new address without a new token forgets the old one) and `private` (Paperless may lie in
  the own network; off: only addresses on the internet). Link-local addresses and the metadata services of cloud
  machines never. `DELETE` removes the connection; what was taken stays. While a run is going on: `409
  paperless_running`.
- `POST /settings/paperless/check`: connects and looks, writes nothing: `version` and `api_version` of Paperless
  (Paperless-ngx 1.14 or newer, API version 3), how many `documents`, `tags`, `correspondents`, `document_types`,
  `custom_fields`, the types in use that become `new_kinds`, the `owners` (`paperless_id`, `name`, `documents`, the
  proposed `user_id`: the person of the same name, else the operator; `matched` says which), `users_hidden` (the token
  may not list users),
  `already` (documents of this Paperless that are here), `inbox_documents` (documents Paperless has in its inbox), and
  the `people` and `vaults` to choose from.
- `POST /settings/paperless/start` `{"where": "owner" | "vault", "vault_id", "sort": "paperless" | "inbox", "people":
  [{"paperless_id", "user_id"}]}` (`202`): the run is queued. `sort`: `paperless` (the default) lets what Paperless had
  in its inbox wait in the inbox and files the rest, `inbox` lets every document wait in the inbox. `owner`: each
  document into the own vault of its person; `vault`: all into a
  shared vault or the operator's own, where an owner who is not in that vault does not own the document (the operator
  does, else a manager of the vault) and gets it as a share to change. A second start while one runs is `409
  paperless_running` (two at once: one wins). `{"resume": true}` goes on with what was chosen at the last start (`409
  paperless_address_changed` when the address changed since). `POST /settings/paperless/stop`: it stops after the
  document it is at.
- The run (in `GET /settings/paperless`, `run`): `state` (`idle`, `queued`, `running`, `paused`, `done`, `failed` with
  `error`), `total`, `done` (here from this Paperless), `taken` and `skipped` in this run, `reasons` of the skipped ones.
  It goes on after a stop of the server, and a new start takes only what is not here yet: every document taken is
  written down with its Paperless number in the same transaction as the document. A skipped one is tried again at the
  next start, except `exists` (the person has the very file already). `GET /settings/paperless/skipped` lists them for
  the card: `items` (`paperless_id` and `reason`, the lowest numbers first, at most 50, never a title or any other word
  of Paperless), `total` and `more`. A document whose original Paperless no longer has (404) is taken as its searchable
  copy when that is a whole PDF (the history of the document says so), else it is skipped as `file_missing`.
  Reasons: `file_missing`, `too_large`,
  `unsupported_type`, `invalid_answer`, `gone`, `download_failed`, `download_timeout`, `empty_file`, `exists`,
  `unreachable`; each is in the log with the Paperless number, never with content.
- What comes over: the original and the searchable copy (the archive version, taken only when it is a PDF from its first
  to its last bytes; it is opened only in the worker process, like every file; an original nexpaper does not take, a
  Word file, say, comes as its searchable PDF), the text Paperless recognised (no new recognition; the search finds it),
  title, date, correspondent (sender), document type (kind; unknown ones become new kinds), tags (an inbox tag puts the
  document in the inbox, else it is filed), notes, custom fields and the archive serial number (one note), the people it
  was shared with (users and groups, the same people here as far as they can be told). Storage paths and workflows are
  left out. Every file is checked by its content like an upload, limited by the size limit, and needs room on the disk
  (`disk_full` stops the run).
- Every request to Paperless is resolved once and checked, follows no redirect (`502 paperless_redirected`: give the
  address Paperless answers at) and no `next` address of an answer, has a deadline (30 s for data, 15 minutes for a file,
  looked at after every piece) and a size limit (32 MB of data, also when packed); at most 100,000 documents. A
  certificate that is not trusted is `502 paperless_tls_failed` (a self-signed one: use http in the own network).

## Exports for the tax adviser

An export belongs to the person who asked for it; for everybody else it does not exist (`404`). Making an export,
fetching its ZIP, making a link to it and copying a link's address need a signed-in browser (`403 browser_only` for a
device token: an export holds a whole period, a lost phone must not hand it out); a device may list, look, delete and
revoke; a program with an API key reaches none of it.

- `GET /exports/preview` (`vault_ids` one or more, `date_from`, `date_to`, the filters of `GET /search`: `q`, `kind_id`,
  `owner_id`, `sender`, `tag`, `status`; `pdf`, `original`, `csv`, `xml`): how many `documents`, the `total` of their
  amounts (cents) and `totals` per currency, about how large (`size`: the originals, once per kind of file chosen), the
  first paths in the ZIP (`sample`), and `too_many`. Counted in the database; a search in it counts like a search.
- `POST /exports` `{date_from, date_to, vault_ids, q, kind_id, owner_id, sender, tag, status, content: {pdf, original,
  csv, xml}, link: {recipient, days}}` (`201`): queued and packed in the background; with `link` the link is made at
  once (`link.token`, `link.url`, shown once). Only documents the person may see when the ZIP is packed, of the vaults
  chosen among their own (`404` for another), not in the trash and not being read. At most 3 waiting (`409
  export_busy`) and 20 kept (`409 too_many_exports`); `422 export_period_invalid`, `export_empty_choice`,
  `export_no_vault`.
- `GET /exports`, `GET /exports/{id}`: `state` (`queued`, `packing`, `ready`, `failed` with `error`: `too_many_documents`
  (20,000), `too_large` (20 GB), `nothing_found`, `disk_full`), `documents`, `size`, `total`, what was asked for, `links`,
  `expires_at` (7 days after packing, longer while a link lasts). `GET /exports/{id}/file`: the ZIP (`409
  export_not_ready`; `409 export_outdated` once the person no longer sees every vault the documents came from).
  `DELETE /exports/{id}`: the ZIP and its links go. When it is ready the person gets a push and, with a mail server and a
  confirmed address, a mail.
- Inside: folders vault, year, sender; files `<date> <title>.pdf` (`(original)` for the original beside it), every part of
  a name made safe (no `..`, no separators), the same name twice gets `(2)`. `liste.csv` (`list.csv` in English): UTF-8
  with a byte order mark, `;` between fields, columns date, title, sender, kind, amount, currency, invoice number, vault,
  file; a text field that starts with `=`, `+`, `-`, `@`, a tab or a return gets a `'` before it. E-invoices that came as
  XML are in it as XML, and the XML taken out of a ZUGFeRD or Factur-X PDF beside the PDF; the list names the invoice
  number of every e-invoice.
- Links: `GET`/`POST /exports/{id}/links` (`{recipient, days}`, at most the operator's `link_max_days`, only while links
  are on), `POST /exports/{id}/links/{link}/address` (the address again, for its maker), `DELETE …/links/{link}`
  (revoked at once). `GET /x/{token}` (no sign-in) shows `shared_by`, `recipient`, `state` (`packing`, `ready`),
  `documents`, `size`, `until` and counts the opening once the ZIP is packed (not for the maker, not while it is being
  packed); `GET /x/{token}/file` hands out the ZIP. A link
  ends when revoked, at its date, with the operator's switch, with the export, when its maker is blocked or deleted,
  and as soon as its maker no longer sees every vault the documents in it came from; every dead or wrong token answers
  `404` alike and counts on the brake of links.

## Sorting in: proposals, rules, e-invoices

When a new document has been read, nexpaper fills in its fields and says per field where the proposal came from
(`suggest` on every document: `einvoice`, `rule`, `last_time`, `text`, `ai`, `default`, and `person` for a field a person
changed since). The first that knows a field wins in this order: the e-invoice, the rules, the same sender as last time
(a filed document of the same person with the same IBAN, VAT id, customer number or letterhead, among the documents the
person may see), the text (date, due date and amount, German and English forms), the AI. Proposals are only proposals:
the document waits in the inbox until it is filed. The history notes `proposed` with the fields and where they came
from, never their values; a move by a rule is `moved` with `by: "rule"`.

### Rules

- `GET /rules`: the rules of the vaults the caller manages (a person manages their own vault), in their order.
  `POST /rules` `{vault_id, when, then, on}` (`201`; `manage` in the vault), `PATCH /rules/{id}` `{when, then, on,
  position}`, `DELETE /rules/{id}`. A rule of a vault applies to the documents that arrive there. A device may use these.
- `GET`/`POST /settings/rules`, `PATCH`/`DELETE /settings/rules/{id}`: the operator's rules for the whole server, from a
  browser only. They apply in shared vaults and in the operator's own personal vault, never in the personal vault of
  another person (no kind, tag, sender, title or move there, and no hit counted).
- `when` (all must hold, 1 to 5): `{field: "sender", op: "is"|"contains", values: [...]}`, `{field: "text", op:
  "contains", values: [...]}` (one of up to 5 words), `{field: "kind", op: "is", value: <kind id>}`, `{field: "source",
  op: "is", value: "upload"|"camera"|"mail"|"folder"|"share"|"paperless"|"api"}`, `{field: "amount", op:
  "over"|"under", value: <cents>}`. Words are compared as plain text (case, accents and Unicode forms aside), never as
  a pattern; at most 100 characters each.
- `then` (1 to 8): `{field: "vault"|"kind", value: <id>}`, `{field: "tag"|"sender", value: <name>}`, `{field: "title",
  value: <pattern>}` with `{sender}`, `{kind}`, `{date}`, `{month}`, `{year}`, `{amount}` (also `{absender}`, `{art}`,
  `{datum}`, `{monat}`, `{jahr}`, `{betrag}`). A vault must be one the maker may add to; it is applied only where the
  person the document belongs to may add to it too and the maker sees the vault the document arrived in.
- The first rule that sets a field wins; tags add up. `hits` counts the documents a rule applied to that its maker may
  see. At most 100 rules per vault and 500 in all (`409 too_many_rules`); `422 invalid_rule` for anything else.
- `POST /documents/{id}/rule` `{kind_id, vault_id, tags}` ("Als Regel merken", `201`): a rule of the vault the document
  arrived in (`manage` there): when the sender is the document's, then what was sent. `422 rule_needs_sender` while the
  document has none.

### E-invoices

ZUGFeRD and Factur-X (the XML inside the PDF) and XRechnung in UBL or CII (an XML file) are read in the worker process:
the XML without entities, without a document type, without fetching anything, at most 1 MB, 40 levels deep, 10,000
attributes, 200 namespace declarations and 200,000 tags (the parser compares the attributes of an element with each other,
so tens of thousands of them would keep the one worker busy for minutes). The XML inside a PDF is read by a child process
of its own with a time limit of five seconds: a hostile XML costs only the e-invoice, never the PDF. A
document that carries one has `einvoice` (its format, e.g. `ZUGFeRD (EN 16931)`, `XRechnung (UBL)`); an XRechnung that
came as XML gets a readable PDF set from its data (`/archive`, with pages and text), the XML stays the original.

- `GET /documents/{id}/einvoice`: `version` (the one that carries it), `xml_only`, `format`, `number`, `issued`, `due`,
  `seller`, `seller_vat`, `buyer`, `buyer_ref`, `iban`, `currency`, `net`, `tax`, `gross`, `payable` (cents),
  `credit_note`, `lines` (`text`, `quantity`, `unit`, `price`, `total`). `404` when it carries none.
- `GET /documents/{id}/versions/{n}/einvoice`: the XML of that version (taken out of the PDF, or the file that came).
- The rights are those of reading the document; an API key that reads reaches both.

### The AI

With the operator's service set up (`/settings/ai`), the account allowed and the person's own switch on, a new document
is sent to the AI once, as a job of its own: the text of its first two pages (at most 6,000 characters) and the names of
the kinds the document can have (the server's and those of its vault), nothing else. `skip_personal` (`PUT /settings/ai`,
on from the start) keeps documents in personal vaults away from it; `GET /ai` tells it as `skip_personal`. `daily_limit`
(`PUT /settings/ai`, 200 from the start, 0 is no limit) is the most documents sent to the AI in one day (UTC) on the whole
server; `used_today` counts them. Once the limit is reached no request is made until the next day, the documents keep what
the rules and the text gave them (no field names the AI as its origin), and the log says so once a day. The answer is read as one JSON object and each value checked; a service
that fails or takes too long leaves the document as it was, and is not asked again.

## Page tools and versions

Every tool makes a **new version** of a document or new documents; the file as it came and every version before stay as
they are, with their checksums. Only a signed-in browser or a device may use them (a key never changes anything). The
caller needs `edit` on every document involved; splitting and joining also need `edit` in the vault itself (a share is
not enough to make documents in a vault or to take pages into it). A document still being read answers `409
not_ready`, one in the trash `409 in_trash`, an e-invoice that is XML only `422 no_pages`.

Each change names the version it was made for (`base_version`, the document's `current_version`). When the document
moved on in the meantime (a second person, a double click), the answer is `409 version_changed` with `current_version`
and nothing is made. While an uploaded version is being read, the tools answer `409 version_pending`. The work on the
PDF runs in a worker process (pikepdf) with the operator's limits of time, memory and pages; while the server runs as
many of them as it allows (two at a time, one per person) the answer is `503 busy` with `Retry-After`; a worker that
ended without an answer `503 try_again`. A file the worker cannot open answers `422 pdf_encrypted`, `pdf_broken`,
`pdf_too_many_pages` or `pdf_too_large`, one that takes too long `422 too_slow`. A file that is not the one its version
names (its checksum) stops the tool with `409 try_again`. A person makes at most 30 changes with the tools a minute
(`429 tools_too_often` with `Retry-After`). While a tool works on a document, the job that renames its files waits.

A new version keeps what its pages show (and the text of the recognition). What a page could do by itself does not come
along: actions of the page (`/AA`), files attached as annotations, actions of form fields (the form is not taken along:
its fields stay visible and cannot be filled), and every link other than to a web or mail address or a place in the
document (JavaScript, Launch, submitting a form). Things of the whole file (opening actions, scripts, attached files,
the form, metadata) are not taken along either; the embedded XML of an e-invoice stays with the version it came in.

- `POST /api/v1/documents/{id}/pages` with `{"base_version": n, "pages": [{"page": 3, "turn": 0}, {"page": 1, "turn":
  90}]}`: the pages that stay, in their new order, each turned by 0, 90, 180 or 270 degrees clockwise; a page left out is
  not in the new version. The text of each page goes along (nothing is read again), the pictures of the new version are
  drawn at once. The same order without turns changes nothing. Answer: the document.
- `POST /api/v1/documents/{id}/merge` with `{"base_version": n, "others": [{"id": 7, "base_version": 1}, ...]}`: the
  pages of the others come after the document's own, in this order (at most 19 others, together at most the operator's
  limit of pages, else `422 too_many_pages`). The document keeps its fields and gets the notes and tags of the others;
  the others go to the trash (restorable). The history of every document involved says so (`merged`, `merged_into`).
- `POST /api/v1/documents/{id}/split` with `{"base_version": n, "parts": [{"pages": [{"page": 1}], "title": "…"}, ...]}`:
  each part (2 to 100) becomes a new document in the inbox with the pages named, in that order; a page named in no part
  is dropped (the blank separators). The new documents take the title (with the number of the part, unless a title is
  given), sender, kind, date and tags; the document goes to the trash. Answer `201` with `items`.
- `GET /api/v1/documents/{id}/separators`: the blank pages of the current version and the split they propose: `checked`
  (looked for while the operator's switch **Blank pages as separators** was on), `blank_pages`, `parts`, `duplex` (every
  second page is blank: a stack scanned on both sides, where only a blank front cuts), `dismissed`, `suggested` (in the
  inbox, two parts or more, not dismissed). Every document carries `split_suggested` too. A key of scope `read` reads it.
  Documents in the inbox that were read without looking for blank pages (before this version, or while the switch was
  off) are looked at by a background job at the start and when the operator turns the switch on.
- `DELETE /api/v1/documents/{id}/separators`: keep it as one document; the proposal is not made again for this version
  nor for the versions made from it with the tools.

### Versions

- `GET /api/v1/documents/{id}/versions` lists them, newest first, with `origin` (`pages`, `merged`, `split`,
  `restored`, `uploaded`, or empty for the file the document came with), `from_n`, `state` (`ready`, `processing` while
  an uploaded version is read, `failed` with `error`), who and when.
- `POST /api/v1/documents/{id}/versions/{n}/restore` with `{"base_version": m}`: version `n` again as the current one,
  as a new version (its file, searchable copy, text and pictures); nothing is deleted. `409 already_current` for the
  current one.
- `POST /api/v1/documents/{id}/versions` (multipart, one file in `file`): a new version. The right is checked before the
  body is read. Answer `202` with the version as `processing`; the worker reads it like a new document, then it is the
  current one (`version_added` in the history). A file that cannot be read stays in the list as `failed` and the
  document keeps the version it had (`version_failed`). The file of the current version again answers `409 same_file`.
- `DELETE /api/v1/documents/{id}/versions/{n}`: puts away an uploaded version that could not be read (`edit`), file and
  all; any other version answers `409 not_failed`.
  In pieces: `POST /api/v1/uploads` with `document_id` instead of `vault_id` (a key for uploading cannot: `403`); the
  finished upload answers with the document.
- On the disk the current version has the plain name, the others `… (version n).pdf` (moved by the `rename` job after
  each change).

## Backups, storage and the check of the files

All of these are the operator's, from a browser (a device token or an API key is refused with `403 browser_only`).

### Backups

A backup is one ZIP with the database, the settings and the server's secret (`secret.key`), **without the documents**
(plain files in `/data/dokumente`, to be backed up with the server) **and without the search index** (it is the largest
part of the database and is built anew from the text after a restore). The database is copied with SQLite's backup API
while nexpaper runs, never as a file.

- `GET /api/v1/backups` lists them, newest first: `name`, `size`, `created`, `kind` (`manual`, `scheduled`, `update`),
  `note`, `accounts`, `documents`, `version`, `uploaded`. Only `scheduled` and `update` copies are pruned (the setting
  `backup_keep`); one made by hand or uploaded stays until it is deleted.
- `POST /api/v1/backups` `{"note": ""}` makes one now. Answer `201` `{name}`.
- `POST /api/v1/backups/upload` (the body is the ZIP, the password in the header `X-Nexpaper-Password` as base64 of its
  UTF-8): brings an archive from elsewhere into the list. It is only listed; nothing is restored by it. `400
  backup_invalid` when it is not an archive of nexpaper's, or when its manifest is larger than 64 KB (so is a listed
  archive whose manifest is: it is left out of the list).
- `POST /api/v1/backups/{name}/check` is the trial run: the start of the server, rehearsed on a scratch copy of the
  database in the archive (the steps that bring it up to today's schema, the end of the stored sign-ins, every table
  and column nexpaper needs; triggers, views and virtual tables that nexpaper does not make are refused), and whether the archive is
  whole (`400 backup_damaged` when it cannot be read to its end, or when its database is not the one the manifest names
  by size and sha256). The answer: whether the archive can be restored (`usable`,
  `database_ok`, `schema`, `too_new` for one made by a newer nexpaper), what the restore would bring back to life
  (`revived_devices`, `revived_keys`, `revived_links`: ones that were valid in the backup and are revoked, blocked or
  removed on this server now; a restore signs everybody out, but it does not remember what was ended since), and what
  it would do to the documents:
  `documents` (what the archive knows), `missing_documents` (documents with a file that is not on the disk),
  `changed_documents` (a file with another checksum; files are read for at most 20 seconds, also inside one large file,
  `not_compared` counts the ones only looked for or given up on), `newer_documents` (documents of today that the archive does not know; they would go, their
  files stay in the folder) and `rebuilds_index`. Nothing is changed.
- `POST /api/v1/backups/{name}/restore` `{"password": "..."}`: checks again, keeps the current state as a backup
  (`update`), lays the archive out and restarts. The password of the operator is asked again. After the start the search
  is empty and a background job fills it; the files check runs again. If the swap fails at the start, the staged files go
  to `backups/restore-failed/`, the log and the operators say so, and the server starts with the database it had.
- `POST /api/v1/backups/{name}/download` `{"password": "..."}` and `DELETE /api/v1/backups/{name}` (also with the password
  in the body) ask for the password again as well.

### Storage and the check of the files

- `GET /api/v1/storage`: `database` (`bytes`, `index_bytes` of it, `where`), `documents` (`bytes`, `files`,
  `originals_bytes`, `complete`, `where`), `cache`, `exports`, `backups` (each `bytes`, `files`, `complete`),
  `free_bytes`, `total_bytes`, `data.where` and `files` (the state of the check, below). `where` is `{kind, fstype,
  network}`: `network` is true for NFS, SMB/CIFS and the like (on Linux read from the mount table, on Windows from the
  drive type); SQLite loses data there, so the card and the log at the start warn about it. A folder is counted at most
  every five minutes and for at most 15 seconds (`complete: false` says the number is a lower bound).
- `POST /api/v1/storage/files/check`: starts the check of the files now (`202`, `started` false when one is running).
  The check also runs once a week by itself.
- `POST /api/v1/storage/files/documents/{id}/check`: looks at the files of one document again, now, and answers
  `{"files_state": ""}` (all well), `"missing"` or `"changed"`; `404` for a document that does not exist, `409 try_again`
  while a page tool works on its files.

The check reads every original and every searchable copy and compares its SHA-256 with the one noted when the file was
put in place (for a searchable copy made before the checksum was noted, the first check notes it). It works in small
portions with pauses, so the disk is not busy all the time, and keeps its place in the database. `files` in the answer
above: `running`, `documents_done` and `documents_total` while it runs, `last_finished_at`, `last_files`,
`last_documents`, `last_problems`, `last_skipped` (documents that were being worked on and come next time),
`flagged_documents` and `every_days`.

A document with a problem carries `files_state` in every answer that shows the document: `missing` (a file is gone, or
its path does not lead into the document folder) or `changed` (a checksum does not match); empty when all is well. The
history of the document gets the lines `files_missing`, `files_changed` and `files_whole`, and the operators get a push
and, with a mail server, a mail when a check finds something new. A document whose file is back loses its sign at the
next check, or at once when the operator asks for that one document, when a new version of it has been read, when a
version that could not be read is put away, or when it comes back from the trash.

### API keys made in the interface

The interface proposes a lifetime of a year for a new key that reads (30 or 90 days, or no end, can be chosen), because a
key that never runs out is the one nobody remembers when it leaks. For a key that only uploads (the iPhone shortcut makes
one, so does a scanner) it proposes no end: such a key can only put documents into its owner's inbox, and a shortcut that
stops working after a year is the worse surprise; 30, 90 or 365 days stay a choice. The API itself takes `days` 30, 90 or
365, or leaves it out for a key without an end.

## Keeping documents

A kind can say how many years its documents are kept (`keep_years` on a kind, empty: no keeping time; the kinds that
come with nexpaper have none). A document of such a kind gets the term `keep_until`: the end of the year of its date plus
that many years (an invoice of 14.03.2026 kept 10 years: 31.12.2036; without a date, the year it came in). It is worked
out again when the document is filed or read, and when its kind, its date or its vault changes. A kind of a vault that
is made in another vault for a document that moves there takes the keeping time along; a kind of that name the other
vault has already keeps its own.

In the answers `keep_until` carries `manual` (only this term does): `false` worked out from the kind, `true` set by a
person, which stays whatever happens to the kind or the date. A `keep_until` sent with `PATCH /documents/{id}` is set by
hand; sending the date the document already has leaves it as it was made, `"manual": false` in the term says "from the
kind" outright, and leaving `keep_until` out of `dates` works it out from the kind again. Deleting a kind, or merging
it into one without a keeping time, leaves the dates where they are, as set by hand. Nothing is ever deleted because
its time is over, unless a kind has the switch below.

- `POST /kinds/{id}/keeping/preview` `{"years"}` (1 to 30, or `null` for taking the time away): what the question
  before setting it says, counted over the documents the caller may see (not in the trash, not being read):
  `{"documents", "by_hand", "expired"}` (`expired` is 0 for `null`). Changes nothing.
- `PUT /kinds/{id}/keeping` `{"years", "existing"}`: sets the keeping time (`null` takes it away). With `existing` the
  documents of the kind already there are worked out again (taken away: a worked-out `keep_until` goes); without it
  they are left alone (`keep_new_only` on the kind; taken away: a worked-out `keep_until` stays, as set by hand).
  Dates set by hand always stay. Every document of the kind is changed, also in vaults the caller does not see, but the
  answer `{"kind", "changed", "queued"}` counts only documents the caller may see: more than 200 of them are done in
  the background (`queued: true`, `changed` 0; one job, which does what was decided last when it runs). Each document
  whose term changed gets a new number for `GET /changes` and a line in its history (`fields: ["keep_until"]`, `by:
  catalog`). A kind of the whole server is the operator's, in a browser; a kind of a vault needs `manage` there.
- `POST /kinds/{id}/auto-trash/preview` (no body): `{"kind", "due"}`, `due` being the filed documents of the kind that
  the caller may see and whose keeping time is over now and which the switch below would put in the trash at its next
  run (one the task took once and a person restored is not counted: it is left alone). Changes nothing. Same rights
  as setting the time.
- `POST /kinds/{id}/merge/preview` `{"into"}`: what merging the kind into another (`POST /kinds/{id}/merge`) would do
  to the switch below: `{"auto_trash", "expired"}`, `auto_trash` being whether the target has the switch on and
  `expired` how many filed documents of the kind that the caller may see would be over their keeping time under the
  target (dates set by hand stay, the others are worked out again from the target's years) and would go to the trash at
  the next run (0 without the switch). Same checks and rights as the merge itself. Changes nothing.
- `PUT /kinds/{id}/auto-trash` `{"enabled"}`: the switch "expired documents into the trash by themselves"
  (`auto_trash` on the kind, in `GET /kinds`, `GET /order/kinds` and in every document's `kind`). Off from the start,
  and only for a kind with a keeping time (`409 no_keeping_time`); taking the time away switches it off. Same rights as
  setting the time: the operator in a browser for a kind of the server, `manage` for a kind of a vault. Switching it on
  changes nothing at once. Once a day, at night (3 o'clock, the server's time; a night the server was off for is made up
  at the next start, and the very first start only notes the night) nexpaper puts the filed documents of such a kind whose
  `keep_until` has passed in the trash (30 days to get them back): at most 500 a day, the rest the next day, each
  document once (one that was restored stays; the history line `auto_trashed` with `keep_until` in its `detail` and no
  person is the mark), with a new number for `GET /changes`. Nothing is deleted for good. A kind made in another vault
  for a document that moves there does not take the switch along.
- `GET /keeping` (`vault_id`, `limit` at most 500, `offset`): the filed documents whose `keep_until` is before today (the
  caller's time zone), in the vaults where the caller may change things (`edit` or `manage`; documents only shared with
  them are not looked at), the ones over longest first, then by date and id: `{"items" (as `GET /documents/{id}`),
  "total", "auto_trashed"}`; `auto_trashed` is how many documents nexpaper put in the trash by itself in the last 30
  days and that are still there, in those vaults. Every document in an answer has `auto_trash_due` (the task will put
  it in the trash, or will once it is filed from the inbox: its kind has the switch on, its `keep_until` is over for
  the caller, and it was not taken before) and `auto_trashed` (it is in the trash because the task put it there).
- `POST /documents/trash` `{"ids"}` (at most 500): many documents into the trash for 30 days, each checked as
  `DELETE /documents/{id}` would be: `{"trashed": [ids], "failed": [{"id", "code"}]}`; one the caller may not see fails
  as `not_found`.
- `GET /order/kinds` gives `keep_years` and `keep_new_only` with each kind; the CSV of an export has a column
  "Aufbewahren bis" / "Keep until".
