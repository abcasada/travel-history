import { Route, Routes } from "react-router";
import { HistoryPage } from "./History";
import { Placeholder } from "./Placeholder";

/** List-pane content per route; both shells render the same routes. */
export function ListRoutes() {
  return (
    <Routes>
      <Route index element={<Placeholder title="Your trips" phase="phase 4 (catalog)" />} />
      <Route path="trips" element={<Placeholder title="Trips" phase="phase 4" />} />
      <Route path="review" element={<Placeholder title="Review queue" phase="phase 4" />} />
      <Route path="stats" element={<Placeholder title="Statistics" phase="phase 6" />} />
      <Route path="vehicles" element={<Placeholder title="Vehicles" phase="phase 4" />} />
      <Route path="history" element={<HistoryPage />} />
      <Route path="*" element={<Placeholder title="Not found" phase="—" />} />
    </Routes>
  );
}
