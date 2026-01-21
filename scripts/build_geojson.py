import json
import math
from typing import Dict, List, Tuple

import requests
from lxml import etree

# =========================
# CONFIG
# =========================
SOURCES = [
    {
        "city": "madrid",
        "url": "https://infocar.dgt.es/datex2/v3/dgt/zbe/ControledZonePublication/Madrid.xml",
    },
    # Para escalar luego:
    # {"city": "barcelona", "url": "https://.../Barcelona.xml"},
]

OUT_DIR = "geojson"


def _text(node) -> str:
    if node is None:
        return ""
    return "".join(node.itertext()).strip()


def order_ring(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """
    Ordena puntos (lon, lat) alrededor de un centro para evitar cruces.
    Nota: funciona bien para anillos simples. Para geometrías muy complejas
    podría requerir tratamiento GIS más avanzado, pero para estos feeds suele bastar.
    """
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)

    return sorted(points, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))


def parse_madrid_like_datex_xml(xml_bytes: bytes) -> List[Dict]:
    """
    Extrae geometrías desde el XML DGT (Datex2) usando openlrPolygonCorners/openlrCoordinates.

    Cambio clave:
    - En vez de concatenar todos los puntos en un solo Polygon (lo que genera cruces),
      tratamos cada bloque <openlrPolygonCorners> como un anillo/polígono independiente
      y construimos un MultiPolygon por zona.
    """
    root = etree.fromstring(xml_bytes)
    cz_nodes = root.xpath(".//*[local-name()='controlledZone']")
    features: List[Dict] = []

    for cz in cz_nodes:
        # Identificador estable (si no existe, dejamos "unknown")
        zone_id = cz.get("id") or "unknown"

        # Nombre legible (si existe)
        name_nodes = cz.xpath(".//*[local-name()='name']")
        zone_name = _text(name_nodes[0]) if name_nodes else zone_id

        # Cada openlrPolygonCorners = UN polígono (anillo)
        multipolygons: List[List[List[Tuple[float, float]]]] = []
        polygon_nodes = cz.xpath(".//*[local-name()='openlrPolygonCorners']")

        for poly in polygon_nodes:
            coords_nodes = poly.xpath(".//*[local-name()='openlrCoordinates']")
            ring: List[Tuple[float, float]] = []

            for c in coords_nodes:
                lat_n = c.xpath("./*[local-name()='latitude']")
                lon_n = c.xpath("./*[local-name()='longitude']")
                if not lat_n or not lon_n:
                    continue
                try:
                    lon = float(_text(lon_n[0]))
                    lat = float(_text(lat_n[0]))
                    ring.append((lon, lat))  # GeoJSON => [lon, lat]
                except ValueError:
                    continue

            # Necesitamos al menos 3 puntos para un polígono
            if len(ring) < 3:
                continue

            # Ordenar para minimizar cruces
            ring = order_ring(ring)

            # Cerrar anillo
            if ring[0] != ring[-1]:
                ring.append(ring[0])

            # GeoJSON MultiPolygon: lista de polígonos, cada polígono es lista de anillos (aquí 1 anillo)
            multipolygons.append([ring])

        if not multipolygons:
            continue

        features.append(
            {
                "type": "Feature",
                "properties": {
                    "ZONAS": zone_name,
                    "ZBE_ID": zone_id,
                },
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": multipolygons,
                },
            }
        )

    return features


def build_feature_collection(name: str, features: List[Dict]) -> Dict:
    return {
        "type": "FeatureCollection",
        "name": name,
        "features": features,
    }


def main():
    all_features: List[Dict] = []

    for src in SOURCES:
        city = src["city"]
        url = src["url"]

        r = requests.get(url, timeout=60)
        r.raise_for_status()

        features = parse_madrid_like_datex_xml(r.content)

        # Añadimos CITY como atributo útil para filtros
        for f in features:
            f["properties"]["CITY"] = city

        fc = build_feature_collection(f"zbe_{city}", features)

        out_path = f"{OUT_DIR}/{city}.geojson"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(fc, f, ensure_ascii=False)

        all_features.extend(features)

    # Si algún día añades más fuentes, puedes generar un “agregado”
    if len(SOURCES) > 1:
        fc_all = build_feature_collection("zbe_spain_all", all_features)
        out_path_all = f"{OUT_DIR}/spain_all_zbe.geojson"
        with open(out_path_all, "w", encoding="utf-8") as f:
            json.dump(fc_all, f, ensure_ascii=False)

    print("GeoJSON generado correctamente.")


if __name__ == "__main__":
    main()
