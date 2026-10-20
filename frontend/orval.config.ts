import { defineConfig } from "orval";

// Typed API client generated from the backend's OpenAPI schema:
//   ./dev manage export_openapi > frontend/src/api/openapi.json && ./dev npm run gen:api
export default defineConfig({
  travel: {
    input: "./src/api/openapi.json",
    output: {
      target: "./src/api/generated.ts",
      client: "react-query",
      httpClient: "fetch",
      clean: false,
      override: {
        mutator: { path: "./src/api/client.ts", name: "apiFetch" },
        fetch: { includeHttpResponseReturnType: false },
      },
    },
  },
});
