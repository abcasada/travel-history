/** Synthetic trips for frontend tests: fake people and places only (CLAUDE.md, "Tests are
 * synthetic"). Override any field per test. */
import type {
  LegOut,
  ParticipantOut,
  StopOut,
  TripDetailOut,
  TripMapOut,
  TripOut,
} from "../api/generated";

const USER = { id: 1, display_name: "Synthetic Member" };

export function makeTrip(over: Partial<TripOut> = {}): TripOut {
  return {
    id: 10,
    title: "Synthetic lake weekend",
    start_date: "2024-05-01",
    end_date: "2024-05-03",
    date_precision: "day",
    status: "confirmed",
    visibility: "participants",
    source: "manual",
    locked: false,
    needs_review: false,
    purpose: { id: 2, name: "Vacation" },
    owner: USER,
    is_owner: true,
    cover_media_id: null,
    tags: [],
    created_at: "2024-05-04T10:00:00Z",
    updated_at: "2024-05-04T10:00:00Z",
    ...over,
  };
}

export function makeStop(over: Partial<StopOut> = {}): StopOut {
  return {
    id: 100,
    trip_id: 10,
    leg_id: null,
    kind: "destination",
    arrive_utc: null,
    depart_utc: null,
    tz: "America/Chicago",
    time_precision: "exact",
    notes: "",
    place: {
      id: 500,
      name: "Synthetic Lake",
      address: "",
      lon: -97.1,
      lat: 38.1,
      country_code: "",
    },
    author: USER,
    can_edit: true,
    ...over,
  };
}

export function makeLeg(over: Partial<LegOut> = {}): LegOut {
  return {
    id: 200,
    trip_id: 10,
    sequence: 1,
    mode: "drive",
    start_utc: null,
    start_tz: "",
    end_utc: null,
    end_tz: "",
    time_precision: "exact",
    origin_label: "",
    destination_label: "",
    origin_stop_id: null,
    destination_stop_id: null,
    vehicle: null,
    author: USER,
    is_contribution: false,
    participant_scope: "trip",
    current_route_id: null,
    distance_m: null,
    airline_id: null,
    flight_number: "",
    origin_airport_id: null,
    destination_airport_id: null,
    aircraft_type_id: null,
    aircraft_registration: "",
    seat: "",
    cabin_class: "",
    notes: "",
    participant_ids: [],
    can_edit: true,
    can_delete: true,
    ...over,
  };
}

export function makeParticipant(
  id: number,
  name: string,
  over: Partial<ParticipantOut> = {},
): ParticipantOut {
  return {
    person: { id, display_name: name },
    on_trip: true,
    public_consent: false,
    leg_ids: [],
    is_me: false,
    can_set_consent: false,
    ...over,
  };
}

export function makeDetail(over: Partial<TripDetailOut> = {}): TripDetailOut {
  return {
    ...makeTrip(),
    notes: "",
    photo_limit_per_contributor: 50,
    edited_in_app_at: null,
    sharing: null,
    access: { edit: true, delete: true, contribute: true, add_leg: "core" },
    participants: [],
    legs: [],
    stops: [],
    ...over,
  };
}

export const EMPTY_MAP: TripMapOut = { trips: [], stops: [], legs: [], truncated: false };
