# Research: Timeline formats, tracker protocols, datasets (checked 2026-10-19/20)

[H]/[M]/[L] confidence. AGPL/GPL sources (RouteConverter, Timelinize, Reitti, Colota, GPSLogger,
PhoneTrack) were read only to learn formats; nothing copied. Examples use made-up coordinates.

## 1. Google Maps Timeline on-device export (no official schema)
- Android: Settings → Location → Location services → Timeline → Export Timeline data
  (`Timeline.json` / `location-history.json`, localized). iOS: Google Maps → profile → Your
  Timeline → ⋯ → Location and privacy settings → Export Timeline data (`location-history.json`)
  [M] (dawarich timeline-format-detector; dawarich #2587). On-device storage confirmed
  (support.google.com/maps/answer/14169818) [H].
- **Android** (mlocati/gmaps-timeline-json MIT schema; pkg.go.dev/github.com/bobg/lohi/schema;
  dawarich.app/blog/whats-inside-your-google-timeline-export) [H]:
  - top level `{semanticSegments[], rawSignals[], userLocationProfile{}}`;
  - times ISO 8601 with ms and offset (`2024-05-04T09:15:00.000+02:00`);
    `startTimeTimezoneUtcOffsetMinutes`/`endTime…` on visit/activity/memory segments;
  - coordinates strings `"48.8566120°, 2.3522190°"` (lat first, degree signs), wrapped
    `{"latLng": …}` in segments, `LatLng` (capital L) in rawSignals.position;
  - `visit`: hierarchyLevel, probability, isTimelessVisit?, topCandidate {placeId, semanticType
    (UNKNOWN, HOME, WORK, INFERRED_HOME, INFERRED_WORK, SEARCHED_ADDRESS, ALIASED_LOCATION),
    probability, placeLocation.latLng};
  - `activity`: start.latLng, end.latLng, distanceMeters, probability, topCandidate {type
    (IN_PASSENGER_VEHICLE, WALKING, CYCLING, FLYING, IN_BUS, IN_TRAIN, IN_SUBWAY, IN_TRAM, IN_FERRY,
    IN_RAIL_VEHICLE, IN_ROAD_VEHICLE, IN_VEHICLE, MOTORCYCLING, RUNNING, ON_FOOT, ON_BICYCLE,
    BOATING, STILL, EXITING_VEHICLE, UNKNOWN_ACTIVITY_TYPE), probability}, parking?;
  - `timelinePath`: [{point "lat°, lng°", time ISO}];
  - `timelineMemory`: {trip {distanceFromOriginKms, destinations[{identifier{placeId}}]}};
  - rawSignals: `position` {LatLng, accuracyMeters, altitudeMeters, source (GPS, WIFI_ONLY,
    UNKNOWN), timestamp, speedMetersPerSecond}, `wifiScan`, `activityRecord`;
  - userLocationProfile: frequentPlaces[{placeId, placeLocation (bare string), label HOME|WORK}],
    frequentTrips[…], persona.travelModeAffinities.
  - **No place names** — only placeId, coordinates, semanticType [H].
- **iOS** (dawarich #2587 real excerpt, fixed 1.7.3; RouteConverter #351 real 2.5 MB file;
  Timelinize; Reitti dto/ios) [H unless noted]:
  - root is a bare array of {startTime, endTime, visit|activity|timelinePath}; no rawSignals or
    userLocationProfile;
  - coordinates `"geo:41.570045,-8.468077"` (6 decimals), not wrapped;
  - numbers/booleans as strings (`"probability": "0.598864"`); key `placeID`;
  - enums human-cased: semanticType `Unknown`, `Home`, `Work`, `Searched Address`,
    `Aliased Location`; activity `in passenger vehicle`, `walking`, `cycling`, `in train`,
    `in subway`, `in bus`, `flying`, `skiing`, `in ferry`, `in tram`;
  - path points `{point, durationMinutesOffsetFromStartTime: "15"}` (minute precision);
  - timelinePath records grouped at the end of the array, 2-hour windows [M-H];
  - times mixed `Z` and `±HH:MM` [M-H]; no altitude/speed/accuracy [M]; activity probability often
    `"0.000000"` [M].
- Detection: object with semanticSegments/rawSignals → Android; array whose first element has
  startTime + visit/activity/timelinePath → iOS; parse both `geo:lat,lng` and `lat°, lng°`.
- Sizes: one iOS file of ~19 months = 2.5 MB (2,933 records, 16,189 path points); Android with
  rawSignals larger; plan 1 MB–several hundred MB [L].
- Legacy Takeout (Records.json E7; Semantic Location History timelineObjects) out of scope.

## 2. OwnTracks HTTP (owntracks.org/booklet/tech/http/, /tech/json/, /features/remoteconfig/) [H]
- POST JSON, one message per request; headers `X-Limit-U`/`X-Limit-D` when identification is set
  (iOS: not reliable).
- Auth: HTTP Basic (settings or userinfo in URL); query params passed through; iOS `httpHeaders`.
- Response: any 2xx = delivered; return `[]` (may contain location/card/transition/cmd); ignore
  zero-length bodies.
- `_type: location`: required lat, lon, tst; optional acc, alt, vac, vel (km/h), cog, batt, bs,
  conn, t, m, SSID, BSSID, inregions, inrids, created_at, topic, tid, motionactivities, poi, tag.
  Zero acc/alt/vel may be omitted.
- Other `_type`: transition, waypoint(s), lwt, card, status, cmd, encrypted (libsodium),
  steps/beacon/request (iOS), configuration.
- Remote config: `.otrc` JSON `{"_type":"configuration", mode: 3, url, auth, username,
  password, deviceId, tid, monitoring, locatorDisplacement, locatorInterval, …}`; deliver as
  `owntracks:///config?inline=<base64>` (URL-encode); both platforms support the URL; QR config
  listed iOS-only [M].
- Android v2.5.9 (2026-05-15, EPL-1.0, F-Droid); iOS 27.1.2 (2026-10-17).

## 3. Overland (github.com/aaronpk/Overland-iOS, overland.p3k.app) [H]
- POST `{"locations":[GeoJSON Feature Point [lon, lat]], "current"?, "trip"?}`; properties
  timestamp (ISO 8601), altitude, speed (m/s), course, horizontal/vertical_accuracy, motion[],
  battery_state, battery_level (0–1), wifi, device_id, unique_id?; batch default 200 (50–1000).
- Auth: `Authorization: Bearer <token>`; URL may also carry params.
- Response must be exactly `{"result":"ok"}` (else retried); may include `"set": {…}`.
- Setup link `overland://setup?url=<urlencoded>&token=…&device_id=…&unique_id=yes`.
- App Store v1.3 (2024-05-13); repo very active 2026-10; Apache-2.0. No official Android
  (happytechca/overland-android v1.4.2 immature; Colota recommended).

## 4. GPSLogger (mendhak/gpslogger; FAQ custom URL, CustomUrlManager) [H]
- Custom URL: free-text URL, method (GET default, POST/PUT), body, headers; Basic auth fields.
- Placeholders: %LAT %LON %DESC %SAT %ALT %SPD %SPD_KPH %ACC %DIR %PROV %TIMESTAMP (epoch s)
  %TIME %TIMEOFFSET %DATE %STARTTIMESTAMP %BATT %ISCHARGING %AID %SER %FILENAME %PROFILE %HDOP
  %VDOP %PDOP %DIST %ALL. %TIME etc. URL-encoded even in bodies → use %TIMESTAMP [M-H].
- No built-in OwnTracks format; JSON body template approximates it; Content-Type header needed.
- Offline queue; auto-send replays CSV hourly (server must dedupe).
- Profile URL `gpslogger://properties/<https URL to .properties>`.
- v137 (2026-08-14), GPL-2.0, F-Droid.

## 5. PhoneTrack [H]
Server julien-nc/phonetrack v1.3.5 (AGPL); Android client v0.1.0 (2020), effectively
unmaintained; custom GET/POST with %LAT %LON %TIMESTAMP %ALT %ACC %SPD %DIR %SAT %BATT %UA; no
native OwnTracks output. Not recommended.

## 6. Colota (github.com/dietrichmax/colota, colota.app) [H]
- AGPL-3.0, v1.20.0 (2026-10-03), ~weekly releases, 686 stars; Play, F-Droid (`com.Colota`),
  IzzyOnDroid; Android only.
- Default payload: flat JSON per point {lat, lon, acc, alt?, vel (m/s), batt, bs, tst, bear?};
  field names remappable; static custom fields (strings); GET option.
- Templates: OwnTracks (adds `_type: location`, `tid`; `cog`), Overland (batch GeoJSON 1–500,
  default 50, `device_id`), Dawarich, GeoPulse, PhoneTrack, Reitti, Traccar, Custom.
- Server: any 2xx; up to 10 concurrent requests in batch sync; HTTPS required for public hosts.
- Auth: none/Basic/Bearer/custom headers/mTLS.
- Setup `colota://setup?config=<base64 JSON>` (QR too) with endpoint, interval, distance,
  syncInterval, apiTemplate, httpMethod, fieldMap, customFields, auth.{type, username, password,
  bearerToken}, customHeaders, geofences, profiles; confirmation screen.
- Offline queue + backoff; profiles (charging, Android Auto, Wi-Fi, BT, speed, stationary);
  stops < 5% battery.
- **Qualifies** as an Android tracker via its OwnTracks or Overland template.

## 7. Background location
- dontkillmyapp.com: Samsung (Never sleeping apps, Unrestricted battery, disable adaptive
  battery/auto-disable; settings may revert after updates), Xiaomi (Autostart, no restrictions,
  lock in recents), Pixel (Unrestricted helps) [H].
- Android 14+: location FGS type + FOREGROUND_SERVICE_LOCATION; background start needs
  ACCESS_BACKGROUND_LOCATION ("Allow all the time")
  (developer.android.com/develop/background-work/services/fgs/service-types) [H].
- iOS: OwnTracks significant mode (~500 m / ≥ 5 min, battery-efficient), move mode (100 m / 300 s,
  heavy); Overland needs "Always"; force-quit apps not relaunched on iOS 26 [L-M].

## 8. Datasets
- **OurAirports** (github.com/davidmegginson/ourairports-data, Unlicense/public domain [H];
  daily updates): airports.csv 86,258 rows, 12.7 MB; columns id, ident, type, name, latitude_deg,
  longitude_deg, elevation_ft, continent, iso_country, iso_region, municipality,
  scheduled_service, icao_code, iata_code, gps_code, local_code, home_link, wikipedia_link,
  keywords. Types: small 42,820; heliport 23,248; **closed 13,574**; medium 4,104; seaplane 1,273;
  large 1,176; balloonport 63. Closed airports have **empty iata_code**; old codes survive only in
  `keywords` (e.g. Stapleton "DEN KDEN, X-KDEN"; Kai Tak "HKG"; Tegel "TXL"; Tempelhof
  "BER, EDDI, THF") → keyword parsing + date logic. countries.csv, regions.csv.
- **OpenFlights** (openflights.org/data.php): database ODbL 1.0, contents DbCL 1.0; acknowledge
  source and license public derived works freely ("Data: OpenFlights.org (ODbL)" + link).
  CSV with `\N`. airlines.dat (ID, Name, Alias, IATA, ICAO, Callsign, Country, Active) 6,162 rows
  (Y 1,255, N 4,906); 320 duplicated IATA codes (PA, TW…). planes.dat (Name, IATA, ICAO) 246 rows.
  **Stale:** airlines 2017-02, airports 2019-05; Active "not reliable"; defunct codes often missing.
- **Natural Earth** (public domain, naturalearthdata.com/about/terms-of-use): v5.1.x;
  `https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip` (4.9 MB),
  `…/ne_10m_admin_1_states_provinces.zip` (14.9 MB). Admin-0: use `ISO_A2_EH` (ISO_A2 is −99 for
  France, Norway, Kosovo…). Admin-1: 4,596 features, `iso_3166_2`, `adm0_a3`, `name`, `gn_id`;
  strip NUL padding.
- **US Census cartographic boundaries**: 2025 vintage
  `https://www2.census.gov/geo/tiger/GENZ2025/shp/cb_2025_us_county_500k.zip` (11.8 MB); fields
  STATEFP, COUNTYFP, COUNTYNS, GEOIDFQ, GEOID, NAME, NAMELSAD, STUSPS, STATE_NAME, LSAD, ALAND,
  AWATER; public domain [M-H].
- **GeoNames** (download.geonames.org/export/dump): CC BY 4.0, credit + link; daily dumps;
  cities500.zip 13 MB (~185k), cities1000 11 MB, allCountries 403 MB; 19 TSV columns (geonameid,
  name, asciiname, alternatenames, latitude, longitude, feature class, feature code, country code,
  cc2, admin1–4, population, elevation, dem, timezone, modification date); admin1CodesASCII
  (`US.CA`); admin1 codes are FIPS for many countries, not ISO.
- Historical airline codes: no open dataset with validity dates; OpenFlights Active=N
  incomplete; Wikipedia lists as manual fallback [L].

## 9. ijson 3.6.0 (2026-10-12, BSD-3/ISC) [H]
Backends yajl2_c (wheels), yajl2_cffi, yajl2, python; `ijson.items(f, "semanticSegments.item")`,
`"rawSignals.item"`, `"item"` for iOS; `use_float=True`; binary mode; one pass can't stream two
arrays at once → two passes or `ijson.parse` events.
