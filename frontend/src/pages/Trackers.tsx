import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import {
  type DeviceTokenCreatedOut,
  type DeviceTokenOut,
  getListDeviceTokensQueryKey,
  type TrackerKind,
  useCreateDeviceToken,
  useListDeviceTokens,
  useRevokeDeviceToken,
} from "../api/generated";
import { useMe } from "../auth/AuthGate";

export const TRACKERS: { kind: TrackerKind; label: string; hint: string }[] = [
  { kind: "owntracks", label: "OwnTracks", hint: "Android or iPhone" },
  { kind: "overland", label: "Overland", hint: "iPhone" },
  { kind: "colota", label: "Colota", hint: "Android (recommended)" },
  { kind: "gpslogger", label: "GPSLogger", hint: "Android" },
  { kind: "generic", label: "Other", hint: "any app that speaks OwnTracks or Overland" },
];

const LINK_LABEL: Partial<Record<TrackerKind, string>> = {
  owntracks: "Open in OwnTracks",
  overland: "Open in Overland",
  colota: "Open in Colota",
};

function trackerLabel(kind: TrackerKind) {
  return TRACKERS.find((t) => t.kind === kind)?.label ?? kind;
}

function when(value: string | null) {
  return value ? new Date(value).toLocaleString() : "never";
}

/** Location trackers (PLAN.md §9): one write-only token per tracker app, shown once. */
export function TrackersPage() {
  const me = useMe();
  const queryClient = useQueryClient();
  const tokens = useListDeviceTokens();
  const [created, setCreated] = useState<DeviceTokenCreatedOut | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: getListDeviceTokensQueryKey() });
  const revoke = useRevokeDeviceToken({ mutation: { onSuccess: refresh } });
  const canCreate = me.role !== "viewer";

  return (
    <div className="space-y-4 p-4">
      <div>
        <h2 className="text-lg font-semibold">Location trackers</h2>
        <p className="text-sm text-slate-600">
          A tracker app on your phone sends its location to your raw history, which only you can
          see. Each app gets its own token. A token can only add points: it can't read anything, and
          you can revoke it at any time.
        </p>
      </div>

      {created ? (
        <NewToken created={created} onDone={() => setCreated(null)} />
      ) : canCreate ? (
        <CreateForm
          onCreated={(result) => {
            setCreated(result);
            refresh();
          }}
        />
      ) : (
        <p className="text-sm text-slate-600">Viewers don't record location history.</p>
      )}

      <section>
        <h3 className="mb-2 font-medium">Your tokens</h3>
        {tokens.isPending && <p className="text-sm text-slate-600">Loading…</p>}
        {tokens.isError && <p className="text-sm text-red-700">Couldn't load your tokens.</p>}
        {tokens.data?.length === 0 && <p className="text-sm text-slate-600">None yet.</p>}
        <ul className="divide-y rounded border">
          {tokens.data?.map((token) => (
            <TokenRow
              key={token.id}
              token={token}
              canRevoke={canCreate}
              busy={revoke.isPending}
              onRevoke={() => {
                const question = `Revoke "${token.name}"? The tracker stops sending points at once, and this can't be undone.`;
                if (window.confirm(question)) revoke.mutate({ tokenId: token.id });
              }}
            />
          ))}
        </ul>
      </section>
    </div>
  );
}

function CreateForm({ onCreated }: { onCreated: (result: DeviceTokenCreatedOut) => void }) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<TrackerKind>("owntracks");
  const create = useCreateDeviceToken({ mutation: { onSuccess: onCreated } });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate({ data: { name: name.trim(), kind } });
  };
  return (
    <form onSubmit={submit} className="space-y-2 rounded border p-3">
      <h3 className="font-medium">Add a tracker</h3>
      <label className="block text-sm">
        Name
        <input
          className="mt-1 block w-full rounded border px-2 py-1"
          value={name}
          maxLength={100}
          required
          placeholder="e.g. My phone"
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <label className="block text-sm">
        App
        <select
          className="mt-1 block w-full rounded border px-2 py-1"
          value={kind}
          onChange={(e) => setKind(e.target.value as TrackerKind)}
        >
          {TRACKERS.map((t) => (
            <option key={t.kind} value={t.kind}>
              {t.label} ({t.hint})
            </option>
          ))}
        </select>
      </label>
      {create.isError && <p className="text-sm text-red-700">Couldn't create the token.</p>}
      <button
        type="submit"
        className="rounded-md bg-blue-700 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        disabled={create.isPending || name.trim() === ""}
      >
        Create token
      </button>
    </form>
  );
}

/** Everything that contains the token, shown once. Leaving the page discards it. */
function NewToken({ created, onDone }: { created: DeviceTokenCreatedOut; onDone: () => void }) {
  const { setup, token, device } = created;
  const kind = device.kind;
  return (
    <section className="space-y-3 rounded border border-amber-400 bg-amber-50 p-3">
      <h3 className="font-medium">Set up {trackerLabel(kind)}</h3>
      <p className="text-sm font-medium text-amber-900">
        This is the only time the token is shown. Set up the app now; if you lose it, revoke this
        token and create a new one. Don't share screenshots of this page.
      </p>
      {setup.link && setup.link_qr && (
        <div className="space-y-1">
          <p className="text-sm">
            Scan this with the phone's camera, or open the link on the phone itself:
          </p>
          <img src={setup.link_qr} alt="Setup QR code" className="h-56 w-56 bg-white" />
          <a className="text-sm text-blue-800 underline" href={setup.link}>
            {LINK_LABEL[kind] ?? "Open the setup link"}
          </a>
        </div>
      )}
      <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="text-slate-600">Address</dt>
        <dd className="break-all font-mono">{setup.endpoint}</dd>
        <dt className="text-slate-600">Sign-in</dt>
        <dd>
          {setup.auth === "basic"
            ? `user name "${setup.username}", password: the token`
            : "Authorization: Bearer <token>"}
        </dd>
        {setup.body_template && (
          <>
            <dt className="text-slate-600">Method</dt>
            <dd>POST, header Content-Type: {setup.content_type}</dd>
            <dt className="text-slate-600">Body</dt>
            <dd className="break-all font-mono">{setup.body_template}</dd>
          </>
        )}
        <dt className="text-slate-600">Token</dt>
        <dd>
          <input
            readOnly
            aria-label="Token"
            className="w-full rounded border bg-white px-2 py-1 font-mono text-xs"
            value={token}
            onFocus={(e) => e.target.select()}
          />
        </dd>
      </dl>
      <details className="text-sm">
        <summary className="cursor-pointer">QR code of the token alone</summary>
        <img src={setup.token_qr} alt="Token QR code" className="mt-1 h-48 w-48 bg-white" />
      </details>
      <button
        type="button"
        className="rounded-md bg-blue-700 px-3 py-1.5 text-sm font-medium text-white"
        onClick={onDone}
      >
        Done, hide the token
      </button>
    </section>
  );
}

function TokenRow({
  token,
  canRevoke,
  busy,
  onRevoke,
}: {
  token: DeviceTokenOut;
  canRevoke: boolean;
  busy: boolean;
  onRevoke: () => void;
}) {
  const revoked = token.revoked_at !== null;
  return (
    <li className="flex items-start justify-between gap-3 p-2 text-sm">
      <div>
        <div className="font-medium">
          {token.name}{" "}
          <span className="font-normal text-slate-600">
            · {trackerLabel(token.kind)} · <span className="font-mono">{token.token_prefix}…</span>
          </span>
        </div>
        <div className="text-slate-600">
          {revoked
            ? `Revoked ${when(token.revoked_at)}`
            : `Last used ${when(token.last_used_at)} · ${token.points_received.toLocaleString()} points`}
        </div>
      </div>
      {!revoked && canRevoke && (
        <button
          type="button"
          className="rounded border px-2 py-1 hover:bg-slate-100 disabled:opacity-50"
          disabled={busy}
          onClick={onRevoke}
        >
          Revoke
        </button>
      )}
    </li>
  );
}
