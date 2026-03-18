"""
RAPTOR (Round-Based Public Transit Optimized Router) for LA Metro rail.

Computes pareto-optimal journeys (fewest transfers AND earliest arrival)
using GTFS static schedule data already cached by gtfs_service.py.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

LA_TZ = ZoneInfo("America/Los_Angeles")

# Walk speed for transfer time estimation
WALK_SPEED_MPH = 3.0
# Same-platform / same-station transfer time (seconds)
SAME_STATION_TRANSFER_SEC = 180
# Maximum walking distance for cross-station transfers (miles)
MAX_TRANSFER_DISTANCE_MI = 0.25

INF = float('inf')

ROUTE_LINE_MAP = {
    "801": "A",
    "802": "B",
    "803": "C",
    "804": "E",
    "805": "D",
    "806": "E",
    "807": "K",
}


@dataclass
class RaptorIndex:
    """Pre-built index structures for RAPTOR queries."""
    # Each pattern is a unique ordered sequence of stop_ids
    pattern_stops: list  # list[tuple[str, ...]]
    # Line letter per pattern
    pattern_line: list  # list[str]
    # stop_id -> list of (pattern_id, position_in_pattern)
    stop_patterns: dict  # dict[str, list[tuple[int, int]]]
    # pattern_id -> trips sorted by departure at first stop
    # each trip = list of (arrival_sec, departure_sec) aligned with pattern_stops
    pattern_trips: list  # list[list[list[tuple[int, int]]]]
    # Parallel trip_id strings for service_id filtering
    pattern_trip_ids: list  # list[list[str]]
    # stop_id -> [(target_stop_id, walk_seconds)]
    transfers: dict  # dict[str, list[tuple[str, int]]]
    # stop_id -> {name, lat, lng, parent}
    stop_info: dict  # dict[str, dict]
    # GTFS stop_id -> Django Station model name
    gtfs_stop_to_app_name: dict  # dict[str, str]
    # Reference to trip_lookup for service_id checks
    trip_lookup: dict = field(repr=False)


@dataclass
class JourneyLeg:
    type: str  # 'ride' or 'transfer'
    line: str  # line letter or None
    from_stop: str
    from_name: str
    to_stop: str
    to_name: str
    departure_sec: int
    arrival_sec: int
    trip_id: str = None
    num_stops: int = 0


@dataclass
class Journey:
    legs: list  # list[JourneyLeg]
    departure_sec: int
    arrival_sec: int
    num_transfers: int


def _haversine_miles(lat1, lng1, lat2, lng2):
    R = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _parse_gtfs_time(time_str):
    """Parse GTFS time (HH:MM:SS, may exceed 24h) to seconds from midnight."""
    h, m, s = map(int, time_str.split(":"))
    return h * 3600 + m * 60 + s


def _normalize_station_name(name):
    """Normalize a GTFS station name for matching against Django Station names."""
    import re
    name = name.strip()
    name = re.sub(r'\s*Station\b.*', '', name)
    name = re.sub(r'\s*-\s*Metro\b.*', '', name)
    name = re.sub(r'\s+[A-Z]-Line\b', '', name)
    return name.strip()


# ---------------------------------------------------------------------------
# Index Construction
# ---------------------------------------------------------------------------

def build_raptor_index(gtfs_data):
    """Build RAPTOR index structures from parsed GTFS cache data.

    Args:
        gtfs_data: dict returned by gtfs_service._build_cache_data()

    Returns:
        RaptorIndex ready for raptor_query()
    """
    trip_lookup = gtfs_data["trip_lookup"]
    trip_stop_times = gtfs_data["trip_stop_times"]
    stop_lookup = gtfs_data["stop_lookup"]
    parent_children = gtfs_data["parent_children"]
    route_line = gtfs_data["route_line"]

    # --- 1. Extract route patterns ---
    # A pattern is (route_id, ordered tuple of stop_ids)
    # Group trips by their pattern
    pattern_map = {}  # (route_id, stop_tuple) -> pattern_id
    pattern_stops_list = []  # pattern_id -> tuple of stop_ids
    pattern_line_list = []  # pattern_id -> line letter
    pattern_trips_map = defaultdict(list)  # pattern_id -> [(sort_key, trip_times, trip_id)]

    for tid, trip in trip_lookup.items():
        sts = trip_stop_times.get(tid, [])
        if not sts:
            continue
        # Sort by stop_sequence
        sts_sorted = sorted(sts, key=lambda x: int(x.get("stop_sequence", 0)))
        stop_seq = tuple(st.get("stop_id", "") for st in sts_sorted)
        if not stop_seq:
            continue

        route_id = trip.get("route_id", "")
        key = (route_id, stop_seq)

        if key not in pattern_map:
            pid = len(pattern_stops_list)
            pattern_map[key] = pid
            pattern_stops_list.append(stop_seq)
            pattern_line_list.append(route_line.get(route_id, ""))

        pid = pattern_map[key]

        # Build trip times aligned with pattern stops
        trip_times = []
        for st in sts_sorted:
            arr_str = st.get("arrival_time", "")
            dep_str = st.get("departure_time", "")
            try:
                arr = _parse_gtfs_time(arr_str) if arr_str else None
                dep = _parse_gtfs_time(dep_str) if dep_str else None
            except (ValueError, TypeError):
                arr = dep = None
            if arr is None and dep is not None:
                arr = dep
            if dep is None and arr is not None:
                dep = arr
            if arr is None:
                # Skip this trip entirely if any stop has no time
                trip_times = None
                break
            trip_times.append((arr, dep))

        if trip_times is None:
            continue

        # Sort key: departure at first stop
        sort_key = trip_times[0][1]
        pattern_trips_map[pid].append((sort_key, trip_times, tid))

    # --- 2. Build stop-to-pattern index ---
    stop_patterns = defaultdict(list)
    for pid, stops in enumerate(pattern_stops_list):
        for pos, sid in enumerate(stops):
            stop_patterns[sid].append((pid, pos))

    # --- 3. Sort trips per pattern by departure at first stop ---
    pattern_trips_list = []
    pattern_trip_ids_list = []
    for pid in range(len(pattern_stops_list)):
        trips_raw = pattern_trips_map.get(pid, [])
        trips_raw.sort(key=lambda x: x[0])
        pattern_trips_list.append([t[1] for t in trips_raw])
        pattern_trip_ids_list.append([t[2] for t in trips_raw])

    # --- 4. Build transfer graph ---
    transfers = defaultdict(list)

    # Collect platform stops (those with a parent_station)
    platform_stops = {}  # stop_id -> {lat, lng, parent}
    for sid, s in stop_lookup.items():
        parent = s.get("parent_station", "")
        lat_str = s.get("stop_lat", "")
        lng_str = s.get("stop_lon", "")
        if not lat_str or not lng_str:
            continue
        try:
            lat = float(lat_str)
            lng = float(lng_str)
        except (ValueError, TypeError):
            continue
        # Only include stops that are actually served by patterns
        if sid in stop_patterns:
            platform_stops[sid] = {"lat": lat, "lng": lng, "parent": parent}

    # Same-parent transfers
    parent_groups = defaultdict(list)
    for sid, info in platform_stops.items():
        if info["parent"]:
            parent_groups[info["parent"]].append(sid)

    for parent, children in parent_groups.items():
        for i, a in enumerate(children):
            for b in children[i + 1:]:
                transfers[a].append((b, SAME_STATION_TRANSFER_SEC))
                transfers[b].append((a, SAME_STATION_TRANSFER_SEC))

    # Same-location transfers: some interchange stations have separate GTFS
    # parent stations per line (e.g. Expo/Crenshaw E-Line vs K-Line).
    # Detect these by matching parent station base names (strip line suffix).
    import re as _re
    def _base_name(name):
        n = _re.sub(r'\s*-?\s*[A-Z]-?Line.*', '', name, flags=_re.IGNORECASE)
        n = _re.sub(r'\s*Station\s*$', '', n)
        return n.strip().lower()

    parent_base_groups = defaultdict(list)  # base_name -> [parent_id, ...]
    for parent_id in parent_groups:
        parent_stop = stop_lookup.get(parent_id, {})
        pname = parent_stop.get("stop_name", "")
        if pname:
            parent_base_groups[_base_name(pname)].append(parent_id)

    for base, parent_ids in parent_base_groups.items():
        if len(parent_ids) < 2:
            continue
        # Collect all platform stops across these co-located parents
        all_platforms = []
        for pid in parent_ids:
            all_platforms.extend(parent_groups.get(pid, []))
        # Create transfers between platforms of different parents
        for i, a in enumerate(all_platforms):
            for b in all_platforms[i + 1:]:
                if platform_stops[a]["parent"] != platform_stops[b]["parent"]:
                    # Avoid duplicates
                    existing = {t for t, _ in transfers.get(a, [])}
                    if b not in existing:
                        transfers[a].append((b, SAME_STATION_TRANSFER_SEC))
                        transfers[b].append((a, SAME_STATION_TRANSFER_SEC))

    # --- 5. Build stop_info ---
    stop_info = {}
    for sid, s in stop_lookup.items():
        lat_str = s.get("stop_lat", "")
        lng_str = s.get("stop_lon", "")
        try:
            lat = float(lat_str)
            lng = float(lng_str)
        except (ValueError, TypeError):
            lat = lng = 0.0
        name = s.get("stop_name", sid)
        parent = s.get("parent_station", "")
        # Use parent name if available
        if parent and parent in stop_lookup:
            name = stop_lookup[parent].get("stop_name", name)
        stop_info[sid] = {
            "name": _normalize_station_name(name),
            "lat": lat,
            "lng": lng,
            "parent": parent,
        }

    # --- 6. Build GTFS stop → app name mapping ---
    gtfs_stop_to_app_name = _build_gtfs_to_app_mapping(stop_info)

    return RaptorIndex(
        pattern_stops=pattern_stops_list,
        pattern_line=pattern_line_list,
        stop_patterns=dict(stop_patterns),
        pattern_trips=pattern_trips_list,
        pattern_trip_ids=pattern_trip_ids_list,
        transfers=dict(transfers),
        stop_info=stop_info,
        gtfs_stop_to_app_name=gtfs_stop_to_app_name,
        trip_lookup=trip_lookup,
    )


def _build_gtfs_to_app_mapping(stop_info):
    """Map GTFS stop_ids to Django Station model names using normalized name matching."""
    import re
    mapping = {}

    try:
        from .models import Station
        app_stations = {s.name: s.name for s in Station.objects.all()}
    except Exception:
        return mapping

    def _norm(name):
        n = name.lower().strip()
        n = re.sub(r'\s*station\b.*', '', n)
        n = re.sub(r'\s*-\s*metro\b.*', '', n)
        n = re.sub(r'\s+[a-z]-line\b', '', n)
        # Normalize separators
        n = re.sub(r'\s*-\s*', '/', n)
        n = re.sub(r'\s*/\s*', '/', n)
        # Expand common abbreviations (match gtfs_service._normalize_name)
        n = re.sub(r'\bst\b', 'street', n)
        n = re.sub(r'\bhwy\b', 'highway', n)
        n = re.sub(r'\bblvd\b', 'boulevard', n)
        n = re.sub(r'\bave\b', 'avenue', n)
        n = re.sub(r'\bdr\b', 'drive', n)
        n = re.sub(r'\s+', ' ', n)
        return n.strip()

    app_norm = {}
    for app_name in app_stations:
        app_norm[_norm(app_name)] = app_name

    for sid, info in stop_info.items():
        gtfs_norm = _norm(info["name"])
        if gtfs_norm in app_norm:
            mapping[sid] = app_norm[gtfs_norm]

    return mapping


# ---------------------------------------------------------------------------
# RAPTOR Algorithm
# ---------------------------------------------------------------------------

def raptor_query(index, source_stops, target_stops, departure_sec, service_ids, max_rounds=4):
    """Run RAPTOR from source stops to target stops.

    Args:
        index: RaptorIndex
        source_stops: set of source stop_ids
        target_stops: set of target stop_ids
        departure_sec: departure time in seconds from midnight
        service_ids: set of active service_id strings
        max_rounds: max transfer rounds (default 4)

    Returns:
        list of Journey objects (pareto-optimal: one per round that improved)
    """
    # τ[k][stop] = earliest arrival at stop in round k
    tau = [{}]
    # τ*[stop] = best known arrival across all rounds
    tau_star = {}
    # Parent pointers: (stop, round) -> (boarding_stop, trip_idx, pattern_id, round_boarded)
    # or for transfers: (stop, round) -> ('transfer', from_stop, walk_sec)
    parents = {}
    # Marked stops per round
    marked = set()

    # --- Round 0: Initialize source stops ---
    tau[0] = {}
    for sid in source_stops:
        tau[0][sid] = departure_sec
        tau_star[sid] = departure_sec
        marked.add(sid)

    # Apply transfers from source stops
    _apply_transfers(index, tau[0], tau_star, marked, parents, 0)

    journeys = []
    best_target_arrival = INF

    for k in range(1, max_rounds + 1):
        tau.append({})
        new_marked = set()

        # --- Collect patterns through marked stops ---
        # Q: pattern_id -> earliest boarding position
        Q = {}
        for sid in marked:
            for pid, pos in index.stop_patterns.get(sid, []):
                if pid not in Q or pos < Q[pid]:
                    Q[pid] = pos

        # --- Scan each pattern ---
        for pid, board_pos in Q.items():
            stops = index.pattern_stops[pid]
            trips = index.pattern_trips[pid]
            trip_ids = index.pattern_trip_ids[pid]
            if not trips:
                continue

            current_trip_idx = None  # Index into trips list
            boarding_stop = None

            for pos in range(board_pos, len(stops)):
                sid = stops[pos]

                # Can we board a trip at this stop?
                # We need departure >= tau[k-1][sid] (or tau_star for improvement)
                prev_arrival = tau[k - 1].get(sid)
                if prev_arrival is not None:
                    # Find earliest trip departing >= prev_arrival
                    candidate = _find_earliest_trip(
                        trips, trip_ids, pos, prev_arrival,
                        service_ids, index.trip_lookup,
                    )
                    if candidate is not None:
                        if current_trip_idx is None or candidate < current_trip_idx:
                            current_trip_idx = candidate
                            boarding_stop = sid

                # If riding a trip, check if arrival improves tau_star
                if current_trip_idx is not None:
                    trip_times = trips[current_trip_idx]
                    arr_time = trip_times[pos][0]  # arrival at this stop

                    if arr_time < tau_star.get(sid, INF):
                        tau[k][sid] = arr_time
                        tau_star[sid] = arr_time
                        new_marked.add(sid)
                        parents[(sid, k)] = {
                            "type": "ride",
                            "boarding_stop": boarding_stop,
                            "trip_idx": current_trip_idx,
                            "pattern_id": pid,
                        }

        # --- Apply transfers from newly marked stops ---
        _apply_transfers(index, tau[k], tau_star, new_marked, parents, k)

        # --- Check if any target stop improved ---
        for sid in target_stops:
            arr = tau_star.get(sid, INF)
            if arr < best_target_arrival:
                best_target_arrival = arr
                journey = _reconstruct_journey(
                    index, parents, tau, sid, k, source_stops,
                )
                if journey:
                    journeys.append(journey)

        marked = new_marked
        if not marked:
            break

    return journeys


def _apply_transfers(index, tau_k, tau_star, marked, parents, k):
    """Apply footpath transfers from marked stops."""
    new_arrivals = {}
    for sid in list(marked):
        arr = tau_k.get(sid)
        if arr is None:
            arr = tau_star.get(sid)
        if arr is None:
            continue
        for target_sid, walk_sec in index.transfers.get(sid, []):
            new_arr = arr + walk_sec
            if new_arr < tau_star.get(target_sid, INF):
                new_arrivals[target_sid] = (new_arr, sid, walk_sec)

    for target_sid, (new_arr, from_sid, walk_sec) in new_arrivals.items():
        if new_arr < tau_star.get(target_sid, INF):
            tau_k[target_sid] = new_arr
            tau_star[target_sid] = new_arr
            marked.add(target_sid)
            parents[(target_sid, k)] = {
                "type": "transfer",
                "from_stop": from_sid,
                "walk_sec": walk_sec,
            }


def _find_earliest_trip(trips, trip_ids, pos, min_departure, service_ids, trip_lookup):
    """Find the earliest trip index departing at/after min_departure at position pos."""
    for idx, trip_times in enumerate(trips):
        dep = trip_times[pos][1]  # departure time at this position
        if dep >= min_departure:
            # Check service_id
            tid = trip_ids[idx]
            trip = trip_lookup.get(tid)
            if trip and trip.get("service_id") in service_ids:
                return idx
    return None


# ---------------------------------------------------------------------------
# Journey Reconstruction
# ---------------------------------------------------------------------------

def _reconstruct_journey(index, parents, tau, target_stop, target_round, source_stops):
    """Trace parent pointers back from target to source, building JourneyLegs."""
    legs = []
    current_stop = target_stop
    current_round = target_round

    while current_round >= 0 and current_stop not in source_stops:
        key = (current_stop, current_round)
        if key not in parents:
            # Try previous rounds
            current_round -= 1
            continue

        parent = parents[key]

        if parent["type"] == "transfer":
            from_stop = parent["from_stop"]
            walk_sec = parent["walk_sec"]
            from_name = _get_stop_display_name(index, from_stop)
            to_name = _get_stop_display_name(index, current_stop)

            arr_at_target = tau[current_round].get(current_stop, 0)
            legs.append(JourneyLeg(
                type="transfer",
                line=None,
                from_stop=from_stop,
                from_name=from_name,
                to_stop=current_stop,
                to_name=to_name,
                departure_sec=arr_at_target - walk_sec,
                arrival_sec=arr_at_target,
            ))
            current_stop = from_stop
            # Don't decrement round — the ride that got us to from_stop is in same round
            continue

        # Ride leg
        pid = parent["pattern_id"]
        trip_idx = parent["trip_idx"]
        boarding_stop = parent["boarding_stop"]
        trip_times = index.pattern_trips[pid][trip_idx]
        stops = index.pattern_stops[pid]
        line = index.pattern_line[pid]
        trip_id = index.pattern_trip_ids[pid][trip_idx]

        # Find positions
        board_pos = None
        alight_pos = None
        for pos, sid in enumerate(stops):
            if sid == boarding_stop and board_pos is None:
                board_pos = pos
            if sid == current_stop:
                alight_pos = pos

        if board_pos is None or alight_pos is None:
            break

        dep_sec = trip_times[board_pos][1]
        arr_sec = trip_times[alight_pos][0]
        num_stops = alight_pos - board_pos

        from_name = _get_stop_display_name(index, boarding_stop)
        to_name = _get_stop_display_name(index, current_stop)

        legs.append(JourneyLeg(
            type="ride",
            line=line,
            from_stop=boarding_stop,
            from_name=from_name,
            to_stop=current_stop,
            to_name=to_name,
            departure_sec=dep_sec,
            arrival_sec=arr_sec,
            trip_id=trip_id,
            num_stops=num_stops,
        ))

        current_stop = boarding_stop
        current_round -= 1

    legs.reverse()

    if not legs:
        return None

    # Count transfers (transfer legs)
    num_transfers = sum(1 for leg in legs if leg.type == "transfer")

    return Journey(
        legs=legs,
        departure_sec=legs[0].departure_sec,
        arrival_sec=legs[-1].arrival_sec,
        num_transfers=num_transfers,
    )


def _get_stop_display_name(index, stop_id):
    """Get human-readable station name for a stop_id."""
    # Prefer Django app name mapping
    app_name = index.gtfs_stop_to_app_name.get(stop_id)
    if app_name:
        return app_name
    info = index.stop_info.get(stop_id, {})
    return info.get("name", stop_id)


# ---------------------------------------------------------------------------
# Output Formatters
# ---------------------------------------------------------------------------

def _format_time(seconds):
    """Format seconds-from-midnight to human-readable time string."""
    h = (seconds // 3600) % 24
    m = (seconds % 3600) // 60
    period = "AM" if h < 12 else "PM"
    display_h = h % 12 or 12
    return f"{display_h}:{m:02d} {period}"


def format_journey_for_context(journey, origin_label, destination_label):
    """Format a Journey into human-readable text for Claude's context.

    Returns a string like:
        Metro Transit Route (Maravilla → North Hollywood):
        1. Board E Line at Maravilla to 7th St/Metro Center (departs 2:15 PM, arrives 2:40 PM, 12 stops, ~25 min)
        2. Transfer at 7th St/Metro Center (~3 min walk)
        3. Board B Line at 7th St/Metro Center to North Hollywood (departs 2:43 PM, arrives 2:55 PM, 6 stops, ~12 min)
        Total: 40 min, 1 transfer(s)
    """
    lines = [f"Metro Transit Route ({origin_label} → {destination_label}):"]
    step_num = 0

    for leg in journey.legs:
        step_num += 1
        if leg.type == "ride":
            duration = (leg.arrival_sec - leg.departure_sec) // 60
            lines.append(
                f"{step_num}. Board {leg.line} Line at {leg.from_name} to {leg.to_name} "
                f"(departs {_format_time(leg.departure_sec)}, arrives {_format_time(leg.arrival_sec)}, "
                f"{leg.num_stops} stops, ~{duration} min)"
            )
        elif leg.type == "transfer":
            walk_min = max(1, (leg.arrival_sec - leg.departure_sec) // 60)
            lines.append(
                f"{step_num}. Transfer at {leg.from_name} (~{walk_min} min walk)"
            )

    total_min = (journey.arrival_sec - journey.departure_sec) // 60
    lines.append(f"Total: {total_min} min, {journey.num_transfers} transfer(s)")
    return "\n".join(lines)


def build_route_block(journey, index):
    """Build a JSON route block matching the existing [ROUTE] format.

    Returns a JSON string like:
        {"steps":[{"type":"ride","line":"E","from":"Maravilla","to":"7th St/Metro Center"},
                  {"type":"transfer","line":null,"from":"7th St/Metro Center","to":"7th St/Metro Center"},
                  {"type":"ride","line":"B","from":"7th St/Metro Center","to":"North Hollywood"}]}
    """
    import json
    steps = []
    ride_legs = [leg for leg in journey.legs if leg.type == "ride"]

    for i, leg in enumerate(journey.legs):
        if leg.type == "ride":
            from_name = _get_app_name_or_display(index, leg.from_stop, leg.from_name)
            to_name = _get_app_name_or_display(index, leg.to_stop, leg.to_name)
            steps.append({
                "type": "ride",
                "line": leg.line,
                "from": from_name,
                "to": to_name,
            })
        elif leg.type == "transfer":
            from_name = _get_app_name_or_display(index, leg.from_stop, leg.from_name)
            to_name = _get_app_name_or_display(index, leg.to_stop, leg.to_name)
            steps.append({
                "type": "transfer",
                "line": None,
                "from": from_name,
                "to": to_name,
            })

    if not steps:
        return None

    return json.dumps({"steps": steps})


def _get_app_name_or_display(index, stop_id, fallback_name):
    """Get Django app station name, falling back to display name."""
    app_name = index.gtfs_stop_to_app_name.get(stop_id)
    return app_name if app_name else fallback_name
