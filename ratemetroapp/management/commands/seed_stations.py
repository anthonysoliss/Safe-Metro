from django.core.management.base import BaseCommand
from ratemetroapp.models import Station, MetroLine


METRO_LINES = [
    {"code": "A", "name": "A Line (Blue)",        "color": "#0072bc", "text_color": "#fff"},
    {"code": "B", "name": "B Line (Red)",         "color": "#e32119", "text_color": "#fff"},
    {"code": "C", "name": "C Line (Green)",       "color": "#00a550", "text_color": "#fff"},
    {"code": "D", "name": "D Line (Purple)",      "color": "#8b4f9e", "text_color": "#fff"},
    {"code": "E", "name": "E Line (Expo)",        "color": "#fdb913", "text_color": "#000"},
    {"code": "G", "name": "G Line (Orange)",      "color": "#f58220", "text_color": "#fff"},
    {"code": "J", "name": "J Line (Silver)",      "color": "#b5a07e", "text_color": "#fff"},
    {"code": "K", "name": "K Line (Crenshaw)",    "color": "#e96bb0", "text_color": "#fff"},
    {"code": "L", "name": "L Line (Gold)",        "color": "#c4a73f", "text_color": "#fff"},
]

STATIONS = [
    # A Line (Blue)
    {"name": "7th St/Metro Center",        "lines": ["A","B","D","E"], "lat": 34.0486, "lng": -118.2588},
    {"name": "Pico",                       "lines": ["A","E"],         "lat": 34.0408, "lng": -118.2660},
    {"name": "Grand/LATTC",                "lines": ["A"],             "lat": 34.0335, "lng": -118.2689},
    {"name": "San Pedro Street",           "lines": ["A"],             "lat": 34.0290, "lng": -118.2540},
    {"name": "Washington",                 "lines": ["A"],             "lat": 34.0181, "lng": -118.2580},
    {"name": "Slauson",                    "lines": ["A"],             "lat": 33.9893, "lng": -118.2671},
    {"name": "Florence",                   "lines": ["A"],             "lat": 33.9764, "lng": -118.2680},
    {"name": "Firestone",                  "lines": ["A"],             "lat": 33.9677, "lng": -118.2685},
    {"name": "103rd St/Watts Towers",      "lines": ["A"],             "lat": 33.9429, "lng": -118.2690},
    {"name": "Willowbrook/Rosa Parks",     "lines": ["A","C"],         "lat": 33.9286, "lng": -118.2380},
    {"name": "Compton",                    "lines": ["A"],             "lat": 33.8972, "lng": -118.2231},
    {"name": "Artesia",                    "lines": ["A"],             "lat": 33.8758, "lng": -118.2282},
    {"name": "Del Amo",                    "lines": ["A"],             "lat": 33.8489, "lng": -118.2119},
    {"name": "Wardlow",                    "lines": ["A"],             "lat": 33.8388, "lng": -118.2087},
    {"name": "Willow Street",              "lines": ["A"],             "lat": 33.8082, "lng": -118.1893},
    {"name": "Pacific Coast Hwy",          "lines": ["A"],             "lat": 33.7902, "lng": -118.1868},
    {"name": "Anaheim Street",             "lines": ["A"],             "lat": 33.7819, "lng": -118.1950},
    {"name": "5th Street",                 "lines": ["A"],             "lat": 33.7751, "lng": -118.1886},
    {"name": "Downtown Long Beach",        "lines": ["A"],             "lat": 33.7684, "lng": -118.1896},
    # B Line (Red)
    {"name": "Union Station",              "lines": ["B","D","L"],     "lat": 34.0561, "lng": -118.2365},
    {"name": "Civic Center/Grand Park",    "lines": ["B","D"],         "lat": 34.0558, "lng": -118.2461},
    {"name": "Pershing Square",            "lines": ["B","D"],         "lat": 34.0494, "lng": -118.2517},
    {"name": "Westlake/MacArthur Park",    "lines": ["B","D"],         "lat": 34.0560, "lng": -118.2745},
    {"name": "Wilshire/Vermont",           "lines": ["B","D"],         "lat": 34.0628, "lng": -118.2911},
    {"name": "Vermont/Beverly",            "lines": ["B"],             "lat": 34.0762, "lng": -118.2913},
    {"name": "Vermont/Santa Monica",       "lines": ["B"],             "lat": 34.0909, "lng": -118.2919},
    {"name": "Vermont/Sunset",             "lines": ["B"],             "lat": 34.0976, "lng": -118.2919},
    {"name": "Hollywood/Western",          "lines": ["B"],             "lat": 34.1016, "lng": -118.3069},
    {"name": "Hollywood/Vine",             "lines": ["B"],             "lat": 34.1017, "lng": -118.3260},
    {"name": "Hollywood/Highland",         "lines": ["B"],             "lat": 34.1016, "lng": -118.3385},
    {"name": "Universal City/Studio City", "lines": ["B"],             "lat": 34.1382, "lng": -118.3621},
    {"name": "North Hollywood",            "lines": ["B","G"],         "lat": 34.1684, "lng": -118.3766},
    # C Line (Green)
    {"name": "Redondo Beach",              "lines": ["C"],             "lat": 33.8994, "lng": -118.2778},
    {"name": "Douglas",                    "lines": ["C"],             "lat": 33.9073, "lng": -118.2940},
    {"name": "El Segundo",                 "lines": ["C"],             "lat": 33.9164, "lng": -118.3037},
    {"name": "Mariposa",                   "lines": ["C"],             "lat": 33.9189, "lng": -118.3288},
    {"name": "Aviation/LAX",               "lines": ["C","K"],         "lat": 33.9342, "lng": -118.3789},
    {"name": "Hawthorne/Lennox",           "lines": ["C"],             "lat": 33.9214, "lng": -118.3520},
    {"name": "Vermont/Athens",             "lines": ["C"],             "lat": 33.9292, "lng": -118.2881},
    {"name": "Harbor Freeway",             "lines": ["C"],             "lat": 33.9292, "lng": -118.2575},
    {"name": "Avalon",                     "lines": ["C"],             "lat": 33.9294, "lng": -118.2443},
    {"name": "Long Beach Blvd",            "lines": ["C"],             "lat": 33.9099, "lng": -118.2108},
    {"name": "Lakewood Blvd",              "lines": ["C"],             "lat": 33.9099, "lng": -118.1329},
    {"name": "Norwalk",                    "lines": ["C"],             "lat": 33.9144, "lng": -118.1050},
    # D Line (Purple)
    {"name": "Wilshire/Normandie",         "lines": ["D"],             "lat": 34.0618, "lng": -118.3012},
    {"name": "Wilshire/Western",           "lines": ["D"],             "lat": 34.0626, "lng": -118.3089},
    {"name": "Wilshire/La Brea",           "lines": ["D"],             "lat": 34.0620, "lng": -118.3443},
    {"name": "Wilshire/Fairfax",           "lines": ["D"],             "lat": 34.0622, "lng": -118.3612},
    {"name": "Wilshire/La Cienega",        "lines": ["D"],             "lat": 34.0624, "lng": -118.3784},
    {"name": "Wilshire/Rodeo",             "lines": ["D"],             "lat": 34.0606, "lng": -118.3975},
    {"name": "Century City/Constellation", "lines": ["D"],             "lat": 34.0555, "lng": -118.4170},
    {"name": "Westwood/VA Hospital",       "lines": ["D"],             "lat": 34.0478, "lng": -118.4406},
    # E Line (Expo)
    {"name": "Jefferson/USC",              "lines": ["E"],             "lat": 34.0216, "lng": -118.2789},
    {"name": "Expo Park/USC",              "lines": ["E"],             "lat": 34.0180, "lng": -118.2857},
    {"name": "Expo/Vermont",               "lines": ["E"],             "lat": 34.0181, "lng": -118.2914},
    {"name": "Expo/Western",               "lines": ["E"],             "lat": 34.0184, "lng": -118.3087},
    {"name": "Farmdale",                   "lines": ["E"],             "lat": 34.0166, "lng": -118.3259},
    {"name": "Expo/Crenshaw",              "lines": ["E","K"],         "lat": 34.0229, "lng": -118.3382},
    {"name": "Expo/La Brea",               "lines": ["E"],             "lat": 34.0233, "lng": -118.3519},
    {"name": "La Cienega/Jefferson",       "lines": ["E"],             "lat": 34.0250, "lng": -118.3729},
    {"name": "Culver City",                "lines": ["E"],             "lat": 34.0283, "lng": -118.3863},
    {"name": "Palms",                      "lines": ["E"],             "lat": 34.0289, "lng": -118.4047},
    {"name": "Westwood/Rancho Park",       "lines": ["E"],             "lat": 34.0365, "lng": -118.4225},
    {"name": "Expo/Sepulveda",             "lines": ["E"],             "lat": 34.0340, "lng": -118.4335},
    {"name": "Expo/Bundy",                 "lines": ["E"],             "lat": 34.0266, "lng": -118.4525},
    {"name": "26th St/Bergamot",           "lines": ["E"],             "lat": 34.0299, "lng": -118.4665},
    {"name": "17th St/SMC",                "lines": ["E"],             "lat": 34.0151, "lng": -118.4792},
    {"name": "Downtown Santa Monica",      "lines": ["E"],             "lat": 34.0115, "lng": -118.4916},
    # K Line (Crenshaw/LAX)
    {"name": "Westchester/Veterans",       "lines": ["K"],             "lat": 33.9590, "lng": -118.3782},
    {"name": "Downtown Inglewood",         "lines": ["K"],             "lat": 33.9613, "lng": -118.3531},
    {"name": "Fairview Heights",           "lines": ["K"],             "lat": 33.9723, "lng": -118.3443},
    {"name": "Hyde Park",                  "lines": ["K"],             "lat": 33.9918, "lng": -118.3312},
    {"name": "Leimert Park",               "lines": ["K"],             "lat": 34.0082, "lng": -118.3325},
    {"name": "Martin Luther King Jr",      "lines": ["K"],             "lat": 34.0110, "lng": -118.3360},
    # L Line (Gold)
    {"name": "Chinatown",                  "lines": ["L"],             "lat": 34.0637, "lng": -118.2358},
    {"name": "Lincoln/Cypress",            "lines": ["L"],             "lat": 34.0688, "lng": -118.2258},
    {"name": "Heritage Square/Arroyo",     "lines": ["L"],             "lat": 34.0813, "lng": -118.2149},
    {"name": "Southwest Museum",           "lines": ["L"],             "lat": 34.0942, "lng": -118.2129},
    {"name": "Highland Park",              "lines": ["L"],             "lat": 34.1111, "lng": -118.1960},
    {"name": "South Pasadena",             "lines": ["L"],             "lat": 34.1154, "lng": -118.1576},
    {"name": "Fillmore",                   "lines": ["L"],             "lat": 34.1262, "lng": -118.1488},
    {"name": "Del Mar",                    "lines": ["L"],             "lat": 34.1380, "lng": -118.1484},
    {"name": "Memorial Park",              "lines": ["L"],             "lat": 34.1436, "lng": -118.1485},
    {"name": "Lake",                       "lines": ["L"],             "lat": 34.1519, "lng": -118.1318},
    {"name": "Allen",                      "lines": ["L"],             "lat": 34.1519, "lng": -118.1132},
    {"name": "Sierra Madre Villa",         "lines": ["L"],             "lat": 34.1481, "lng": -118.0811},
    {"name": "Arcadia",                    "lines": ["L"],             "lat": 34.1419, "lng": -118.0530},
    {"name": "Monrovia",                   "lines": ["L"],             "lat": 34.1482, "lng": -118.0019},
    {"name": "Duarte/City of Hope",        "lines": ["L"],             "lat": 34.1546, "lng": -117.9752},
    {"name": "Irwindale",                  "lines": ["L"],             "lat": 34.1267, "lng": -117.9441},
    {"name": "Azusa Downtown",             "lines": ["L"],             "lat": 34.1350, "lng": -117.9091},
    {"name": "APU/Citrus College",         "lines": ["L"],             "lat": 34.1378, "lng": -117.8862},
    # G Line (Orange)
    {"name": "Chatsworth",                 "lines": ["G"],             "lat": 34.2583, "lng": -118.6010},
    {"name": "Nordhoff",                   "lines": ["G"],             "lat": 34.2342, "lng": -118.5871},
    {"name": "Roscoe",                     "lines": ["G"],             "lat": 34.2194, "lng": -118.5700},
    {"name": "De Soto",                    "lines": ["G"],             "lat": 34.2002, "lng": -118.5595},
    {"name": "Pierce College",             "lines": ["G"],             "lat": 34.1874, "lng": -118.5501},
    {"name": "Tampa",                      "lines": ["G"],             "lat": 34.1732, "lng": -118.5340},
    {"name": "Reseda",                     "lines": ["G"],             "lat": 34.1725, "lng": -118.5117},
    {"name": "Balboa",                     "lines": ["G"],             "lat": 34.1732, "lng": -118.4970},
    {"name": "Woodley",                    "lines": ["G"],             "lat": 34.1672, "lng": -118.4690},
    {"name": "Sepulveda",                  "lines": ["G"],             "lat": 34.1610, "lng": -118.4487},
    {"name": "Van Nuys",                   "lines": ["G"],             "lat": 34.1486, "lng": -118.4494},
    {"name": "Valley College",             "lines": ["G"],             "lat": 34.1646, "lng": -118.4155},
    {"name": "Laurel Canyon",              "lines": ["G"],             "lat": 34.1665, "lng": -118.3920},
    {"name": "Woodman",                    "lines": ["G"],             "lat": 34.1668, "lng": -118.3841},
]


class Command(BaseCommand):
    help = "Seed the database with all LA Metro stations and lines"

    def handle(self, *args, **options):
        # Create / update metro lines
        line_objects = {}
        for line_data in METRO_LINES:
            line, created = MetroLine.objects.update_or_create(
                code=line_data["code"],
                defaults={
                    "name": line_data["name"],
                    "color": line_data["color"],
                    "text_color": line_data["text_color"],
                },
            )
            line_objects[line_data["code"]] = line
            action = "Created" if created else "Updated"
            self.stdout.write(f"  {action} line: {line}")

        self.stdout.write(self.style.SUCCESS(f"Lines ready: {len(line_objects)}"))

        # Create / update stations
        created_count = 0
        updated_count = 0
        for station_data in STATIONS:
            station, created = Station.objects.update_or_create(
                name=station_data["name"],
                defaults={
                    "latitude": station_data["lat"],
                    "longitude": station_data["lng"],
                },
            )
            # Sync line associations
            station.lines.set([line_objects[code] for code in station_data["lines"]])

            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done — {created_count} stations created, {updated_count} updated."
            )
        )
