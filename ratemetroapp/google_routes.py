"""
Google Routes API service for real transit directions.
Queries the Routes API v2 for transit routing between stations/addresses.
"""

import requests


def get_transit_route(origin, destination, api_key):
    """
    Get transit directions from origin to destination using Google Routes API.

    Args:
        origin: Station name (str) or dict with lat/lng keys
        destination: Station name (str) or dict with lat/lng keys
        api_key: Google Maps API key

    Returns:
        Dict with total_duration and steps list, or None on error.
    """
    url = "https://routes.googleapis.com/directions/v2:computeRoutes"

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "routes.legs.steps.transitDetails,"
            "routes.legs.steps.travelMode,"
            "routes.legs.steps.staticDuration,"
            "routes.legs.steps.localizedValues,"
            "routes.legs.duration,"
            "routes.duration"
        ),
    }

    body = {
        "origin": _build_waypoint(origin),
        "destination": _build_waypoint(destination),
        "travelMode": "TRANSIT",
        "transitPreferences": {
            "routingPreference": "FEWER_TRANSFERS",
        },
    }

    try:
        resp = requests.post(url, json=body, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    return _parse_response(data)


def _build_waypoint(location):
    """Build a Routes API waypoint from a name string or lat/lng dict."""
    if isinstance(location, dict) and "lat" in location and "lng" in location:
        return {
            "location": {
                "latLng": {
                    "latitude": float(location["lat"]),
                    "longitude": float(location["lng"]),
                }
            }
        }
    # Treat as address string — append LA context for better geocoding
    address = str(location)
    if "los angeles" not in address.lower() and "la" not in address.lower():
        address += ", Los Angeles, CA"
    return {"address": address}


def _parse_response(data):
    """Parse Google Routes API response into a structured dict."""
    routes = data.get("routes", [])
    if not routes:
        return None

    route = routes[0]

    # Total duration
    duration_str = route.get("duration", "0s")
    total_seconds = _parse_duration(duration_str)
    total_minutes = round(total_seconds / 60)

    steps = []
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            parsed = _parse_step(step)
            if parsed:
                steps.append(parsed)

    if not steps:
        return None

    return {
        "total_duration": total_minutes,
        "steps": steps,
    }


def _parse_step(step):
    """Parse a single route step into a structured dict."""
    travel_mode = step.get("travelMode", "")
    duration_str = step.get("staticDuration", "0s")
    duration_minutes = round(_parse_duration(duration_str) / 60)

    localized = step.get("localizedValues", {})

    if travel_mode == "TRANSIT":
        transit = step.get("transitDetails", {})
        stop_details = transit.get("stopDetails", {})

        departure_stop = stop_details.get("departureStop", {})
        arrival_stop = stop_details.get("arrivalStop", {})

        departure_time = transit.get("localizedValues", {}).get("departureTime", {}).get("time", {}).get("text", "")
        arrival_time = transit.get("localizedValues", {}).get("arrivalTime", {}).get("time", {}).get("text", "")

        transit_line = transit.get("transitLine", {})
        line_name = transit_line.get("nameShort") or transit_line.get("name", "")
        vehicle_type = transit_line.get("vehicle", {}).get("type", "")

        num_stops = transit.get("stopCount", 0)

        return {
            "type": "ride",
            "line": line_name,
            "vehicle_type": vehicle_type,
            "from_station": departure_stop.get("name", ""),
            "to_station": arrival_stop.get("name", ""),
            "departure_time": departure_time,
            "arrival_time": arrival_time,
            "duration_minutes": duration_minutes,
            "num_stops": num_stops,
        }

    elif travel_mode == "WALK":
        return {
            "type": "walk",
            "duration_minutes": duration_minutes,
            "distance": localized.get("staticDuration", {}).get("text", ""),
        }

    return None


def _parse_duration(duration_str):
    """Parse a Google duration string like '1234s' into seconds."""
    if not duration_str:
        return 0
    try:
        return int(duration_str.rstrip("s"))
    except (ValueError, AttributeError):
        return 0


def get_walking_route(origin, destination, api_key):
    """
    Get walking directions from origin to destination using Google Routes API.

    Args:
        origin: dict with lat/lng keys or address string
        destination: dict with lat/lng keys or address string
        api_key: Google Maps API key

    Returns:
        Dict with duration_minutes and distance_text, or None on error.
    """
    url = "https://routes.googleapis.com/directions/v2:computeRoutes"

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "routes.duration,"
            "routes.distanceMeters,"
            "routes.localizedValues"
        ),
    }

    body = {
        "origin": _build_waypoint(origin),
        "destination": _build_waypoint(destination),
        "travelMode": "WALK",
    }

    try:
        resp = requests.post(url, json=body, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    routes = data.get("routes", [])
    if not routes:
        return None

    route = routes[0]
    duration_seconds = _parse_duration(route.get("duration", "0s"))
    duration_minutes = round(duration_seconds / 60)
    distance_meters = route.get("distanceMeters", 0)

    # Convert to miles
    distance_miles = round(distance_meters / 1609.34, 1)

    localized = route.get("localizedValues", {})
    distance_text = localized.get("distance", {}).get("text", f"{distance_miles} mi")

    return {
        "duration_minutes": duration_minutes,
        "distance_text": distance_text,
        "distance_miles": distance_miles,
    }


def format_route_for_context(route_data, origin_name, destination_name):
    """
    Format a parsed route into a human-readable string for the AI context.

    Returns a string like:
        Google Transit Route (Maravilla → North Hollywood):
        1. Walk 3 min to Maravilla station
        2. Board E Line to 7th St/Metro Center (departs 2:15 PM, arrives 2:40 PM, 12 stops, ~25 min)
        ...
        Total: 49 min
    """
    if not route_data or not route_data.get("steps"):
        return ""

    lines = [f"Google Transit Route ({origin_name} → {destination_name}):"]
    step_num = 1

    for step in route_data["steps"]:
        if step["type"] == "walk":
            dur = step["duration_minutes"]
            if dur > 0:
                lines.append(f"{step_num}. Walk {dur} min")
                step_num += 1

        elif step["type"] == "ride":
            parts = [f"{step_num}. Board {step['line']}"]
            if step.get("from_station"):
                parts[0] += f" at {step['from_station']}"
            if step.get("to_station"):
                parts[0] += f" to {step['to_station']}"

            details = []
            if step.get("departure_time"):
                details.append(f"departs {step['departure_time']}")
            if step.get("arrival_time"):
                details.append(f"arrives {step['arrival_time']}")
            if step.get("num_stops"):
                details.append(f"{step['num_stops']} stops")
            if step.get("duration_minutes"):
                details.append(f"~{step['duration_minutes']} min")

            if details:
                parts[0] += f" ({', '.join(details)})"

            lines.append(parts[0])
            step_num += 1

    lines.append(f"Total: {route_data['total_duration']} min")
    return "\n".join(lines)
