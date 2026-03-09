"""
Management command to update station coordinates using Google Places API.

Usage:
  python manage.py update_station_coords                  # dry-run: shows changes
  python manage.py update_station_coords --apply          # applies to DB
  python manage.py update_station_coords --apply --seed   # also updates seed_stations.py
"""

import math
import time

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from ratemetroapp.models import Station


# Bounding box for LA Metro service area (loose)
LA_BOUNDS = {
    "south": 33.6,
    "west": -118.7,
    "north": 34.4,
    "east": -117.7,
}

# Mapping of line codes to line names for better search queries
LINE_NAMES = {
    "A": "A Line Blue Line",
    "B": "B Line Red Line",
    "C": "C Line Green Line",
    "D": "D Line Purple Line",
    "E": "E Line Expo Line",
    "G": "G Line Orange Line",
    "K": "K Line Crenshaw Line",
    "J": "J Line Silver Line",
    "L": "Gold Line",
}

# Max allowed shift in meters — anything beyond this is likely a wrong result
MAX_SHIFT_METERS = 3000


def search_station(station_name, api_key, line_hint=None):
    """
    Query Google Places Text Search for a metro station's coordinates.

    Args:
        station_name: The station name
        api_key: Google API key
        line_hint: Optional line code (e.g. "A") to disambiguate generic names

    Returns:
        ((lat, lng), display_name) or (None, error_message)
    """
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.location,places.displayName,places.formattedAddress",
    }

    # Build a specific query to avoid ambiguous results
    line_str = ""
    if line_hint and line_hint in LINE_NAMES:
        line_str = f" {LINE_NAMES[line_hint]}"
    query = f"{station_name} Metro Station{line_str} Los Angeles"

    body = {
        "textQuery": query,
        "locationBias": {
            "rectangle": {
                "low": {"latitude": LA_BOUNDS["south"], "longitude": LA_BOUNDS["west"]},
                "high": {"latitude": LA_BOUNDS["north"], "longitude": LA_BOUNDS["east"]},
            }
        },
        "maxResultCount": 1,
    }

    try:
        resp = requests.post(url, json=body, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return None, str(e)

    places = data.get("places", [])
    if not places:
        return None, "no results"

    loc = places[0].get("location", {})
    lat = loc.get("latitude")
    lng = loc.get("longitude")
    name = places[0].get("displayName", {}).get("text", "")

    if lat is None or lng is None:
        return None, "no location in result"

    # Sanity check: must be within LA metro area
    if not (LA_BOUNDS["south"] <= lat <= LA_BOUNDS["north"] and
            LA_BOUNDS["west"] <= lng <= LA_BOUNDS["east"]):
        return None, f"result outside LA bounds: {lat}, {lng} ({name})"

    return (lat, lng), name


class Command(BaseCommand):
    help = "Update station coordinates from Google Places API"

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually update the database (default is dry-run)",
        )
        parser.add_argument(
            "--seed",
            action="store_true",
            help="Also update seed_stations.py with new coordinates",
        )
        parser.add_argument(
            "--station",
            type=str,
            help="Only update a single station (by name)",
        )
        parser.add_argument(
            "--max-shift",
            type=int,
            default=MAX_SHIFT_METERS,
            help=f"Max allowed shift in meters (default: {MAX_SHIFT_METERS})",
        )

    def handle(self, *args, **options):
        api_key = settings.GOOGLE_MAPS_API_KEY
        if not api_key:
            self.stderr.write(self.style.ERROR("GOOGLE_MAPS_API_KEY not set in settings"))
            return

        apply_changes = options["apply"]
        update_seed = options["seed"]
        single_station = options.get("station")
        max_shift = options["max_shift"]

        if single_station:
            stations = Station.objects.filter(name=single_station).prefetch_related("lines")
            if not stations.exists():
                self.stderr.write(self.style.ERROR(f"Station '{single_station}' not found"))
                return
        else:
            stations = Station.objects.all().prefetch_related("lines").order_by("name")

        self.stdout.write(f"\nQuerying Google Places API for {stations.count()} stations...")
        self.stdout.write(f"Max shift threshold: {max_shift}m\n")
        if not apply_changes:
            self.stdout.write(self.style.WARNING("DRY RUN — use --apply to save changes\n"))

        updates = {}  # name -> (new_lat, new_lng)
        skipped = []
        too_far = []
        errors = []

        for station in stations:
            # Get the primary line for this station to help disambiguate
            line_codes = list(station.lines.values_list("code", flat=True))
            line_hint = line_codes[0] if line_codes else None

            result, info = search_station(station.name, api_key, line_hint=line_hint)

            if result is None:
                errors.append((station.name, info))
                self.stdout.write(self.style.ERROR(f"  ERR   {station.name}: {info}"))
                time.sleep(0.2)
                continue

            new_lat, new_lng = result
            old_lat, old_lng = station.latitude, station.longitude
            dist_m = _haversine_meters(old_lat, old_lng, new_lat, new_lng)

            if dist_m < 5:
                skipped.append(station.name)
                self.stdout.write(f"  OK    {station.name} (unchanged, <5m)")
            elif dist_m > max_shift:
                too_far.append((station.name, dist_m, info))
                self.stdout.write(
                    self.style.WARNING(
                        f"  SKIP  {station.name}: {dist_m:.0f}m shift exceeds "
                        f"{max_shift}m threshold — Google: {info}"
                    )
                )
            else:
                updates[station.name] = (new_lat, new_lng)
                arrow = ">>>" if dist_m > 500 else " > "
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  {arrow} {station.name}: "
                        f"({old_lat:.6f}, {old_lng:.6f}) → ({new_lat:.6f}, {new_lng:.6f})  "
                        f"[{dist_m:.0f}m] — Google: {info}"
                    )
                )

            # Rate limit: ~5 requests/sec to stay well under quota
            time.sleep(0.2)

        # Summary
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"  Total stations: {stations.count()}")
        self.stdout.write(self.style.SUCCESS(f"  Will update:  {len(updates)}"))
        self.stdout.write(f"  No change:    {len(skipped)}")
        self.stdout.write(self.style.WARNING(f"  Too far:      {len(too_far)}"))
        self.stdout.write(self.style.ERROR(f"  Errors:       {len(errors)}"))
        self.stdout.write(f"{'='*60}\n")

        if too_far:
            self.stdout.write("\nSkipped (shift exceeded threshold):")
            for name, dist, gname in too_far:
                self.stdout.write(f"  - {name}: {dist:.0f}m (Google: {gname})")
            self.stdout.write("")

        if not updates:
            self.stdout.write("No changes to apply.")
            return

        if apply_changes:
            # Update database
            count = 0
            for name, (lat, lng) in updates.items():
                Station.objects.filter(name=name).update(latitude=lat, longitude=lng)
                count += 1
            self.stdout.write(self.style.SUCCESS(f"\nUpdated {count} stations in database."))

            if update_seed:
                self._update_seed_file(updates)
                self.stdout.write(self.style.SUCCESS("Updated seed_stations.py"))

            self.stdout.write(self.style.WARNING(
                "\nRemember to also update the metroStations array in map.html!"
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f"\nRun with --apply to save {len(updates)} changes to the database."
            ))

    def _update_seed_file(self, updates):
        """Update coordinates in seed_stations.py."""
        import re
        seed_path = "ratemetroapp/management/commands/seed_stations.py"
        with open(seed_path, "r") as f:
            content = f.read()

        for name, (new_lat, new_lng) in updates.items():
            # Match the station dict entry and replace lat/lng values
            escaped = re.escape(name)
            pattern = (
                rf'("name":\s*"{escaped}"\s*,'
                rf'\s*"lines":\s*\[[^\]]*\]\s*,'
                rf'\s*"lat":\s*)([\d.-]+)'
                rf'(\s*,\s*"lng":\s*)([\d.-]+)'
            )
            replacement = rf'\g<1>{new_lat:.6f}\g<3>{new_lng:.6f}'
            content = re.sub(pattern, replacement, content)

        with open(seed_path, "w") as f:
            f.write(content)


def _haversine_meters(lat1, lng1, lat2, lng2):
    """Calculate distance in meters between two coordinates."""
    R = 6371000  # Earth radius in meters
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))
