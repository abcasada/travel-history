import type { ReactNode } from "react";
import { createContext, useContext } from "react";
import { ApiError, signInUrl } from "../api/client";
import { type MeOut, useGetMe } from "../api/generated";
import { PrivacyNotice } from "./PrivacyNotice";

const MeContext = createContext<MeOut | null>(null);

export function useMe(): MeOut {
  const me = useContext(MeContext);
  if (!me) throw new Error("useMe outside AuthGate");
  return me;
}

/** Renders children only for a signed-in user who has acknowledged the honesty notice. */
export function AuthGate({ children }: { children: ReactNode }) {
  const me = useGetMe();
  if (me.isPending) {
    return <Centered>Loading…</Centered>;
  }
  if (me.isError) {
    if (me.error instanceof ApiError && me.error.status === 401) return <SignIn />;
    return <Centered>Couldn't reach the server. Try again shortly.</Centered>;
  }
  if (!me.data.privacy_notice_ack_at) return <PrivacyNotice />;
  return <MeContext value={me.data}>{children}</MeContext>;
}

function SignIn() {
  return (
    <Centered>
      <h1 className="mb-2 text-2xl font-semibold">Travel History</h1>
      <p className="mb-6 text-slate-600">Sign in to see your family's trips.</p>
      <a className="rounded-md bg-blue-700 px-4 py-2 font-medium text-white" href={signInUrl()}>
        Sign in
      </a>
    </Centered>
  );
}

export function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-full flex-col items-center justify-center p-6 text-center">
      {children}
    </div>
  );
}
