"""
LA Metro A Line – Next trains from Downtown Long Beach → Pomona
Uses LA Metro's GTFS Rail static schedule (no API key needed).

pip install requests
python metro_arrivals.py
"""

import requests
import zipfile
import io
from datetime import datetime, timedelta

GTFS_URL = "https://gitlab.com/LACMTA/gtfs_rail/-/raw/master/gtfs_rail.zip"

# Known values from previous run — hardcoded for speed
ROUTE_ID  = "801"    # A Line
STOP_ID   = "80101"  # Downtown Long Beach Station (main platform)


def download_gtfs() -> zipfile.ZipFile:
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(GTFS_URL, headers=headers, timeout=30)
    r.raise_for_status()
    return zipfile.ZipFile(io.BytesIO(r.content))


def read_csv(zf: zipfile.ZipFile, filename: str) -> list[dict]:
    lines   = zf.read(filename).decode("utf-8-sig").splitlines()
    headers = lines[0].strip().split(",")
    return [
        dict(zip(headers, line.strip().split(",")))
        for line in lines[1:] if line.strip()
    ]


def get_service_ids_for_today(calendar, calendar_dates) -> set[str]:
    today     = datetime.now()
    day_name  = today.strftime("%A").lower()
    today_str = today.strftime("%Y%m%d")
    active    = set()

    for row in calendar:
        if row["start_date"] <= today_str <= row["end_date"]:
            if row.get(day_name, "0") == "1":
                active.add(row["service_id"])

    for row in calendar_dates:
        if row.get("date") == today_str:
            if row.get("exception_type") == "1":
                active.add(row["service_id"])
            elif row.get("exception_type") == "2":
                active.discard(row["service_id"])

    return active


def is_pomona_bound(headsign: str, direction_id: str) -> bool:
    """
    A Line direction_id=0 runs northbound/eastbound toward Pomona/Azusa.
    direction_id=1 runs southbound/westbound toward Long Beach (wrong way).
    We also check the headsign for Pomona keywords as a backup.
    """
    headsign_lower = headsign.lower()

    # Headsign keywords for Pomona-bound trains
    pomona_keywords = ["pomona", "azusa", "claremont", "montclair", "glendora",
                       "san dimas", "la verne", "apu", "citrus"]

    if any(kw in headsign_lower for kw in pomona_keywords):
        return True

    # direction_id=0 is the outbound/eastbound direction (away from Long Beach)
    if direction_id == "0":
        return True

    return False


def find_pomona_arrivals(trips, stop_times, service_ids) -> list[dict]:
    # Build valid trip lookup: A Line, running today
    valid_trips = {
        t["trip_id"]: t
        for t in trips
        if t.get("route_id") == ROUTE_ID and t.get("service_id") in service_ids
    }

    now  = datetime.now()
    base = now.replace(hour=0, minute=0, second=0, microsecond=0)

    seen_times = set()   # deduplicate by (time_str, headsign)
    arrivals   = []

    for row in stop_times:
        if row.get("stop_id") != STOP_ID:
            continue
        trip = valid_trips.get(row.get("trip_id"))
        if not trip:
            continue

        headsign     = trip.get("trip_headsign", "")
        direction_id = trip.get("direction_id", "")

        if not is_pomona_bound(headsign, direction_id):
            continue

        time_str = row.get("arrival_time") or row.get("departure_time", "")
        if not time_str:
            continue

        try:
            h, m, s    = map(int, time_str.split(":"))
            arrival_dt = base + timedelta(hours=h, minutes=m, seconds=s)
            mins       = (arrival_dt - now).total_seconds() / 60
            if not (-2 <= mins <= 180):   # next 3 hours
                continue

            # Deduplicate — same minute + same headsign = same train
            dedup_key = (arrival_dt.strftime("%H:%M"), headsign)
            if dedup_key in seen_times:
                continue
            seen_times.add(dedup_key)

            arrivals.append({
                "arrival_time": arrival_dt,
                "minutes_away": max(0, int(mins)),
                "trip_id":      row["trip_id"],
                "headsign":     headsign,
                "direction_id": direction_id,
            })
        except ValueError:
            continue

    arrivals.sort(key=lambda x: x["arrival_time"])
    return arrivals


def main():
    print("=" * 62)
    print("  LA Metro A Line — Trains to Pomona")
    print("  📍 You are at: Downtown Long Beach Station")
    print("=" * 62)
    print(f"  {datetime.now().strftime('%A %B %d, %Y  %I:%M:%S %p')}")
    print("=" * 62)

    try:
        print("\n  Downloading GTFS schedule...")
        zf = download_gtfs()

        trips          = read_csv(zf, "trips.txt")
        stop_times     = read_csv(zf, "stop_times.txt")
        calendar       = read_csv(zf, "calendar.txt")
        calendar_dates = read_csv(zf, "calendar_dates.txt")

        service_ids = get_service_ids_for_today(calendar, calendar_dates)
        arrivals    = find_pomona_arrivals(trips, stop_times, service_ids)

        print()
        print("=" * 62)
        if not arrivals:
            print("  No Pomona-bound trains in the next 3 hours.")
            print("  (Service may have ended for the night.)")
        else:
            print(f"  Next Pomona-bound A Line train(s):\n")
            for i, a in enumerate(arrivals, 1):
                t     = a["arrival_time"].strftime("%I:%M %p")
                mins  = a["minutes_away"]
                label = "Boarding now" if mins == 0 else f"in {mins} min"
                head  = a["headsign"] if a["headsign"] else "toward Pomona"
                print(f"  [{i:>2}]  {t}   {label:<14}  → {head}")
        print("=" * 62)

    except Exception as e:
        print(f"\n  ❌ {type(e).__name__}: {e}")
        print("=" * 62)


if __name__ == "__main__":
    main()