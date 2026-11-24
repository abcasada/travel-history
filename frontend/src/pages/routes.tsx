import { Route, Routes } from "react-router";
import { ImportsPage } from "../imports/ImportsPage";
import { TripSheetPreviewPage } from "../imports/TripSheetPreviewPage";
import { PeoplePage } from "../people/PeoplePage";
import { LegRoutePage } from "../routing/LegRoutePage";
import { PurposesPage } from "../trips/PurposesPage";
import { TagsPage } from "../trips/TagsPage";
import { TripDetailPage } from "../trips/TripDetailPage";
import { TripEditPage, TripNewPage } from "../trips/TripEditPage";
import { TripListPage } from "../trips/TripListPage";
import { AboutPage } from "./About";
import { HistoryPage } from "./History";
import { Placeholder } from "./Placeholder";
import { TrackersPage } from "./Trackers";

/** List-pane content per route; both shells render the same routes. Paths are built with
 * trips/paths.ts; the map layers read the same URL (map/MapLayers.tsx). */
export function ListRoutes() {
  return (
    <Routes>
      <Route index element={<TripListPage title="Your trips" />} />
      <Route path="trips" element={<TripListPage />} />
      <Route path="trips/new" element={<TripNewPage />} />
      <Route path="trips/:tripId" element={<TripDetailPage />} />
      <Route path="trips/:tripId/edit" element={<TripEditPage />} />
      <Route path="trips/:tripId/legs/:legId/route" element={<LegRoutePage />} />
      <Route path="tags" element={<TagsPage />} />
      <Route path="purposes" element={<PurposesPage />} />
      <Route path="people" element={<PeoplePage />} />
      <Route path="review" element={<Placeholder title="Review queue" phase="phase 4" />} />
      <Route path="stats" element={<Placeholder title="Statistics" phase="phase 6" />} />
      <Route path="vehicles" element={<Placeholder title="Vehicles" phase="phase 4" />} />
      <Route path="imports" element={<ImportsPage />} />
      <Route path="imports/:batchId" element={<TripSheetPreviewPage />} />
      <Route path="history" element={<HistoryPage />} />
      <Route path="trackers" element={<TrackersPage />} />
      <Route path="about" element={<AboutPage />} />
      <Route path="*" element={<Placeholder title="Not found" phase="—" />} />
    </Routes>
  );
}
