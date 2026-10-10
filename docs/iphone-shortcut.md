# The iPhone shortcut "Nach nexpaper"

On the iPhone, Safari puts no web app into the share menu of other apps. A shortcut in Apple's app Shortcuts does: once
it is there, every app (Mail, Files, a banking app, Photos) can share PDFs and pictures to nexpaper, and they land in
the inbox.

## Why there is no file to download

iOS imports only shortcuts that Apple signed. Signing needs a Mac (`shortcuts sign`, which asks Apple's servers) or
an iCloud link made on a device signed in with an Apple account. An unsigned `.shortcut` file is refused, and a
`shortcuts://import-shortcut` link takes only iCloud links. So nexpaper cannot ship a ready file, and a file made for
one server would not fit another anyway. There are two ways instead:

- **Build it** in a few steps (below). My account, Devices and apps shows the address and the key to copy.
- **The operator shares a finished one** by an iCloud link (Settings, API, "Shortcut for the iPhone"). My account then
  shows "Load the shortcut" to everybody; the shortcut asks each person for their own address and key when it is added.

## The key

The shortcut uses an **API key that only uploads** (`npk_…`, scope `upload`): it can bring files in and nothing else
(no reading, no changing, at most 120 requests a minute and 50 files an hour). API keys are off until the operator
switches them on (Settings, API); until then the card says so and makes no key. The key stands with the API keys under
My account, Devices and apps, and deleting it there stops the shortcut at once.

> **Never put your own key into a shortcut you share.** Whoever has the shortcut has the key and can upload into your
> account. A shortcut meant for others asks for the address and the key with **Import Questions**, and holds only
> placeholders.

## Build it

1. In nexpaper on the iPhone: **My account, Devices and apps, "Key for the shortcut"**. It makes a key for uploading
   named "iPhone shortcut" and shows two values to copy: the address,
   `https://<your nexpaper>/api/v1/documents?source=share`, and the header value, `Bearer npk_…`. They are shown once.
2. In **Shortcuts**, make a new shortcut called **Nach nexpaper**. Under Details, switch on **Show in Share Sheet** and
   let it take **PDFs** and **Images**.
3. Add the action **Get Contents of URL**: the address from step 1, **Method** POST, a **Header** `Authorization` with
   the value from step 1, **Request Body** Form, one field named `file` of the kind **File** holding the
   **Shortcut Input**.
4. Add the action **Show Notification** with the text "It is in the inbox."

To send several files at once, put the action of step 3 inside **Repeat with Each** over the Shortcut Input and use
**Repeated Item** as the file.

## For the operator: a shortcut to share

Build it as above, but in step 3 type placeholders, not your key. Then, in the shortcut's settings, add two **Import
Questions**: one for the URL of "Get Contents of URL" ("Address of your nexpaper, ending in
/api/v1/documents?source=share") and one for the value of the header ("Your key for uploading: Bearer npk_…, from My
account, Devices and apps"). Share it as an iCloud link and enter the link under Settings, API.

## What it does, and what it may

The shortcut sends each file as `POST /api/v1/documents?source=share` with the key. The answer names the new document
only; whether the account had the file already is not told to a key.
