# Third-party notices

This file lists third-party code ported into this repository and the data/services whose
licenses require attribution. The app's About page shows the same attributions.

## Code

### gpx.studio (MIT)

The drag-to-reshape route editor (docs/design/routing.md §13.4) is ported from gpx.studio's
anchor routing (https://github.com/gpxstudio/gpx.studio, commit 2e0edc7, 2026-11-15):
`frontend/src/routing/editor/geometry.ts`, `model.ts` and `controller.ts`. Each of those files
carries the notice below in its header.

> MIT License
>
> Copyright (c) 2026 gpx.studio
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

## Data and services

- Map data © OpenStreetMap contributors (ODbL 1.0).
- Basemap: OpenFreeMap © OpenMapTiles, data from OpenStreetMap.
- Routing: Valhalla (MIT); OpenRouteService results © openrouteservice by HeiGIT (CC-BY-SA 4.0);
  FOSSGIS OSRM demo server (routing.openstreetmap.de).
- Airports: OurAirports (public domain).
- Airlines and aircraft: OpenFlights.org (ODbL 1.0 / DbCL 1.0).
- Countries and states/provinces: Natural Earth (public domain).
- US counties: US Census Bureau cartographic boundary files (public domain).
- Place names: GeoNames (geonames.org), CC BY 4.0.
