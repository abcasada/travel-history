# Exporting your Google Timeline

Google keeps Timeline (Location History) only on your phone, so the export has to start there.
This guide covers getting the file off the phone, keeping it safe, and importing it.
Format details and the importer's design are in [design/timeline-import.md](design/timeline-import.md) (§8).

## 1. Before you export

- **Keep retention on.** In the Timeline settings, turn auto-delete off. Otherwise Google may
  drop old history before you export it.

## 2. Export from the phone

Menu names move between app versions. If a step doesn't match, look for "Timeline" under the
location settings.

**Android**

1. Open the phone's **Settings → Location → Location services → Timeline**. On some versions
   it's in Google Maps instead: **profile picture → Settings → Location & privacy**.
2. Choose **Export Timeline data** and save the file. It's usually called `Timeline.json`.

**iPhone**

1. Open **Google Maps → profile picture → Your Timeline → ⋯ → Location and privacy settings**.
2. Choose **Export Timeline data** and save the file to Files.

The iPhone format is supported but **not yet verified against a real export** (D-38). If anyone
in the family uses an iPhone, a sample export helps confirm it.

## 3. Keep the original safe

The export is the only copy of your history that you control. Keep the original file:

- in **three places**, one of them offline (for example, a USB drive in a drawer);
- **out of git**. On the server it goes in `data/private/`, which is git-ignored.

The app never changes or deletes the raw file. It archives the uploaded bytes read-only
(zstd-compressed, checksum-verified, included in the encrypted backups).

## 4. Import

Upload the file on the **History** page (it's also there under "How do I export my
Timeline?"). Large files upload in resumable chunks, so a dropped connection doesn't mean
starting over.

- The import runs in the background. The History page shows the progress and a summary
  (segments, points, and what changed).
- **Re-importing a newer export is safe.** The app compares it with what it already has.
  It adds new data and flags what changed. Anything missing from the new export is kept,
  not deleted. Trips you've confirmed are never changed silently; they get a review flag.
- Place names don't come from Google (the export has only place IDs). They're filled in
  later by offline reverse geocoding.

## 5. Privacy notes

- The file contains your precise location history. Don't email it or put it in shared cloud
  folders.
- Nothing from the export is sent to third-party services. Routing and geocoding run on the
  server.
