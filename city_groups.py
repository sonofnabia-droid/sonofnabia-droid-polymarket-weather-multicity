"""city_groups.py - agrupamento climatico das cidades. FONTE UNICA."""

GROUPS = {
    "PACIFIC": [
        "panama_city", "singapore", "kuala_lumpur", "manila",
        "chongqing", "sao_paulo",
    ],
    "CONTINENTAL": [
        "beijing", "qingdao", "seoul", "busan", "tokyo", "shanghai",
        "shenzhen", "wuhan", "taipei", "guangzhou", "lucknow",
        "karachi", "jeddah",
    ],
    "ATLANTIC": [
        "munich", "london", "paris", "amsterdam", "milan", "warsaw",
        "helsinki", "moscow", "madrid", "istanbul", "tel_aviv",
        "cape_town", "wellington", "toronto", "buenos_aires",
        "mexico_city",
    ],
}

ICONS = {"PACIFIC": "T", "CONTINENTAL": "C", "ATLANTIC": "A"}


def group_of(city):
    c = str(city).lower().strip()
    for g, lst in GROUPS.items():
        if c in lst:
            return g
    return "ATLANTIC"


def all_cities():
    return [c for lst in GROUPS.values() for c in lst]
