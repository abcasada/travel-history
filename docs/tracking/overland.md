# Overland (iPhone)

Overland (overland.p3k.app; App Store 1.3) records detailed tracks and sends them in batches.
It needs location access **Always**.

## Setup

1. Install Overland from the App Store.
2. In **Location trackers**, create a token for **Overland**.
3. On the iPhone, tap **Open in Overland** (or scan the setup QR code with the camera). The link
   sets the receiver endpoint, the token (sent as `Authorization: Bearer`) and a device id.
4. Allow location **Always**. In Overland's settings, a batch size between 50 and 500 works
   well; the server takes at most 1,000 points per request.
5. Check: tap **Send now**. The token's "last used" time updates and the queue empties.

## Manual setup

Settings → **Receiver Endpoint**: the address shown when you created the token (it ends in
`/api/v1/ingest/overland`). **Access Token**: the token. Overland sends it in the
`Authorization` header. Older versions without a token field can append `?token=<token>` to the
URL instead; the server removes it before logging, but any proxy in between can see URLs, so
use the field when you can.

## Notes

- The server answers exactly `{"result":"ok"}`; any other answer makes Overland keep the batch
  and retry, so nothing is lost while something is wrong.
- Trip and visit records Overland adds to a batch are accepted and not stored; only the
  location points are.
- Don't force-quit Overland in the app switcher: iOS stops tracking for force-quit apps.
