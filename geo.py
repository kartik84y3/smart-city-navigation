"""Server-side clients for Nominatim (geocoding) and OSRM (routing).

Calling them from the server lets us:
* send a proper User-Agent (required by the Nominatim usage policy),
* respect the 1-request-per-second limit and cache repeated searches,
* turn network failures into friendly, consistent error messages.

Only the Python standard library is used (urllib), so no extra dependency.
Neither service provides live traffic. OSRM durations are free-flow estimates.
"""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


class GeoServiceError(Exception):
    """Error that is safe to show to the user. ``status`` is the HTTP status to return."""

    def __init__(self, message, status=503):
        super().__init__(message)
        self.message = message
        self.status = status


class GeoClient:
    CACHE_SECONDS = 3600
    CACHE_MAX = 200

    def __init__(self, nominatim_url, osrm_url, user_agent, timeout=10):
        self.nominatim_url = nominatim_url.rstrip("/")
        self.osrm_url = osrm_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout = timeout
        self._cache = {}
        self._lock = threading.Lock()
        self._last_nominatim = 0.0

    # ---- low level ------------------------------------------------------
    def _get_json(self, url, service):
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent,
                                                   "Accept": "application/json",
                                                   "Accept-Language": "en"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise GeoServiceError(f"The {service} service is rate-limiting requests. "
                                      "Please wait a few seconds and try again.", 429)
            if e.code == 400 and service == "routing":
                raise GeoServiceError("The routing service could not use those coordinates.", 404)
            raise GeoServiceError(f"The {service} service returned an error ({e.code}). "
                                  "Please try again later.", 503)
        except (urllib.error.URLError, TimeoutError, OSError):
            raise GeoServiceError(f"Could not reach the {service} service. Check your internet "
                                  "connection and try again.", 503)
        except ValueError:
            raise GeoServiceError(f"The {service} service sent an unreadable response.", 503)

    def _throttle(self):
        with self._lock:
            wait = 1.05 - (time.monotonic() - self._last_nominatim)
            if wait > 0:
                time.sleep(wait)
            self._last_nominatim = time.monotonic()

    # ---- geocoding ------------------------------------------------------
    @staticmethod
    def short_label(item):
        parts = [p.strip() for p in item.get("display_name", "").split(",") if p.strip()]
        name = item.get("name") or (parts[0] if parts else "Unnamed place")
        extra = [p for p in parts[1:2] if p != name]
        return ", ".join([name] + extra)

    def geocode(self, query, limit=5):
        q = " ".join(query.split())
        key = q.lower()
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and now - cached[0] < self.CACHE_SECONDS:
            return cached[1]
        self._throttle()
        url = f"{self.nominatim_url}/search?" + urllib.parse.urlencode(
            {"format": "jsonv2", "limit": limit, "q": q})
        data = self._get_json(url, "place search")
        results = []
        for item in data if isinstance(data, list) else []:
            try:
                results.append({"label": self.short_label(item),
                                "display_name": item.get("display_name", ""),
                                "lat": float(item["lat"]), "lon": float(item["lon"])})
            except (KeyError, TypeError, ValueError):
                continue
        if len(self._cache) >= self.CACHE_MAX:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = (now, results)
        return results

    # ---- routing --------------------------------------------------------
    def route(self, origin, dest):
        coords = f"{origin['lon']},{origin['lat']};{dest['lon']},{dest['lat']}"
        url = (f"{self.osrm_url}/route/v1/driving/{coords}?"
               + urllib.parse.urlencode({"overview": "full", "geometries": "geojson",
                                         "alternatives": "true"}))
        data = self._get_json(url, "routing")
        if data.get("code") == "NoRoute" or not data.get("routes"):
            raise GeoServiceError("No driving route was found between these two places "
                                  "(for example, they may be on different islands or have no road link).", 404)
        if data.get("code") != "Ok":
            raise GeoServiceError("The routing service could not calculate this route.", 503)
        return [{"index": i, "distance": r["distance"], "duration": r["duration"],
                 "geometry": r["geometry"]} for i, r in enumerate(data["routes"])]
