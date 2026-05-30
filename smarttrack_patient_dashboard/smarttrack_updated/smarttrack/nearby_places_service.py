"""
OpenStreetMap Overpass + Nominatim for nearby healthcare finders.
Pharmacy/clinic filtering with OSM-tag trust + relaxed fallback when few results.
"""
import logging
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)
NEARBY_DEBUG = os.environ.get('SMARTTRACK_NEARBY_DEBUG', '').lower() in ('1', 'true', 'yes')
_last_search_debug: Dict[str, object] = {}

OVERPASS_MIRRORS = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
    'https://overpass.openstreetmap.de/api/interpreter',
]
NOMINATIM_REVERSE = 'https://nominatim.openstreetmap.org/reverse'
NOMINATIM_SEARCH = 'https://nominatim.openstreetmap.org/search'
USER_AGENT = 'SmartTrack/1.0 Healthcare Finder (contact@smarttrack.local)'

# Search radii (meters): start 5 km, expand to 8 / 10 km if needed
SEARCH_RADII_M = [5000, 8000, 10000]
EMERGENCY_RADII_M = [2000, 5000, 8000]
MIN_RESULTS_BEFORE_STOP = 5
MIN_RESULTS_TARGET = 1
MAX_REVERSE_GEOCODE = 12
OVERPASS_TIMEOUT = 18
OVERPASS_MIRRORS_LIMIT = 2
SEARCH_CACHE_TTL_SEC = 600
SEARCH_CACHE: Dict[str, Tuple[float, tuple]] = {}

GENERIC_NAMES = frozenset({
    '', 'medical facility', 'pharmacy', 'clinic', 'hospital', 'unnamed',
    'health center', 'health centre', 'medical center', 'medical centre',
})

# Always reject (even with healthcare OSM tags)
HARD_NAME_BLACKLIST_RE = re.compile(
    r'kirana|grocery|groceries|super\s*market|supermarket|convenience|'
    r'department\s*store|stationery|provisions|wholesale|hardware|'
    r'electricals?|mobile\s*shop|restaurant|hotel|bakery|garments?|textile|'
    r'petrol|fuel\s*station|fertilizer|agro|sweet\s*shop|tea\s*stall|pan\s*shop|'
    r'barber|salon|beauty\s*parlour|gym|fitness|jewellery|jewelry|'
    r'optical(?!.*pharm)|atm|bank\b|school|college|temple|mosque|church|'
    r'xerox|printing|laundry|dry\s*clean|furniture|paint\s*shop|liquor|'
    r'wine\s*shop|beer\s*shop|chicken|mutton|fish\s*market|vegetable|'
    r'fruits?\s*shop|sabzi|mandi\b|mall\b|shopping\s*centre|shopping\s*center',
    re.IGNORECASE,
)

# Reject only when OSM tags do NOT confirm pharmacy/clinic (e.g. "Medical & General Store" with amenity=pharmacy)
SOFT_NAME_BLACKLIST_RE = re.compile(
    r'general\s*store|general\s*stores',
    re.IGNORECASE,
)

PHARMACY_POSITIVE_RE = re.compile(
    r'pharmacy|pharmacies|chemist|chemists|medical\s*store|medical\s*shop|'
    r'medical\s*&|medicals\b|medico|medicine\s*shop|drug\s*store|drugstore|'
    r'apothecary|medplus|apollo\s*pharm|wellness\s*forever|wellness\b|'
    r'prescription|hospital\s*pharm|24\s*[x×]\s*7|healthcare\s*pharm|'
    r'homeopath|homoeopath|ayurvedic|allopathic|pharma|dispensary|druggist|'
    r'aushadhi|patent\s*medicine|allopathy|homeopathy',
    re.IGNORECASE,
)

PHARMACY_RELAXED_NAME_RE = re.compile(
    r'medical|chemist|pharma|medicine|drug|dispensary|medico|aushadhi|health\s*care',
    re.IGNORECASE,
)

CLINIC_POSITIVE_RE = re.compile(
    r'hospital|clinic|health\s*centre|health\s*center|healthcare|nursing\s*home|'
    r'multispecial|multi\s*special|emergency|trauma|urgent\s*care|physician|'
    r'doctor|doctors|surgeon|dentist|dermatolog|cardiolog|pediatric|'
    r'gynaecolog|gynecolog|orthop|ENT\b|OPD|diagnostic\s*centre|'
    r'diagnostic\s*center|polyclinic|medical\s*centre|medical\s*center|'
    r'trust\s*hospital|care\s*hospital|nursing\s*hospital',
    re.IGNORECASE,
)

INVALID_SHOP_TAGS = frozenset({
    'general', 'convenience', 'supermarket', 'mall', 'department_store',
    'greengrocer', 'kiosk', 'variety_store', 'newsagent', 'pet', 'electronics',
    'clothes', 'hairdresser', 'beauty', 'furniture', 'hardware', 'alcohol',
    'beverages', 'dairy', 'frozen_food', 'seafood', 'bakery', 'pastry',
    'confectionery', 'stationery', 'books', 'gift', 'toys', 'sports',
    'outdoor', 'mobile_phone', 'computer', 'ticket', 'travel_agency',
    'car', 'car_repair', 'bicycle', 'yes', 'vacant',
})


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return round(r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 2)


def build_osm_address(tags: dict) -> str:
    if tags.get('addr:full'):
        return tags['addr:full'].strip()

    street_parts = []
    if tags.get('addr:housenumber'):
        street_parts.append(tags['addr:housenumber'].strip())
    if tags.get('addr:street'):
        street_parts.append(tags['addr:street'].strip())
    elif tags.get('addr:road'):
        street_parts.append(tags['addr:road'].strip())
    parts = [' '.join(street_parts)] if street_parts else []

    for key in (
        'addr:unit', 'addr:place', 'addr:neighbourhood', 'addr:suburb',
        'addr:hamlet', 'addr:district', 'addr:city', 'addr:town',
        'addr:village', 'addr:state', 'addr:postcode', 'addr:country',
    ):
        val = tags.get(key)
        if val and str(val).strip() not in parts:
            parts.append(str(val).strip())
    return ', '.join(parts)


def _resolve_name(tags: dict) -> Optional[str]:
    for key in (
        'name', 'name:en', 'name:hi', 'brand', 'operator', 'alt_name',
        'official_name', 'short_name',
    ):
        val = (tags.get(key) or '').strip()
        if val and val.lower() not in GENERIC_NAMES and len(val) >= 2:
            return val
    return None


def _fallback_place_name(tags: dict, place_kind: str) -> Optional[str]:
    brand = (tags.get('brand') or tags.get('operator') or '').strip()
    if brand and brand.lower() not in GENERIC_NAMES:
        return brand
    if place_kind == 'pharmacy' and (_osm_pharmacy_tags(tags) or tags.get('dispensing') == 'yes'):
        label = tags.get('shop') or tags.get('amenity') or tags.get('healthcare') or 'pharmacy'
        return f"Medical store ({str(label).replace('_', ' ')})"
    if place_kind == 'clinic' and _osm_clinic_tags(tags):
        label = tags.get('amenity') or tags.get('healthcare') or 'clinic'
        return f"Healthcare ({str(label).replace('_', ' ')})"
    return None


def _name_blocked(name: str, tags: Optional[dict] = None, place_kind: str = 'pharmacy') -> bool:
    if not name:
        return True
    if HARD_NAME_BLACKLIST_RE.search(name):
        return True
    if SOFT_NAME_BLACKLIST_RE.search(name):
        if tags and place_kind == 'pharmacy' and (
            _osm_pharmacy_tags(tags) or tags.get('dispensing') == 'yes'
        ):
            return False
        if tags and place_kind == 'clinic' and _osm_clinic_tags(tags):
            return False
        return True
    return False


def _osm_pharmacy_tags(tags: dict) -> bool:
    if tags.get('amenity') == 'pharmacy':
        return True
    shop = (tags.get('shop') or '').lower()
    if shop in ('pharmacy', 'chemist', 'medical_supply', 'herbalist', 'nutrition_supplements'):
        return True
    healthcare = (tags.get('healthcare') or '').lower()
    if healthcare in ('pharmacy', 'chemist'):
        return True
    if tags.get('dispensing') == 'yes':
        return True
    return False


def _is_valid_pharmacy(name: str, tags: dict, strict: bool = True) -> bool:
    shop = (tags.get('shop') or '').lower()
    if shop in INVALID_SHOP_TAGS and not _osm_pharmacy_tags(tags):
        return False

    has_osm = _osm_pharmacy_tags(tags) or tags.get('dispensing') == 'yes'
    has_name = bool(name and len(name) >= 2)
    name_ok = has_name and (
        PHARMACY_POSITIVE_RE.search(name)
        or (not strict and PHARMACY_RELAXED_NAME_RE.search(name))
    )

    if has_osm:
        if has_name and _name_blocked(name, tags, 'pharmacy'):
            return False
        amenity = (tags.get('amenity') or '').lower()
        if amenity in ('restaurant', 'cafe', 'fast_food', 'bank', 'fuel'):
            return False
        return True

    if not has_name:
        return False
    if _name_blocked(name, tags, 'pharmacy'):
        return False
    if name_ok:
        if shop in INVALID_SHOP_TAGS:
            return False
        amenity = (tags.get('amenity') or '').lower()
        if amenity in ('restaurant', 'cafe', 'fast_food', 'bank', 'fuel'):
            return False
        return True
    if not strict and PHARMACY_RELAXED_NAME_RE.search(name):
        return True
    return False


def _osm_clinic_tags(tags: dict) -> bool:
    amenity = (tags.get('amenity') or '').lower()
    if amenity in (
        'hospital', 'clinic', 'doctors', 'nursing_home', 'health_centre',
        'health_center', 'social_facility',
    ):
        return True
    healthcare = (tags.get('healthcare') or '').lower()
    if healthcare in (
        'hospital', 'clinic', 'centre', 'center', 'doctor', 'physician',
        'nursing_home', 'midwife', 'rehabilitation', 'laboratory', 'dentist',
        'psychotherapist', 'alternative', 'birthing_centre', 'birthing_center',
    ):
        if healthcare == 'laboratory' and not CLINIC_POSITIVE_RE.search(
            (tags.get('name') or '') + (tags.get('brand') or '')
        ):
            return False
        return True
    office = (tags.get('office') or '').lower()
    if office in ('doctor', 'healthcare', 'physician'):
        return True
    if (tags.get('building') or '').lower() in ('hospital', 'clinic', 'health_centre'):
        return True
    if tags.get('emergency') == 'yes' and amenity:
        return True
    return False


def _is_valid_clinic(name: str, tags: dict, strict: bool = True) -> bool:
    shop = (tags.get('shop') or '').lower()
    if shop in INVALID_SHOP_TAGS or shop in ('pharmacy', 'chemist', 'beauty', 'optician'):
        if not _osm_clinic_tags(tags):
            return False

    has_osm = _osm_clinic_tags(tags)
    has_name = bool(name and len(name) >= 2)

    if has_osm:
        if has_name and _name_blocked(name, tags, 'clinic'):
            return False
        if has_name and HARD_NAME_BLACKLIST_RE.search(name):
            return False
        return True

    if not has_name:
        return False
    if len(name) < 3 and not tags.get('brand'):
        return False
    if _name_blocked(name, tags, 'clinic'):
        return False
    if CLINIC_POSITIVE_RE.search(name):
        amenity = (tags.get('amenity') or '').lower()
        if amenity in ('restaurant', 'cafe', 'bank', 'fuel', 'pharmacy'):
            return False
        return True
    if not strict and re.search(
        r'hospital|clinic|doctor|health|nursing|medical\s*cent',
        name,
        re.IGNORECASE,
    ):
        return True
    return False


def _element_coords(element: dict) -> Tuple[Optional[float], Optional[float]]:
    if element.get('type') == 'node':
        return element.get('lat'), element.get('lon')
    center = element.get('center') or {}
    return center.get('lat'), center.get('lon')


def _parse_open_status(opening_hours: str) -> Tuple[Optional[bool], str]:
    if not opening_hours:
        return None, ''
    oh_lower = opening_hours.lower().strip()
    if oh_lower in ('closed', '24/7 closed'):
        return False, opening_hours
    return True, opening_hours


def _cache_key(lat: float, lng: float, place_kind: str, fast: bool, emergency: bool) -> str:
    return f"{place_kind}:{round(lat, 3)}:{round(lng, 3)}:{'e' if emergency else 'f' if fast else 'n'}"


def _cache_get(key: str) -> Optional[tuple]:
    entry = SEARCH_CACHE.get(key)
    if not entry:
        return None
    expires, payload = entry
    if time.time() > expires:
        SEARCH_CACHE.pop(key, None)
        return None
    return payload


def _cache_set(key: str, payload: tuple) -> None:
    places = payload[0] if payload else []
    if not places:
        return
    SEARCH_CACHE[key] = (time.time() + SEARCH_CACHE_TTL_SEC, payload)


def get_last_nearby_search_debug() -> Dict[str, object]:
    return dict(_last_search_debug)


def _debug_log(place_kind: str, msg: str, **kwargs) -> None:
    if NEARBY_DEBUG:
        logger.info('nearby_%s %s %s', place_kind, msg, kwargs)
    _last_search_debug.setdefault('events', []).append({'msg': msg, **kwargs})


def _run_overpass(query: str, timeout: int = OVERPASS_TIMEOUT) -> List[dict]:
    headers = {
        'User-Agent': USER_AGENT,
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    for url in OVERPASS_MIRRORS[:OVERPASS_MIRRORS_LIMIT]:
        try:
            response = requests.post(
                url, data={'data': query}, headers=headers, timeout=timeout
            )
            if response.status_code == 200:
                data = response.json()
                elements = data.get('elements', [])
                if elements:
                    return elements
                if data.get('remark') or data.get('error'):
                    _debug_log('overpass', 'api_remark', url=url, msg=data.get('remark') or data.get('error'))
            elif response.status_code == 429:
                _debug_log('overpass', 'rate_limit', url=url)
                time.sleep(1.5)
        except Exception as exc:
            _debug_log('overpass', 'error', url=url, err=str(exc)[:120])
            continue
    return []


def _run_overpass_parallel(
    query_builder: Callable[[int, float, float], str],
    radii: List[int],
    lat: float,
    lng: float,
    timeout: int,
) -> List[dict]:
    """Fetch multiple radii in parallel; return merged elements."""
    queries = [query_builder(r, lat, lng) for r in radii]
    merged: List[dict] = []
    seen_ids = set()
    with ThreadPoolExecutor(max_workers=min(3, len(queries))) as pool:
        futures = [pool.submit(_run_overpass, q, timeout) for q in queries]
        for fut in as_completed(futures):
            try:
                for el in fut.result():
                    eid = el.get('id') or id(el)
                    if eid not in seen_ids:
                        seen_ids.add(eid)
                        merged.append(el)
            except Exception:
                continue
    return merged


def _reverse_geocode(lat: float, lon: float, cache: Dict[Tuple[float, float], str]) -> str:
    key = (round(lat, 5), round(lon, 5))
    if key in cache:
        return cache[key]
    try:
        response = requests.get(
            NOMINATIM_REVERSE,
            params={'lat': lat, 'lon': lon, 'format': 'json', 'addressdetails': 1, 'zoom': 18},
            headers={'User-Agent': USER_AGENT},
            timeout=8,
        )
        if response.status_code == 200:
            display = (response.json().get('display_name') or '').strip()
            cache[key] = display
            return display
    except Exception:
        pass
    cache[key] = ''
    return ''


def _dedupe_key(name: str, lat: float, lon: float) -> Tuple[str, float, float]:
    return (name.lower().strip(), round(lat, 4), round(lon, 4))


def _place_from_coords(
    name: str,
    lat: float,
    lon: float,
    origin_lat: float,
    origin_lng: float,
    place_kind: str,
    address: str = '',
    phone: str = '',
    tags: Optional[dict] = None,
    strict: bool = True,
) -> Optional[dict]:
    tags = tags or {}
    if place_kind == 'pharmacy':
        if not _is_valid_pharmacy(name, tags, strict=strict):
            return None
    else:
        if not _is_valid_clinic(name, tags, strict=strict):
            return None

    opening_hours = (tags.get('opening_hours') or '').strip()
    is_open, hours_display = _parse_open_status(opening_hours)
    is_24_7 = bool(re.search(r'24\s*[/x×]\s*7', opening_hours, re.I)) if opening_hours else False
    rating = tags.get('rating') or tags.get('stars') or ''
    try:
        rating_val = float(rating) if rating else None
    except (TypeError, ValueError):
        rating_val = None

    emergency = place_kind == 'clinic' and (
        tags.get('emergency') == 'yes'
        or (tags.get('amenity') or '') in ('hospital', 'clinic', 'doctors')
        or (tags.get('healthcare') or '') == 'hospital'
    )

    addr = address or build_osm_address(tags)
    return {
        'id': f"{round(lat, 5)}_{round(lon, 5)}_{name.lower().replace(' ', '_')[:48]}",
        'name': name,
        'address': addr,
        'address_pending': not addr,
        'phone': phone or (tags.get('phone') or tags.get('contact:phone') or ''),
        'lat': lat,
        'lng': lon,
        'distance_km': haversine_km(origin_lat, origin_lng, lat, lon),
        'open': is_open,
        'opening_hours': hours_display,
        'is_24_7': is_24_7,
        'rating': rating_val,
        'emergency': emergency,
    }


def _parse_element(
    element: dict,
    origin_lat: float,
    origin_lng: float,
    place_kind: str,
    strict: bool = True,
) -> Optional[dict]:
    tags = element.get('tags') or {}
    name = _resolve_name(tags)
    if not name:
        name = _fallback_place_name(tags, place_kind) if not strict else None
    if not name:
        return None
    elat, elon = _element_coords(element)
    if elat is None or elon is None:
        return None
    return _place_from_coords(
        name, elat, elon, origin_lat, origin_lng, place_kind, tags=tags, strict=strict
    )


def _nominatim_search(
    lat: float,
    lng: float,
    queries: List[str],
    place_kind: str,
    origin_lat: float,
    origin_lng: float,
    radius_m: int = 5000,
) -> List[dict]:
    max_km = max(radius_m / 1000.0, 1.0)
    delta = max_km / 111.0
    cos_lat = max(math.cos(math.radians(lat)), 0.2)
    delta_lng = max_km / (111.0 * cos_lat)
    viewbox = f"{lng - delta_lng},{lat - delta},{lng + delta_lng},{lat + delta}"
    collected = []
    seen = set()

    for q in queries:
        try:
            response = requests.get(
                NOMINATIM_SEARCH,
                params={
                    'q': q,
                    'format': 'json',
                    'limit': 20,
                    'viewbox': viewbox,
                    'bounded': 1,
                    'addressdetails': 1,
                },
                headers={'User-Agent': USER_AGENT},
                timeout=10,
            )
            if response.status_code != 200:
                continue
            for item in response.json():
                name = (item.get('display_name') or '').split(',')[0].strip()
                if not name or len(name) < 3:
                    name = item.get('name') or ''
                if not name:
                    continue
                try:
                    elat = float(item['lat'])
                    elon = float(item['lon'])
                except (KeyError, TypeError, ValueError):
                    continue
                if haversine_km(origin_lat, origin_lng, elat, elon) > max_km:
                    continue
                klass = (item.get('class') or '').lower()
                typ = (item.get('type') or '').lower()
                tags = {
                    'name': name,
                    'amenity': typ if klass == 'amenity' else '',
                    'shop': typ if klass == 'shop' else '',
                    'healthcare': typ if klass == 'healthcare' else '',
                }
                place = _place_from_coords(
                    name, elat, elon, origin_lat, origin_lng, place_kind,
                    address=item.get('display_name', ''),
                    tags=tags,
                    strict=False,
                )
                if not place:
                    continue
                key = _dedupe_key(place['name'], place['lat'], place['lng'])
                if key in seen:
                    continue
                seen.add(key)
                collected.append(place)
            time.sleep(0.35)
        except Exception:
            continue
    return collected


def _pharmacy_overpass_query_minimal(radius_m: int, lat: float, lng: float) -> str:
    return f"""
[out:json][timeout:15];
(
  node["amenity"="pharmacy"](around:{radius_m},{lat},{lng});
  way["amenity"="pharmacy"](around:{radius_m},{lat},{lng});
  node["shop"="chemist"](around:{radius_m},{lat},{lng});
  way["shop"="chemist"](around:{radius_m},{lat},{lng});
  node["shop"="pharmacy"](around:{radius_m},{lat},{lng});
  way["shop"="pharmacy"](around:{radius_m},{lat},{lng});
);
out center 120;
"""


def _pharmacy_overpass_query(radius_m: int, lat: float, lng: float) -> str:
    return f"""
[out:json][timeout:25];
(
  node["amenity"="pharmacy"](around:{radius_m},{lat},{lng});
  way["amenity"="pharmacy"](around:{radius_m},{lat},{lng});
  node["shop"="pharmacy"](around:{radius_m},{lat},{lng});
  way["shop"="pharmacy"](around:{radius_m},{lat},{lng});
  node["shop"="chemist"](around:{radius_m},{lat},{lng});
  way["shop"="chemist"](around:{radius_m},{lat},{lng});
  node["shop"="medical_supply"](around:{radius_m},{lat},{lng});
  way["shop"="medical_supply"](around:{radius_m},{lat},{lng});
  node["shop"="herbalist"](around:{radius_m},{lat},{lng});
  way["shop"="herbalist"](around:{radius_m},{lat},{lng});
  node["healthcare"="pharmacy"](around:{radius_m},{lat},{lng});
  way["healthcare"="pharmacy"](around:{radius_m},{lat},{lng});
  node["healthcare"="chemist"](around:{radius_m},{lat},{lng});
  way["healthcare"="chemist"](around:{radius_m},{lat},{lng});
  node["dispensing"="yes"](around:{radius_m},{lat},{lng});
  way["dispensing"="yes"](around:{radius_m},{lat},{lng});
  node["name"~"Pharmacy|Chemist|Medical Store|Medical Shop|Medico|Medicine Shop|Drug Store|Dispensary",i](around:{radius_m},{lat},{lng});
  way["name"~"Pharmacy|Chemist|Medical Store|Medical Shop|Medico|Medicine Shop|Drug Store|Dispensary",i](around:{radius_m},{lat},{lng});
);
out center 300;
"""


def _clinic_overpass_query_minimal(radius_m: int, lat: float, lng: float) -> str:
    return f"""
[out:json][timeout:15];
(
  node["amenity"~"hospital|clinic|doctors"](around:{radius_m},{lat},{lng});
  way["amenity"~"hospital|clinic|doctors"](around:{radius_m},{lat},{lng});
  node["healthcare"~"hospital|clinic"](around:{radius_m},{lat},{lng});
  way["healthcare"~"hospital|clinic"](around:{radius_m},{lat},{lng});
);
out center 120;
"""


def _clinic_overpass_query(radius_m: int, lat: float, lng: float) -> str:
    return f"""
[out:json][timeout:25];
(
  node["amenity"~"hospital|clinic|doctors|health_centre|health_center|nursing_home"](around:{radius_m},{lat},{lng});
  way["amenity"~"hospital|clinic|doctors|health_centre|health_center|nursing_home"](around:{radius_m},{lat},{lng});
  node["healthcare"~"hospital|clinic|centre|center|doctor|physician|nursing_home|dentist"](around:{radius_m},{lat},{lng});
  way["healthcare"~"hospital|clinic|centre|center|doctor|physician|nursing_home|dentist"](around:{radius_m},{lat},{lng});
  node["building"~"hospital|clinic|health_centre"](around:{radius_m},{lat},{lng});
  way["building"~"hospital|clinic|health_centre"](around:{radius_m},{lat},{lng});
  node["office"="doctor"](around:{radius_m},{lat},{lng});
  way["office"="doctor"](around:{radius_m},{lat},{lng});
  node["name"~"Hospital|Clinic|Health Centre|Health Center|Nursing Home|Multispecial",i](around:{radius_m},{lat},{lng});
  way["name"~"Hospital|Clinic|Health Centre|Health Center|Nursing Home|Multispecial",i](around:{radius_m},{lat},{lng});
  node["emergency"="yes"]["amenity"](around:{radius_m},{lat},{lng});
  way["emergency"="yes"]["amenity"](around:{radius_m},{lng});
);
out center 300;
"""


def _merge_elements_into(
    collected: Dict[Tuple, dict],
    elements: List[dict],
    origin_lat: float,
    origin_lng: float,
    place_kind: str,
    strict: bool = True,
    stats: Optional[dict] = None,
) -> int:
    added = 0
    raw = len(elements)
    rejected = 0
    for element in elements:
        parsed = _parse_element(element, origin_lat, origin_lng, place_kind, strict=strict)
        if not parsed:
            rejected += 1
            continue
        key = _dedupe_key(parsed['name'], parsed['lat'], parsed['lng'])
        if key not in collected:
            collected[key] = parsed
            added += 1
        elif parsed.get('address') and not collected[key].get('address'):
            collected[key]['address'] = parsed['address']
            collected[key]['address_pending'] = False
    if stats is not None:
        stats['raw_elements'] = stats.get('raw_elements', 0) + raw
        stats['rejected'] = stats.get('rejected', 0) + rejected
        stats['added'] = stats.get('added', 0) + added
    return added


def _fetch_overpass_elements(
    query_builder: Callable,
    radii: List[int],
    lat: float,
    lng: float,
    timeout: int,
    parallel: bool,
) -> Tuple[List[dict], int]:
    """Return merged elements and largest radius used."""
    if parallel and len(radii) > 1:
        elements = _run_overpass_parallel(query_builder, radii, lat, lng, timeout)
        if elements:
            return elements, max(radii)
    used = radii[0]
    merged: List[dict] = []
    seen_ids = set()
    for radius in radii:
        used = radius
        batch = _run_overpass(query_builder(radius, lat, lng), timeout=timeout)
        for el in batch:
            eid = (el.get('type'), el.get('id')) or id(el)
            if eid not in seen_ids:
                seen_ids.add(eid)
                merged.append(el)
        if len(merged) >= MIN_RESULTS_BEFORE_STOP:
            break
    return merged, used


def _finalize_addresses(places: List[dict], enrich: bool = False) -> None:
    """Use OSM tags immediately; optional slow reverse-geocode (off by default)."""
    if enrich:
        geocode_cache: Dict[Tuple[float, float], str] = {}
        geocoded = 0
        for place in places:
            if geocoded >= MAX_REVERSE_GEOCODE:
                break
            if place.get('address') and not place.get('address_pending'):
                continue
            enriched = _reverse_geocode(place['lat'], place['lng'], geocode_cache)
            geocoded += 1
            if enriched:
                place['address'] = enriched
                place['address_pending'] = False
            time.sleep(1.02)

    for place in places:
        if not place.get('address'):
            dist = place.get('distance_km')
            suffix = f", {dist} km away" if dist is not None else ''
            place['address'] = f"{place['name']}{suffix}"
        place.pop('address_pending', None)


def _search_parallel(
    lat: float,
    lng: float,
    place_kind: str,
    query_builder: Callable[[int, float, float], str],
    nominatim_queries: List[str],
    fast: bool = True,
    emergency: bool = False,
) -> Tuple[List[dict], int]:
    global _last_search_debug
    _last_search_debug = {
        'place_kind': place_kind,
        'lat': lat,
        'lng': lng,
        'fast': fast,
        'emergency': emergency,
        'events': [],
    }
    collected: Dict[Tuple, dict] = {}
    stats: dict = {'raw_elements': 0, 'rejected': 0, 'added': 0}
    radii = EMERGENCY_RADII_M if emergency else SEARCH_RADII_M
    used_radius = radii[0]
    last_elements: List[dict] = []

    _debug_log(place_kind, 'location', lat=lat, lng=lng)

    minimal_builder = (
        _pharmacy_overpass_query_minimal if place_kind == 'pharmacy' else _clinic_overpass_query_minimal
    )
    for radius in radii:
        used_radius = radius
        before_n = len(collected)
        nominatim_batch = _nominatim_search(
            lat, lng, nominatim_queries, place_kind, lat, lng, radius_m=radius
        )
        for place in nominatim_batch:
            key = _dedupe_key(place['name'], place['lat'], place['lng'])
            if key not in collected:
                collected[key] = place
        _debug_log(
            place_kind,
            'nominatim',
            radius_m=radius,
            batch=len(nominatim_batch),
            count=len(collected),
            new=len(collected) - before_n,
        )
        if len(collected) >= MIN_RESULTS_BEFORE_STOP:
            break

    skip_overpass = fast and len(collected) >= MIN_RESULTS_BEFORE_STOP
    if skip_overpass:
        _debug_log(place_kind, 'overpass_skipped', reason='nominatim_sufficient', count=len(collected))

    if not skip_overpass:
        for radius in radii:
            if len(collected) >= MIN_RESULTS_BEFORE_STOP:
                break
            used_radius = radius
            elements = _run_overpass(minimal_builder(radius, lat, lng), timeout=OVERPASS_TIMEOUT)
            stats['raw_elements'] += len(elements)
            last_elements = elements or last_elements
            before = len(collected)
            _merge_elements_into(collected, elements, lat, lng, place_kind, strict=True, stats=stats)
            _debug_log(
                place_kind,
                'overpass_minimal',
                radius_m=radius,
                elements=len(elements),
                count=len(collected),
                new=len(collected) - before,
            )

        for radius in radii:
            if len(collected) >= MIN_RESULTS_BEFORE_STOP:
                break
            used_radius = radius
            elements = _run_overpass(query_builder(radius, lat, lng), timeout=OVERPASS_TIMEOUT)
            last_elements = elements or last_elements
            stats['raw_elements'] += len(elements)
            before = len(collected)
            _merge_elements_into(collected, elements, lat, lng, place_kind, strict=True, stats=stats)
            _debug_log(
                place_kind,
                'overpass_full',
                radius_m=radius,
                elements=len(elements),
                count=len(collected),
                new=len(collected) - before,
            )
            if len(collected) >= MIN_RESULTS_BEFORE_STOP:
                break

        if len(collected) < MIN_RESULTS_TARGET and last_elements:
            before = len(collected)
            _merge_elements_into(
                collected, last_elements, lat, lng, place_kind, strict=False, stats=stats
            )
            _debug_log(place_kind, 'relaxed_reparse', count=len(collected), new=len(collected) - before)

        if len(collected) < MIN_RESULTS_TARGET:
            for radius in radii:
                nominatim_fallback = _nominatim_search(
                    lat, lng, nominatim_queries[:2], place_kind, lat, lng, radius_m=radius
                )
                for place in nominatim_fallback:
                    key = _dedupe_key(place['name'], place['lat'], place['lng'])
                    if key not in collected:
                        collected[key] = place
                if collected:
                    used_radius = max(used_radius, radius)
                    break

    places = list(collected.values())
    places.sort(key=lambda p: (p['distance_km'], p['name'].lower()))
    _finalize_addresses(places, enrich=False)

    _last_search_debug.update({
        'final_count': len(places),
        'search_radius_m': used_radius,
        'stats': stats,
    })
    _debug_log(
        place_kind,
        'done',
        final=len(places),
        radius_m=used_radius,
        rejected=stats.get('rejected', 0),
        raw=stats.get('raw_elements', 0),
    )
    return places, used_radius


def _cached_search(
    lat: float,
    lng: float,
    place_kind: str,
    query_builder: Callable,
    nominatim_queries: List[str],
    fast: bool,
    emergency: bool,
) -> Tuple[List[dict], int]:
    key = _cache_key(lat, lng, place_kind, fast, emergency)
    hit = _cache_get(key)
    if hit and hit[0]:
        _debug_log(place_kind, 'cache_hit', count=len(hit[0]))
        return hit
    result = _search_parallel(
        lat, lng, place_kind, query_builder, nominatim_queries, fast=fast, emergency=emergency
    )
    if result[0]:
        _cache_set(key, result)
    return result


def search_nearby_pharmacies(
    lat: float, lng: float, fast: bool = True, emergency: bool = False
) -> Tuple[List[dict], int]:
    return _cached_search(
        lat,
        lng,
        'pharmacy',
        _pharmacy_overpass_query,
        [
            'pharmacy', 'chemist', 'medical store', 'medical shop', 'drugstore',
            'dispensary', 'medicine shop',
        ],
        fast,
        emergency,
    )


def search_nearby_clinics(
    lat: float, lng: float, fast: bool = True, emergency: bool = False
) -> Tuple[List[dict], int]:
    return _cached_search(
        lat,
        lng,
        'clinic',
        _clinic_overpass_query,
        ['hospital', 'clinic', 'health centre', 'nursing home', 'doctor clinic', 'medical center'],
        fast,
        emergency,
    )
