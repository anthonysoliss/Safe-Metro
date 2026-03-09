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
    {"name": "7th St/Metro Center",        "lines": ["A","B","D","E"], "lat": 34.048111, "lng": -118.258459},
    {"name": "Pico",                       "lines": ["A","E"],         "lat": 34.040523, "lng": -118.266345},
    {"name": "Grand/LATTC",                "lines": ["A"],             "lat": 34.033030, "lng": -118.268944},
    {"name": "San Pedro Street",           "lines": ["A"],             "lat": 34.026737, "lng": -118.255355},
    {"name": "Washington",                 "lines": ["A"],             "lat": 34.019934, "lng": -118.243094},
    {"name": "Slauson",                    "lines": ["A"],             "lat": 33.988840, "lng": -118.243388},
    {"name": "Florence",                   "lines": ["A"],             "lat": 33.974091, "lng": -118.243286},
    {"name": "Firestone",                  "lines": ["A"],             "lat": 33.959854, "lng": -118.243229},
    {"name": "103rd St/Watts Towers",      "lines": ["A"],             "lat": 33.942219, "lng": -118.243156},
    {"name": "Willowbrook/Rosa Parks",     "lines": ["A","C"],         "lat": 33.927815, "lng": -118.237446},
    {"name": "Compton",                    "lines": ["A"],             "lat": 33.897662, "lng": -118.224277},
    {"name": "Artesia",                    "lines": ["A"],             "lat": 33.875786, "lng": -118.222748},
    {"name": "Del Amo",                    "lines": ["A"],             "lat": 33.848221, "lng": -118.211014},
    {"name": "Wardlow",                    "lines": ["A"],             "lat": 33.819866, "lng": -118.196091},
    {"name": "Willow Street",              "lines": ["A"],             "lat": 33.806797, "lng": -118.189720},
    {"name": "Pacific Coast Hwy",          "lines": ["A"],             "lat": 33.789223, "lng": -118.189384},
    {"name": "Anaheim Street",             "lines": ["A"],             "lat": 33.781830, "lng": -118.189384},
    {"name": "5th Street",                 "lines": ["A"],             "lat": 33.7751, "lng": -118.1886},
    {"name": "Downtown Long Beach",        "lines": ["A"],             "lat": 33.768051, "lng": -118.193135},
    # B Line (Red)
    {"name": "Union Station",              "lines": ["B","D","L"],     "lat": 34.056024, "lng": -118.234768},
    {"name": "Civic Center/Grand Park",    "lines": ["B","D"],         "lat": 34.054220, "lng": -118.247065},
    {"name": "Pershing Square",            "lines": ["B","D"],         "lat": 34.048427, "lng": -118.251570},
    {"name": "Westlake/MacArthur Park",    "lines": ["B","D"],         "lat": 34.056923, "lng": -118.276154},
    {"name": "Wilshire/Vermont",           "lines": ["B","D"],         "lat": 34.062479, "lng": -118.290869},
    {"name": "Vermont/Beverly",            "lines": ["B"],             "lat": 34.076625, "lng": -118.292035},
    {"name": "Vermont/Santa Monica",       "lines": ["B"],             "lat": 34.090104, "lng": -118.292019},
    {"name": "Vermont/Sunset",             "lines": ["B"],             "lat": 34.098369, "lng": -118.291452},
    {"name": "Hollywood/Western",          "lines": ["B"],             "lat": 34.101539, "lng": -118.309010},
    {"name": "Hollywood/Vine",             "lines": ["B"],             "lat": 34.101313, "lng": -118.325658},
    {"name": "Hollywood/Highland",         "lines": ["B"],             "lat": 34.101770, "lng": -118.339307},
    {"name": "Universal City/Studio City", "lines": ["B"],             "lat": 34.139043, "lng": -118.362586},
    {"name": "North Hollywood",            "lines": ["B","G"],         "lat": 34.168875, "lng": -118.376608},
    # C Line (Green)
    {"name": "Redondo Beach",              "lines": ["C"],             "lat": 33.894743, "lng": -118.369490},
    {"name": "Douglas",                    "lines": ["C"],             "lat": 33.9073, "lng": -118.2940},
    {"name": "El Segundo",                 "lines": ["C"],             "lat": 33.9164, "lng": -118.3037},
    {"name": "Mariposa",                   "lines": ["C"],             "lat": 33.9189, "lng": -118.3288},
    {"name": "Aviation/LAX",               "lines": ["C","K"],         "lat": 33.929660, "lng": -118.377206},
    {"name": "Hawthorne/Lennox",           "lines": ["C"],             "lat": 33.933478, "lng": -118.351964},
    {"name": "Vermont/Athens",             "lines": ["C"],             "lat": 33.928705, "lng": -118.291386},
    {"name": "Harbor Freeway",             "lines": ["C"],             "lat": 33.928725, "lng": -118.280791},
    {"name": "Avalon",                     "lines": ["C"],             "lat": 33.927464, "lng": -118.265221},
    {"name": "Long Beach Blvd",            "lines": ["C"],             "lat": 33.924864, "lng": -118.209991},
    {"name": "Lakewood Blvd",              "lines": ["C"],             "lat": 33.913091, "lng": -118.140185},
    {"name": "Norwalk",                    "lines": ["C"],             "lat": 33.914119, "lng": -118.104075},
    # D Line (Purple)
    {"name": "Wilshire/Normandie",         "lines": ["D"],             "lat": 34.061570, "lng": -118.300930},
    {"name": "Wilshire/Western",           "lines": ["D"],             "lat": 34.062128, "lng": -118.308862},
    {"name": "Wilshire/La Brea",           "lines": ["D"],             "lat": 34.061938, "lng": -118.343990},
    {"name": "Wilshire/Fairfax",           "lines": ["D"],             "lat": 34.063085, "lng": -118.362320},
    {"name": "Wilshire/La Cienega",        "lines": ["D"],             "lat": 34.065483, "lng": -118.376770},
    {"name": "Wilshire/Rodeo",             "lines": ["D"],             "lat": 34.066768, "lng": -118.398282},
    {"name": "Century City/Constellation", "lines": ["D"],             "lat": 34.059722, "lng": -118.415000},
    {"name": "Westwood/VA Hospital",       "lines": ["D"],             "lat": 34.052687, "lng": -118.452977},
    # E Line (Expo)
    {"name": "Jefferson/USC",              "lines": ["E"],             "lat": 34.022056, "lng": -118.278191},
    {"name": "Expo Park/USC",              "lines": ["E"],             "lat": 34.018192, "lng": -118.285680},
    {"name": "Expo/Vermont",               "lines": ["E"],             "lat": 34.018303, "lng": -118.292338},
    {"name": "Expo/Western",               "lines": ["E"],             "lat": 34.018283, "lng": -118.308443},
    {"name": "Farmdale",                   "lines": ["E"],             "lat": 34.023961, "lng": -118.346687},
    {"name": "Expo/Crenshaw",              "lines": ["E","K"],         "lat": 34.022383, "lng": -118.333975},
    {"name": "Expo/La Brea",               "lines": ["E"],             "lat": 34.024803, "lng": -118.355156},
    {"name": "La Cienega/Jefferson",       "lines": ["E"],             "lat": 34.026356, "lng": -118.372124},
    {"name": "Culver City",                "lines": ["E"],             "lat": 34.027885, "lng": -118.388865},
    {"name": "Palms",                      "lines": ["E"],             "lat": 34.029317, "lng": -118.404200},
    {"name": "Westwood/Rancho Park",       "lines": ["E"],             "lat": 34.036830, "lng": -118.424546},
    {"name": "Expo/Sepulveda",             "lines": ["E"],             "lat": 34.035426, "lng": -118.434270},
    {"name": "Expo/Bundy",                 "lines": ["E"],             "lat": 34.031706, "lng": -118.452929},
    {"name": "26th St/Bergamot",           "lines": ["E"],             "lat": 34.027981, "lng": -118.469203},
    {"name": "17th St/SMC",                "lines": ["E"],             "lat": 34.023159, "lng": -118.480396},
    {"name": "Downtown Santa Monica",      "lines": ["E"],             "lat": 34.014000, "lng": -118.491347},
    # K Line (Crenshaw/LAX)
    {"name": "Westchester/Veterans",       "lines": ["K"],             "lat": 33.961964, "lng": -118.374466},
    {"name": "Downtown Inglewood",         "lines": ["K"],             "lat": 33.967155, "lng": -118.351494},
    {"name": "Fairview Heights",           "lines": ["K"],             "lat": 33.975250, "lng": -118.336075},
    {"name": "Hyde Park",                  "lines": ["K"],             "lat": 33.988186, "lng": -118.330818},
    {"name": "Leimert Park",               "lines": ["K"],             "lat": 34.004620, "lng": -118.332657},
    {"name": "Martin Luther King Jr",      "lines": ["K"],             "lat": 34.011272, "lng": -118.335781},
    # L Line (Gold)
    {"name": "Chinatown",                  "lines": ["L"],             "lat": 34.063930, "lng": -118.235924},
    {"name": "Lincoln/Cypress",            "lines": ["L"],             "lat": 34.081083, "lng": -118.220315},
    {"name": "Heritage Square/Arroyo",     "lines": ["L"],             "lat": 34.087508, "lng": -118.213010},
    {"name": "Southwest Museum",           "lines": ["L"],             "lat": 34.098402, "lng": -118.206488},
    {"name": "Highland Park",              "lines": ["L"],             "lat": 34.111188, "lng": -118.192619},
    {"name": "South Pasadena",             "lines": ["L"],             "lat": 34.115271, "lng": -118.157803},
    {"name": "Fillmore",                   "lines": ["L"],             "lat": 34.133522, "lng": -118.148125},
    {"name": "Del Mar",                    "lines": ["L"],             "lat": 34.141983, "lng": -118.148281},
    {"name": "Memorial Park",              "lines": ["L"],             "lat": 34.147981, "lng": -118.147672},
    {"name": "Lake",                       "lines": ["L"],             "lat": 34.151822, "lng": -118.131601},
    {"name": "Allen",                      "lines": ["L"],             "lat": 34.152431, "lng": -118.113942},
    {"name": "Sierra Madre Villa",         "lines": ["L"],             "lat": 34.148415, "lng": -118.081231},
    {"name": "Arcadia",                    "lines": ["L"],             "lat": 34.142763, "lng": -118.029043},
    {"name": "Monrovia",                   "lines": ["L"],             "lat": 34.133151, "lng": -118.003292},
    {"name": "Duarte/City of Hope",        "lines": ["L"],             "lat": 34.132512, "lng": -117.967502},
    {"name": "Irwindale",                  "lines": ["L"],             "lat": 34.129020, "lng": -117.932465},
    {"name": "Azusa Downtown",             "lines": ["L"],             "lat": 34.135772, "lng": -117.906781},
    {"name": "APU/Citrus College",         "lines": ["L"],             "lat": 34.136811, "lng": -117.891719},
    # G Line (Orange)
    {"name": "Chatsworth",                 "lines": ["G"],             "lat": 34.253241, "lng": -118.599470},
    {"name": "Nordhoff",                   "lines": ["G"],             "lat": 34.235607, "lng": -118.597042},
    {"name": "Roscoe",                     "lines": ["G"],             "lat": 34.219770, "lng": -118.597229},
    {"name": "De Soto",                    "lines": ["G"],             "lat": 34.2002, "lng": -118.5595},
    {"name": "Pierce College",             "lines": ["G"],             "lat": 34.187171, "lng": -118.570938},
    {"name": "Tampa",                      "lines": ["G"],             "lat": 34.180729, "lng": -118.553314},
    {"name": "Reseda",                     "lines": ["G"],             "lat": 34.180418, "lng": -118.536601},
    {"name": "Balboa",                     "lines": ["G"],             "lat": 34.185970, "lng": -118.500717},
    {"name": "Woodley",                    "lines": ["G"],             "lat": 34.186239, "lng": -118.483643},
    {"name": "Sepulveda",                  "lines": ["G"],             "lat": 34.180965, "lng": -118.466042},
    {"name": "Van Nuys",                   "lines": ["G"],             "lat": 34.1486, "lng": -118.4494},
    {"name": "Valley College",             "lines": ["G"],             "lat": 34.172272, "lng": -118.422351},
    {"name": "Laurel Canyon",              "lines": ["G"],             "lat": 34.168519, "lng": -118.396488},
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
