"""
GTFS service for LA Metro rail schedule data.
Downloads, caches, and queries GTFS static schedule to provide
upcoming train arrivals for any station.
"""

import io
import re
import threading
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta

import requests
from zoneinfo import ZoneInfo

LA_TZ = ZoneInfo("America/Los_Angeles")

GTFS_URL = "https://gitlab.com/LACMTA/gtfs_rail/-/raw/master/gtfs_rail.zip"
CACHE_TTL = 4 * 3600  # 4 hours

# Route ID → line letter mapping (built dynamically, but these are the known ones)
ROUTE_LINE_MAP = {
    "801": "A",
    "802": "B",
    "803": "C",
    "804": "D",
    "806": "E",
    "805": "G",
    "807": "K",
}

LINE_COLORS = {
    "A": "#0072bc",
    "B": "#e3242b",
    "C": "#58a738",
    "D": "#a05da5",
    "E": "#fdb913",
    "G": "#f58220",
    "K": "#e96bb0",
}

# Thread-safe cache
_cache_lock = threading.Lock()
_cache = {
    "data": None,
    "timestamp": 0,
}


def _download_gtfs():
    """Download and parse GTFS ZIP into memory."""
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(GTFS_URL, headers=headers, timeout=30)
    r.raise_for_status()
    return zipfile.ZipFile(io.BytesIO(r.content))


def _read_csv(zf, filename):
    """Parse a CSV file from the GTFS ZIP into a list of dicts."""
    lines = zf.read(filename).decode("utf-8-sig").splitlines()
    headers = lines[0].strip().split(",")
    rows = []
    for line in lines[1:]:
        line = line.strip()
        if line:
            rows.append(dict(zip(headers, line.split(","))))
    return rows


def _build_cache_data(zf):
    """Parse all GTFS CSVs and build indexed lookup structures."""
    trips = _read_csv(zf, "trips.txt")
    stop_times = _read_csv(zf, "stop_times.txt")
    calendar = _read_csv(zf, "calendar.txt")
    calendar_dates = _read_csv(zf, "calendar_dates.txt")
    stops = _read_csv(zf, "stops.txt")
    routes = _read_csv(zf, "routes.txt")

    # Build route_id → line letter map from routes.txt
    route_line = dict(ROUTE_LINE_MAP)
    for route in routes:
        rid = route.get("route_id", "")
        short = route.get("route_short_name", "")
        if rid and short and rid not in route_line:
            route_line[rid] = short

    # Build trip lookup: trip_id → trip dict (with line letter added)
    trip_lookup = {}
    for t in trips:
        tid = t.get("trip_id", "")
        rid = t.get("route_id", "")
        t["_line"] = route_line.get(rid, "")
        trip_lookup[tid] = t

    # Index stop_times by stop_id for O(1) lookup
    # Also index by trip_id to find terminal stops for headsign generation
    stop_times_index = defaultdict(list)
    trip_stop_times = defaultdict(list)
    for st in stop_times:
        sid = st.get("stop_id", "")
        stop_times_index[sid].append(st)
        trip_stop_times[st.get("trip_id", "")].append(st)

    # Build stop lookup: stop_id → stop dict
    # Also build parent → children mapping
    stop_lookup = {}
    parent_children = defaultdict(list)
    for s in stops:
        sid = s.get("stop_id", "")
        stop_lookup[sid] = s
        parent = s.get("parent_station", "")
        if parent:
            parent_children[parent].append(sid)

    # Pre-compute headsigns for trips with empty trip_headsign
    # by finding the last stop name in each trip's stop sequence
    for tid, sts in trip_stop_times.items():
        trip = trip_lookup.get(tid)
        if trip and not trip.get("trip_headsign"):
            sts_sorted = sorted(sts, key=lambda x: int(x.get("stop_sequence", 0)))
            if sts_sorted:
                last_stop_id = sts_sorted[-1].get("stop_id", "")
                last_stop = stop_lookup.get(last_stop_id, {})
                # Use parent station name if available, otherwise use stop name
                parent_id = last_stop.get("parent_station", "")
                if parent_id and parent_id in stop_lookup:
                    name = stop_lookup[parent_id].get("stop_name", "")
                else:
                    name = last_stop.get("stop_name", "")
                # Clean up the name — remove "Station" suffix, line info
                name = re.sub(r'\s*Station\b.*', '', name)
                name = re.sub(r'\s*-\s*Metro\b.*', '', name)
                name = re.sub(r'\s+[A-Z]-Line\b', '', name)
                trip["trip_headsign"] = name.strip()

    # Build name → stop_ids mapping for station name matching
    # Normalize names for fuzzy matching
    name_to_stop_ids = defaultdict(set)
    for s in stops:
        sid = s.get("stop_id", "")
        name = s.get("stop_name", "")
        normalized = _normalize_name(name)
        name_to_stop_ids[normalized].add(sid)
        # Also add parent's children
        parent = s.get("parent_station", "")
        if parent:
            name_to_stop_ids[normalized].add(parent)

    return {
        "trip_lookup": trip_lookup,
        "stop_times_index": dict(stop_times_index),
        "trip_stop_times": dict(trip_stop_times),
        "calendar": calendar,
        "calendar_dates": calendar_dates,
        "stop_lookup": stop_lookup,
        "parent_children": dict(parent_children),
        "name_to_stop_ids": dict(name_to_stop_ids),
        "route_line": route_line,
    }


def _normalize_name(name):
    """Normalize a station name for matching."""
    name = name.lower().strip()
    # Remove "station" suffix and everything after it (e.g. "Station - Metro A-Line")
    name = re.sub(r'\s*station\b.*', '', name)
    # Normalize separators: replace " - " with "/", normalize spaces around "/"
    name = re.sub(r'\s*-\s*', '/', name)
    name = re.sub(r'\s*/\s*', '/', name)
    # Remove line suffixes like "e/line", "a/line", "k/line"
    name = re.sub(r'\s*[a-z]/line\b', '', name)
    # Expand common abbreviations
    name = re.sub(r'\bst\b', 'street', name)
    name = re.sub(r'\bhwy\b', 'highway', name)
    name = re.sub(r'\bblvd\b', 'boulevard', name)
    name = re.sub(r'\bave\b', 'avenue', name)
    name = re.sub(r'\bdr\b', 'drive', name)
    # Remove extra whitespace
    name = re.sub(r'\s+', ' ', name)
    return name


def _get_cached_data():
    """Get cached GTFS data, downloading if stale or missing."""
    with _cache_lock:
        now = time.time()
        if _cache["data"] is not None and (now - _cache["timestamp"]) < CACHE_TTL:
            return _cache["data"]

    # Download outside the lock to avoid blocking other threads
    zf = _download_gtfs()
    data = _build_cache_data(zf)

    with _cache_lock:
        _cache["data"] = data
        _cache["timestamp"] = time.time()

    return data


def _get_service_ids_for_today(calendar, calendar_dates):
    """Determine which service_ids are active today."""
    today = datetime.now(LA_TZ)
    day_name = today.strftime("%A").lower()
    today_str = today.strftime("%Y%m%d")
    active = set()

    for row in calendar:
        if row.get("start_date", "") <= today_str <= row.get("end_date", ""):
            if row.get(day_name, "0") == "1":
                active.add(row["service_id"])

    for row in calendar_dates:
        if row.get("date") == today_str:
            if row.get("exception_type") == "1":
                active.add(row["service_id"])
            elif row.get("exception_type") == "2":
                active.discard(row["service_id"])

    return active


def _find_stop_ids_for_station(data, station_name):
    """Find all GTFS stop_ids that match a frontend station name."""
    normalized = _normalize_name(station_name)

    # Direct match
    if normalized in data["name_to_stop_ids"]:
        stop_ids = set(data["name_to_stop_ids"][normalized])
        # Also include children of any parent stations
        for sid in list(stop_ids):
            if sid in data["parent_children"]:
                stop_ids.update(data["parent_children"][sid])
        return stop_ids

    # Fuzzy: try matching with contained substrings
    best_match = None
    best_score = 0
    for gtfs_name, sids in data["name_to_stop_ids"].items():
        # Check if normalized query is contained in GTFS name or vice versa
        if normalized in gtfs_name or gtfs_name in normalized:
            score = len(set(normalized.split()) & set(gtfs_name.split()))
            if score > best_score:
                best_score = score
                best_match = sids

    if best_match:
        stop_ids = set(best_match)
        for sid in list(stop_ids):
            if sid in data["parent_children"]:
                stop_ids.update(data["parent_children"][sid])
        return stop_ids

    # Try matching individual words (at least 2 words must match)
    query_words = set(normalized.split())
    for gtfs_name, sids in data["name_to_stop_ids"].items():
        gtfs_words = set(gtfs_name.split())
        overlap = query_words & gtfs_words
        if len(overlap) >= min(2, len(query_words)):
            stop_ids = set(sids)
            for sid in list(stop_ids):
                if sid in data["parent_children"]:
                    stop_ids.update(data["parent_children"][sid])
            return stop_ids

    return set()


def get_arrivals(station_name, limit=10):
    """
    Get upcoming train arrivals for a station.

    Returns a list of dicts with keys:
        time, minutes_away, headsign, line, color
    """
    try:
        data = _get_cached_data()
    except Exception:
        return []

    service_ids = _get_service_ids_for_today(data["calendar"], data["calendar_dates"])
    if not service_ids:
        return []

    stop_ids = _find_stop_ids_for_station(data, station_name)
    if not stop_ids:
        return []

    now = datetime.now(LA_TZ)
    base = now.replace(hour=0, minute=0, second=0, microsecond=0)

    seen = set()
    arrivals = []

    for sid in stop_ids:
        for st in data["stop_times_index"].get(sid, []):
            trip = data["trip_lookup"].get(st.get("trip_id"))
            if not trip:
                continue
            if trip.get("service_id") not in service_ids:
                continue

            time_str = st.get("arrival_time") or st.get("departure_time", "")
            if not time_str:
                continue

            try:
                h, m, s = map(int, time_str.split(":"))
                arrival_dt = base + timedelta(hours=h, minutes=m, seconds=s)
                mins = (arrival_dt - now).total_seconds() / 60
                if not (-2 <= mins <= 180):
                    continue

                headsign = trip.get("trip_headsign", "")
                line = trip.get("_line", "")

                # Deduplicate: same minute + same headsign + same line
                dedup_key = (arrival_dt.strftime("%H:%M"), headsign, line)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                arrivals.append({
                    "time": arrival_dt.strftime("%I:%M %p").lstrip("0"),
                    "minutes_away": max(0, int(mins)),
                    "headsign": headsign,
                    "line": line,
                    "color": LINE_COLORS.get(line, "#888"),
                    "_sort": arrival_dt,
                })
            except ValueError:
                continue

    arrivals.sort(key=lambda x: x["_sort"])

    # Remove internal sort key before returning
    for a in arrivals:
        del a["_sort"]

    return arrivals[:limit]


def _parse_gtfs_time(time_str):
    """Parse a GTFS time string (HH:MM:SS, may exceed 24h) into total seconds from midnight."""
    h, m, s = map(int, time_str.split(":"))
    return h * 3600 + m * 60 + s


def get_travel_times(origin_names, destination_name):
    """
    Compute travel times from multiple origin stations to one destination.

    Returns a dict: {origin_name: {"minutes": int, "line": str}} or None per origin if no route found.
    Only considers direct (same-trip) connections — no transfers.
    """
    try:
        data = _get_cached_data()
    except Exception:
        return {}

    service_ids = _get_service_ids_for_today(data["calendar"], data["calendar_dates"])
    if not service_ids:
        return {}

    dest_stop_ids = _find_stop_ids_for_station(data, destination_name)
    if not dest_stop_ids:
        return {}

    results = {}

    for origin_name in origin_names:
        origin_stop_ids = _find_stop_ids_for_station(data, origin_name)
        if not origin_stop_ids:
            results[origin_name] = None
            continue

        # Find trips that pass through both origin and destination
        best_time = None
        best_line = None

        # Build set of trip_ids that serve the origin
        origin_trips = set()
        for sid in origin_stop_ids:
            for st in data["stop_times_index"].get(sid, []):
                tid = st.get("trip_id", "")
                trip = data["trip_lookup"].get(tid)
                if trip and trip.get("service_id") in service_ids:
                    origin_trips.add(tid)

        # Check each origin trip for a stop at the destination
        for tid in origin_trips:
            trip_stops = data["trip_stop_times"].get(tid, [])
            origin_time = None
            dest_time = None

            for st in trip_stops:
                sid = st.get("stop_id", "")
                t_str = st.get("arrival_time") or st.get("departure_time", "")
                if not t_str:
                    continue
                try:
                    t_sec = _parse_gtfs_time(t_str)
                except ValueError:
                    continue

                if sid in origin_stop_ids and (origin_time is None or t_sec < origin_time):
                    origin_time = t_sec
                if sid in dest_stop_ids and (dest_time is None or t_sec > dest_time):
                    dest_time = t_sec

            if origin_time is not None and dest_time is not None and dest_time > origin_time:
                travel_min = (dest_time - origin_time) // 60
                if best_time is None or travel_min < best_time:
                    best_time = travel_min
                    trip = data["trip_lookup"].get(tid)
                    best_line = trip.get("_line", "") if trip else ""

        if best_time is not None:
            results[origin_name] = {"minutes": best_time, "line": best_line}
        else:
            results[origin_name] = None

    return results


def get_schedule_at_station(station_name, target_time_str, direction_station=None, limit=5):
    """
    Get train schedule at a station around a target time.

    target_time_str: "HH:MM" in 24h format (LA time), e.g. "14:00"
    direction_station: optional station name to filter trains heading toward that station

    Returns list of dicts: {time, line, headsign, color}
    """
    try:
        data = _get_cached_data()
    except Exception:
        return []

    service_ids = _get_service_ids_for_today(data["calendar"], data["calendar_dates"])
    if not service_ids:
        return []

    stop_ids = _find_stop_ids_for_station(data, station_name)
    if not stop_ids:
        return []

    # Parse target time
    try:
        th, tm = map(int, target_time_str.split(":"))
        target_sec = th * 3600 + tm * 60
    except ValueError:
        return []

    # If direction_station specified, find its stop_ids to filter trips
    dir_stop_ids = None
    if direction_station:
        dir_stop_ids = _find_stop_ids_for_station(data, direction_station)

    window = 60 * 60  # 1 hour window around target time
    candidates = []

    for sid in stop_ids:
        for st in data["stop_times_index"].get(sid, []):
            trip = data["trip_lookup"].get(st.get("trip_id"))
            if not trip:
                continue
            if trip.get("service_id") not in service_ids:
                continue

            time_str = st.get("arrival_time") or st.get("departure_time", "")
            if not time_str:
                continue

            try:
                t_sec = _parse_gtfs_time(time_str)
            except ValueError:
                continue

            # Within window of target time (before and after)
            if abs(t_sec - target_sec) > window:
                continue

            # If direction filter, check this trip also stops at the direction station AFTER this stop
            if dir_stop_ids:
                trip_stops = data["trip_stop_times"].get(st.get("trip_id", ""), [])
                passes_dir = False
                for ts in trip_stops:
                    ts_sid = ts.get("stop_id", "")
                    ts_time = ts.get("arrival_time") or ts.get("departure_time", "")
                    if ts_sid in dir_stop_ids and ts_time:
                        try:
                            if _parse_gtfs_time(ts_time) > t_sec:
                                passes_dir = True
                                break
                        except ValueError:
                            continue
                if not passes_dir:
                    continue

            h, m, s = map(int, time_str.split(":"))
            # Normalize hours > 23 for display
            display_h = h % 24
            period = "AM" if display_h < 12 else "PM"
            display_h = display_h % 12 or 12

            line = trip.get("_line", "")
            candidates.append({
                "time": f"{display_h}:{m:02d} {period}",
                "line": line,
                "headsign": trip.get("trip_headsign", ""),
                "color": LINE_COLORS.get(line, "#888"),
                "_sort_sec": t_sec,
            })

    # Sort by closeness to target time, preferring trains just before target
    candidates.sort(key=lambda x: (x["_sort_sec"] > target_sec, abs(x["_sort_sec"] - target_sec)))

    # Deduplicate
    seen = set()
    results = []
    for c in candidates:
        key = (c["time"], c["line"], c["headsign"])
        if key not in seen:
            seen.add(key)
            results.append({k: v for k, v in c.items() if k != "_sort_sec"})
        if len(results) >= limit:
            break

    return results
