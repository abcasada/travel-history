import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { BrowserRouter } from "react-router";
import { ApiError } from "./api/client";
import { AuthGate } from "./auth/AuthGate";
import { Shell } from "./shells/Shell";

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Authentication errors are handled by the gate, not retried.
        retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
        staleTime: 30_000,
      },
    },
  });
}

export function App({ queryClient }: { queryClient?: QueryClient }) {
  const [client] = useState(() => queryClient ?? makeQueryClient());
  return (
    <QueryClientProvider client={client}>
      <BrowserRouter basename="/app">
        <AuthGate>
          <Shell />
        </AuthGate>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
