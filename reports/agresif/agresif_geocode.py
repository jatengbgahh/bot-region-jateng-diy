"""
Geocoding titik -> KAB/KEC/DESA untuk report /agresif, port PERSIS dari tool
browser GeocodingJatengDIY (index.html + boundaries.js). Dipakai agar kolom
kab2/kec2 di sheet RAW bisa dihasilkan otomatis dari koordinat DB (tanpa langkah
geocoding manual).

BOUNDARY_DATA di-embed di boundaries.js sebagai `window.BOUNDARY_DATA = {...};`
(JSON). Struktur: {cellSize, bounds, features:[{k,c,d,id,bbox,cen,poly}], grid}.
  k = KAB/KOTA, c = KECAMATAN, d = DESA, id = kode desa
  poly = multipolygon: [ [ring_luar, ring_lubang...], ... ], ring = [[lon,lat],...]
  grid = {"gx_gy": [feature_index,...]}  (cellSize derajat)
Algoritma matchPoint identik dgn JS: cek sel grid -> point-in-polygon; kalau
gagal expand 3x3; kalau tetap gagal ambil centroid terdekat (NEAREST <=5km,
selain itu FAR).
"""
import json
import math
import os
import re
import zipfile


class Geocoder:
    def __init__(self, boundary_data: dict):
        self.cell = boundary_data["cellSize"]
        self.bounds = boundary_data["bounds"]
        self.feats = boundary_data["features"]
        self.grid = boundary_data["grid"]

    # ---- loaders -----------------------------------------------------------
    @classmethod
    def from_json_file(cls, path: str) -> "Geocoder":
        with open(path, encoding="utf8") as f:
            return cls(json.load(f))

    @classmethod
    def from_boundaries_js(cls, path: str) -> "Geocoder":
        with open(path, encoding="utf8") as f:
            data = f.read()
        return cls(cls._parse_js(data))

    @classmethod
    def from_geocoding_zip(cls, zip_path: str) -> "Geocoder":
        with zipfile.ZipFile(zip_path) as z:
            name = next(n for n in z.namelist() if n.endswith("boundaries.js"))
            data = z.read(name).decode("utf8", "ignore")
        return cls(cls._parse_js(data))

    @staticmethod
    def _parse_js(data: str) -> dict:
        pre = "window.BOUNDARY_DATA = "
        i = data.find("{")
        body = data[i:].rstrip().rstrip(";")
        return json.loads(body)

    # ---- point-in-polygon (port dari JS) -----------------------------------
    @staticmethod
    def _point_in_ring(x, y, ring) -> bool:
        inside = False
        n = len(ring)
        j = n - 1
        for i in range(n):
            xi, yi = ring[i][0], ring[i][1]
            xj, yj = ring[j][0], ring[j][1]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside

    def _point_in_poly_rings(self, x, y, rings) -> bool:
        if not self._point_in_ring(x, y, rings[0]):
            return False
        for k in range(1, len(rings)):
            if self._point_in_ring(x, y, rings[k]):
                return False
        return True

    def _point_in_feature(self, x, y, feat) -> bool:
        bb = feat["bbox"]
        if x < bb[0] or x > bb[2] or y < bb[1] or y > bb[3]:
            return False
        for poly in feat["poly"]:
            if self._point_in_poly_rings(x, y, poly):
                return True
        return False

    @staticmethod
    def _haversine(lon1, lat1, lon2, lat2):
        R = 6371000.0
        tr = math.pi / 180.0
        d_lat = (lat2 - lat1) * tr
        d_lon = (lon2 - lon1) * tr
        a = (math.sin(d_lat / 2) ** 2
             + math.cos(lat1 * tr) * math.cos(lat2 * tr) * math.sin(d_lon / 2) ** 2)
        return 2 * R * math.asin(math.sqrt(a))

    def _cands(self, gx, gy):
        return self.grid.get(f"{gx}_{gy}", [])

    def match_point(self, x, y) -> dict:
        if x is None or y is None or (isinstance(x, float) and math.isnan(x)) \
                or (isinstance(y, float) and math.isnan(y)):
            return {"status": "NO_COORD"}
        cell = self.cell
        gx = math.floor(x / cell)
        gy = math.floor(y / cell)
        for i in self._cands(gx, gy):
            if self._point_in_feature(x, y, self.feats[i]):
                return {"status": "EXACT", "feat": self.feats[i]}
        # expand 3x3
        s = set(self._cands(gx, gy))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                for i in self._cands(gx + dx, gy + dy):
                    s.add(i)
        for i in s:
            if self._point_in_feature(x, y, self.feats[i]):
                return {"status": "EXACT", "feat": self.feats[i]}
        # fallback nearest centroid
        source = [self.feats[i] for i in s] if s else self.feats
        best, best_d = None, float("inf")
        for f in source:
            d = self._haversine(x, y, f["cen"][0], f["cen"][1])
            if d < best_d:
                best_d, best = d, f
        if best and best_d <= 5000:
            return {"status": "NEAREST", "feat": best, "dist": round(best_d)}
        if best:
            return {"status": "FAR", "feat": best, "dist": round(best_d)}
        return {"status": "NOT_FOUND"}

    def kab_kec(self, x, y):
        """Return (KAB_KOTA, KECAMATAN, DESA, status) untuk (lon,lat)."""
        m = self.match_point(x, y)
        f = m.get("feat")
        if f:
            return f["k"], f["c"], f["d"], m["status"]
        return "", "", "", m["status"]


def parse_coord(raw):
    """Port dari parseCoord() JS: bersihkan spasi & normalisasi koma/titik."""
    if raw is None or raw == "":
        return float("nan")
    s = str(raw).strip()
    s = re.sub(r"[\s]", "", s)
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return float("nan")
