# Security

## Reporting a vulnerability

Please do not open a public issue for a security problem. Report it privately through GitHub instead:
**Security, Report a vulnerability** on this repository (private vulnerability reporting). Say what you found, how to
reproduce it, and which version you ran.

You get an answer within a week. A fix goes out as a new release; the release notes name the problem once the fix is
available, and you are thanked there unless you would rather not be.

## Supported versions

Only the newest release gets security fixes. Updating is `docker compose pull && docker compose up -d`; see
[Updating](README.md#updating).

## Reaching nexpaper from outside

nexpaper is best used in your own network, and from on the way through a VPN. If you open it to the internet anyway,
the README has a checklist: [Reaching nexpaper from outside](README.md#reaching-nexpaper-from-outside).

## What the operator can reach

A personal vault is shown to nobody else, the operator included. One way leads past that, on purpose and in the open:
when the operator deletes an account, they choose where the documents of its personal vault go and may choose
themselves or a vault they are in; the dialog says so, and the history of every document notes the takeover and who
did it.

A backup holds the server's secret (`secret.key`) together with the database: with both, the mail and AI credentials,
the addresses of open links and the PDF passwords people chose to keep can be read. Keep backups as protected as the
data folder.

A link to the outside may show further documents beside its own, but only those chosen one by one when it was made,
among the documents that go with it and that its maker may share by a link of their own; nothing comes in later by
itself, and every document shown this way says so on its own page, where whoever may see its links can take it out.

A link shows the document as it is now; whoever may change it sees that it is open and is asked before changing its
pages (without learning to whom or until when, which only whoever may share it sees).

## Inputs: the intake folder and the mailbox

**The mailbox is open to anybody who knows its address.** Whoever sends a mail can write any address into `From`, and
anybody who knows the address of the mailbox can write to `paper+<account>@` (account names are short and can be
guessed). nexpaper uses both only to choose whose inbox a mail goes to: nothing from the mailbox is filed, shared or sent
on by itself, every attachment waits in an inbox, and the document remembers where it came from (the sender's address
and the subject, shown to its owner and the managers of its vault). An address counts for a person only after the link
mailed to it was opened; an address that two people confirmed belongs to nobody (the mail goes to the operator, marked
unknown). When the trusted server wrote an `Authentication-Results` header and it says `dmarc=fail`, the mail counts
as unknown. The trusted server is the name the operator enters (for a hosted mailbox the provider's, such as
`mx.google.com`), else the domain of the mailbox's address, each with the names below it. Headers of any other server are
ignored, since a sender can write them; a server that lets forged headers of its own name through is not caught, and
without the right name entered the check does nothing. `spf=fail` alone does not count: a forwarded mail fails SPF and
still passes DMARC.
A stranger can therefore still put files into an inbox, and fill disk and the reading queue up to the amounts nexpaper
allows: 250 MB of mail per run (every 5 minutes), 500 MB of documents per person and 2 GB on the whole server per day;
the rest waits for the next day. The operator can have mails nobody can be told from left in the mailbox instead of the
operator's inbox.

**A mail is taken apart in a process of its own**, at the lowest priority, with a time limit (20 seconds) and, where
the system allows it, a limit of its computing time and its memory: some mails cost far more to take apart than their size (a header of thousands of quotes, a file name of
thousands of encoded words). Before that, a look at its bytes refuses what no mail program writes (an address or MIME
header over 8 KB, any other header over 64 KB, more than 500 header lines, more than 100 parts, parameters or addresses,
a file name over 1 KB). Such a mail is
skipped for good, said in the log and in the settings, and left in the mailbox. Where fetching stands is written before a
mail is taken apart, so a mail that brings the server down is tried three times at most, then flagged and left.

"Afterwards" (read, moved, deleted) happens only to a mail whose every part that can be a document was taken. A mail with
a part over the limits (size, number of parts) stays where it is and is flagged; a part that failed is tried again. A
mail is deleted only where the server can delete that one mail (UIDPLUS); elsewhere it is moved or marked read, so that
mails others marked deleted are never removed with it. What was taken is known by the mailbox (server, account, folder),
UIDVALIDITY, UID and part, so another folder with the same numbers is never taken for the first one.

The mailbox password is sealed with the server's secret, never shown again, and forgotten when the server or the port
changes without a new one, so a stolen operator session cannot send it to a server of its own. The server's address is
checked like every way out: resolved once and connected to exactly as checked, never link-local or a cloud metadata
address, a server in the own network only when the operator allowed it, without TLS only on the same machine. Every
socket is under the deadline of the run from its first byte (TLS handshake and greeting included), every read has a
time limit, and an answer may hold at most 10,000 lines and a mail's size: a hostile or hijacked mail server can hold a
run for its deadline, not longer, and cannot fill the memory. A mail over 50 MB is left alone and flagged.

The intake folder may not be a place whose files matter: not the data folder or a folder above it, nothing inside it but
`eingang`, not the program, not a system folder, no path with `..`. Links, junctions and hard links are not taken
(a hard link is set aside), nothing outside the folder is opened, and a file that is not taken is moved aside, never
deleted. A file is removed only when it is still the one that was read (size, time and file number): a scanner that
writes the same name again keeps its new file. A folder or a person's subfolder where nexpaper may only read is not
taken from at all (a file it could not remove would come in again); the settings say so. When the container fixes the owners of `/data` at its
start, a folder mounted below it keeps the owners of its files.

## Paperless import and exports

The token of Paperless is sealed with the server's secret, never shown again, and forgotten when the address changes
without a new one; only the operator, from a browser, reaches the import. Paperless is treated as a stranger: its address
is checked like every way out (resolved once, never link-local or a cloud metadata address, the own network only when
the operator allowed it), no redirect and no `next` address of an answer is followed, every request has a deadline and
a size limit, every value is checked for its type and cut to what nexpaper keeps, and every original goes through the
same check of its kind and size as an upload. The searchable copy Paperless made is taken only when it is a PDF from its
first to its last bytes; like every file it is opened only in the worker process, with its limits.

An export holds only documents the person may see at the moment it is packed (the rights are in the query), and its
names cannot leave the ZIP. The documents that go with them come along only on request, and only those the person sees
in a vault of theirs. A text in its list that a spreadsheet would take for a formula is defused. A link to an
export ends when revoked, at its date, with the operator's switch for links, with the export, when its maker is blocked,
and as soon as its maker no longer sees every vault the documents in it came from. A ZIP is removed seven days after it
was packed, or when the last link to it ends, whichever comes later.

## Sorting in: rules, e-invoices, the AI

The words of a rule are compared as plain text, never as a regular expression, and a rule is limited in its size and
number. A rule moves a document only into a vault its person may add to, and only out of a vault its maker sees. **A rule
for the whole server (the operator's) never touches a document in the personal vault of somebody else**: it sets no kind,
no tag, no sender and no title there and moves nothing, and its counter does not count what it did not touch. A rule
counts a hit only for a document its maker may see, and a rule of a vault sets only kinds of the server and of that
vault. "As last time" looks only at documents the person may see (the rights are in the query); a known property: when a
person uploads into a shared vault a document with the same IBAN, VAT id, customer number or letterhead as one of their
private documents, the sender and tags of that private document are proposed for the new one, which the other members of
the shared vault then see in the inbox and in the sender list of that vault. Nothing reaches a person who is not
a member. The kinds of a vault belong to that vault: a name used in another vault answers like a name nobody uses, and
a kind of another vault is refused with the answer for a kind that does not exist.
E-invoices are read in the worker process; their XML is parsed without entities, document types or network, with limits
on size (1 MB), depth, attributes, namespace declarations and tags (the parser takes minutes on tens of thousands of
attributes on one element; the marks are counted in the bytes before it runs), and a document type in any encoding is
refused. The XML inside a PDF is read by a child process with a time limit, so a hostile one costs only the e-invoice.
Patterns that read texts from outside (the customer number, amounts, the fence around an AI answer) are written so that a
long run of one character costs no more than any other text; tests hold each to a time limit. What goes to the AI is the text of the
first two pages and the list of kinds the document can have, never a picture, a name of an account or a vault; personal
vaults are left out unless the operator lets them in, and every person can switch the AI off. The operator sets a limit
of documents per day for the whole server (200 from the start), because a large delivery would otherwise be sent one by
one to a service that is paid for by the request; once it is reached no request is made until the next day. An answer
that fails in any way, however unexpected, ends the job: it is never asked again. The AI's answer is only a proposal, checked
field by field, and the document's text is marked off from the instructions with a random word.

## Backups, the check of the files and where the data lies

**A backup holds the database and `secret.key`, not the documents and not the search index.** It is made with SQLite's
backup API (a file copy of a database in WAL mode would miss what is not yet in the main file). Downloading, deleting,
uploading and restoring one ask for the operator's password again, from a browser only: a stolen session or a device
token can neither carry a backup away nor lay one out. An archive that is uploaded or restored is read with its limits:
it may hold nothing but its three parts (a path, a link or another name makes it unusable); the manifest is read up to
64 KB and no further; the bytes are counted while they are unpacked and never taken from what the archive says about
itself; the database must be the one the manifest names by size and sha256 (a flipped byte is "damaged", not an error);
and a path in a foreign database that leads out of the document folder counts as a missing file and is never read.

**How the trial run opens the database of an archive.** It never opens it in place and never with the server's own
connection. The database is unpacked into a hidden scratch file in the backups folder (`.check-<process>-<time>.db`,
removed when the run ends, also after an error) and looked at in this order. (1) `PRAGMA integrity_check` and
`user_version` through a plain `sqlite3` connection; no extension can be loaded and nothing is attached. (2) A read only
connection (`mode=ro`) lists the triggers, views and virtual tables in `sqlite_master`; any that nexpaper does not make
itself ends the run, **before anything is written**, because a trigger would fire at every write of the app after a
restore, a view may name anything and a virtual table has a module of SQLite behind it. One that carries the name of one
of ours counts only if its statement is ours, too (a trigger named like the one that keeps the search index, with another
body, is the first thing somebody would try). Plain tables of data nexpaper does not know are left alone: nothing reads
them. (3) Only then is the scratch copy written to, as the start does it: the steps that bring it to today's
schema, the end of the stored sign-ins, and a look (read only again) that every table and column nexpaper needs is there. Any error in any of it, or a database without tables, makes the archive
"not usable", logs the kind of the error (never its text, which could quote the database) and changes nothing. (4) Last,
read only, the paths of the documents are looked up in the document folder through the same check that every other read
of a document file uses. The scratch copy is the only file that is changed. Because the real start does the same steps,
an archive that passes cannot stop the next start.

**A restore that fails.** The swap at the start is made on temporary files beside the live ones and ends in `os.replace`;
the live database and `secret.key` are not touched before that. If anything fails, the staged files move to
`backups/restore-failed/` (with a note of when and what kind of error), the log and the operators (push, and a mail with
a mail server) say so, and the server starts with the database it had. The way back is also kept: a restore makes a copy
of the state before it first.

**What a restore brings back.** It ends every session, but a backup does not know what was ended after it was made:
devices, API keys and links that were revoked, blocked or removed since are valid again after it. The trial run counts
them from the live database (`revived_devices`, `revived_keys`, `revived_links`, and `revived_link_documents` for
further documents a link would show again) and says so in the dialog; after a
restore, check the lists of devices and keys and withdraw what should stay gone. A password changed since is the old one
again, too.

**The check of the files** (once a week and on a click) reads each file, compares its checksum with the one noted and
marks a document whose file is gone or no longer matches. It is gentle (portions with pauses), skips a document that the
page tools or the renaming of files work on right now, reads nothing outside `dokumente/`, and writes no contents into
the log or a notice, only numbers. It finds a disk fault or a restored folder that lags behind; it is **not** a defence
against somebody who can write the document folder and the database: that person can change both.

**SQLite on a network share.** NFS and SMB do not keep SQLite's promises, and a database there can lose data without a
word. nexpaper looks where the data folder lies (the mount table on Linux, the drive type on Windows), says so on the
storage card and in the log at the start, and does not stop: the decision stays with the operator. The documents may
lie on a share.

## Files that come in

The kind of a file is read from its content, never from its name or the type a browser claims; a program called
`.pdf`, a web page called `.png` and an SVG are turned away, and XML only as an e-invoice without a document type
definition. Size, pages, pixels and open uploads are limited by the operator (Settings, Storage).

A file is read in a process of its own, one document at a time: it gets the paths and the limits, no database handle and
no secret in its environment or its code, runs in an empty folder of its own, is stopped at a time limit (with everything
it started) and, where the system allows it, is held to a memory limit. A damaged, password-protected or hostile PDF or
picture can therefore end that one run, and a flaw in the reader gets no key handed to it. It is **not a sandbox**: the
worker runs as the same system user as the server, so a reader that was taken over could still read what that user
reads (the data folder, `secret.key` included). The container drops every capability and runs without root; a separate
user for the worker is a hardening step that is still open. The pictures of pages are drawn by the same worker, never
inside the server process.

Whether a person already has a file is decided only from the documents they may see; nothing in an answer, its timing
or an error tells them that somebody else keeps the same file in a vault they cannot look into.


## Protected PDFs and kept PDF passwords

A PDF that needs a password to be opened waits in the inbox. Whoever may change the document types the password at its
card. It goes in the body of that one request to the worker process, on its standard input: never as an argument of the
process, never in its environment, never in a file, never in the table of jobs (the run is made within the request and
its time limit). The worker answers only whether it opened the PDF and with which of the passwords it was given, by
number. A wrong password changes nothing; every try counts against a brake of 5 per document and person and 20 per
person in an hour (somebody else's tries never lock the owner out). The brake keeps the server from being used to guess;
it does not make a weak password strong: whoever may read the document can download the protected original and guess
at it elsewhere. A file that claims to be encrypted but opens with nothing is refused as damaged. No log line, answer,
error message or history line names a password.

**The PDF opened lies unencrypted on the disk.** That is the point: it is the searchable copy beside the original
(`... (searchable).pdf`), which the view, the search, the page tools, links and exports take. The original stays as it
came, password and checksum and all ("Download: original" says so). Protecting the disk is the operator's business, as
for every other document; the interface says it in one sentence when a PDF is opened. A PDF that only locks printing or
changing (it opens without a password) is read the same way without asking.

**Keeping a password** happens only when the person ticks "Remember for future documents" and gives it a name. It is
stored sealed with the server's secret (AES-256-GCM with a key from `secret.key`, bound to the person), at most 10 per
person, and never shown again, not even to that person: the list under My account, Upload shows names and dates, and an
entry can be renamed or deleted. **Whose kept passwords are tried** is decided in one place, by the file, never by
the owner of the document: a file a person uploaded while signed in (browser, phone, a device or a key), as a document
or as a new version, gets that person's passwords; a file from the intake folder or the mailbox (the plus address and
unknown senders too) gets the passwords of the person it was given to, and only while it stands in that person's own
vault, where nobody else sees the outcome; anything else (the Paperless import, a version made by the page tools) gets
none. So nobody can find out by uploading a file which passwords somebody else keeps. The worker gets them for one more
run, and only when the first run said the PDF needs a password; the operator sees, uses and counts nobody's entries. The history then says that a kept password opened it, never which one. Deleting an
account deletes its entries. A new `secret.key` makes them unreadable (the list says so); **a backup together with
`secret.key` opens them**, so keep backups protected. While the server runs, a kept password is unsealed in its memory
for the run that needs it and passed to the worker on its standard input; Python gives no way to wipe a string, so it
stays in the memory of the two processes until it is overwritten.

## Reminders of deadlines

A reminder (push, mail, the weekly mail) names the kind of a deadline, its day and **the title of the document**
("Cancel by Wed, Sep 30: Mobile contract"). This is the one place where something a person stored leaves the server in a
message: the push service of the browser (Google, Mozilla, Apple, Microsoft) carries it encrypted, but the lock screen
of a phone shows it, and a mail lies in the mailbox of the person. Never an amount, the text, notes or tags. Whoever does
not want titles on a lock screen switches the push off under My account, Reminders (the deadlines page still shows
everything), or mutes a vault.

Only people who may change a document are reminded of it (edit or manage in its vault, or a share with edit); a reader
is not. The rights and the muted vaults are part of the query that runs right before a message goes out, so nobody is
told about a document they lost meanwhile. Each reminder is written down before it is sent and goes out once, also when
two runs meet; at most 20 per person and day, the rest in one message. The update that brings reminders sends none for deadlines that were there before: the first look marks the
open leads as reminded.

Somebody who does not use deadlines switches them off for themselves (My account, Reminders): then nothing is reminded
and no weekly mail is sent to them, and the web app shows no deadlines. The dates stay on the documents.

## Expired documents into the trash by themselves

A kind with a keeping time can be set (by whoever sets the time: the operator for the kinds of the server, a manager for
those of a vault) to have its expired documents put in the trash once a day, at night. It is off for every kind from the start, it
asks first and says how many documents it would affect at once. It only ever uses the trash of every other deletion (30
days, then the files go): it deletes nothing for good by itself, takes at most 500 documents a day, takes a document
only once (one that was restored stays), and leaves a line in the history of each document and in the weekly mail of the
people who may change it. A kind that a document brings along to another vault does not bring the switch with it.
