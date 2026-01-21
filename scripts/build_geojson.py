import json
import re
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
    # Ejemplos para escalar (cuando tengas más endpoints):
    # {"city": "barcelona", "url": "https://.../Barcelona.xml"},
]

OUT_DIR = "geojson"


def _text(node) -> str:
    if node is None:
        return ""
    return "".join(node.itertext()).strip()


def parse_madrid_like_datex_xml(xml_bytes: bytes) -> List[Dict]:
    """
    Extrae polígonos desde el XML de DGT (Datex2) usando openlrCoordinates.
    Devuelve una lista de features GeoJSON (Polygon), una por cada 'ZONA' (Attribute:id).
    """
    root = etree.fromstring(xml_bytes)

    # Capturamos coordenadas en cualquier namespace usando local-name()
    lat_xpath = ".//*[local-name()='openlrCoordinates']/*[local-name()='latitude']"
    lon_xpath = ".//*[local-name()='openlrCoordinates']/*[local-name()='longitude']"

    # Cada "controlledZone" suele contener su id y un conjunto de corners (coordenadas).
    cz_nodes = root.xpath(".//*[local-name()='controlledZone']")

    features = []
    for cz in cz_nodes:
        # id de zona
        zone_id = cz.get("id") or cz.get("{http://www.w3.org/XML/1998/namespace}id")
        # En tu Power Query venía como Attribute:id, aquí normalmente es atributo "id" o similar.
        # Si no aparece, intentamos encontrar un atributo cualquiera que contenga "Madrid (" como fallback.
        if not zone_id:
            # fallback: busca atributo con 'Madrid' (muy conservador)
            for k, v in cz.attrib.items():
                if isinstance(v, str) and "Madrid" in v:
                    zone_id = v
                    break
        if not zone_id:
            zone_id = "unknown"

        # Nombre: intenta leer <name> ... <value> <Element:Text> (en XML real puede variar)
        # Como no queremos atarnos a namespaces, tomamos el primer <name> textual si existe.
        name_node = cz.xpath(".//*[local-name()='name']")[0] if cz.xpath(".//*[local-name()='name']") else None
        zone_name = _text(name_node) if name_node is not None else zone_id

        # Coordenadas: recorremos openlrCoordinates en orden de aparición
        coords_nodes = cz.xpath(".//*[local-name()='openlrCoordinates']")
        ring: List[Tuple[float, float]] = []
        for c in coords_nodes:
            lat_n = c.xpath("./*[local-name()='latitude']")
            lon_n = c.xpath("./*[local-name()='longitude']")
            if not lat_n or not lon_n:
                continue
            try:
                lat = float(_text(lat_n[0]))
                lon = float(_text(lon_n[0]))
                ring.append((lon, lat))  # GeoJSON = [lon, lat]
            except ValueError:
                continue

        # Si no hay suficientes puntos, saltamos
        if len(ring) < 3:
            continue

        # Cierra el polígono (primer punto al final)
        if ring[0] != ring[-1]:
            ring.append(ring[0])

        features.append(
            {
                "type": "Feature",
                "properties": {
                    "ZONAS": zone_name,
                    "ZBE_ID": zone_id,
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [ring],
                },
            }
        )

    return features


def build_feature_collection(city: str, features: List[Dict]) -> Dict:
    return {
        "type": "FeatureCollection",
        "name": f"zbe_{city}",
        "features": features,
    }


def main():
    # Genera 1 GeoJSON por ciudad + un agregado nacional (si hay varias)
    all_features: List[Dict] = []

    for src in SOURCES:
        city = src["city"]
        url = src["url"]

        r = requests.get(url, timeout=60)
        r.raise_for_status()

        features = parse_madrid_like_datex_xml(r.content)
        # Añadimos CITY a propiedades para filtrar luego en Power BI si quieres
        for f in features:
            f["properties"]["CITY"] = city

        fc = build_feature_collection(city, features)

        out_path = f"{OUT_DIR}/{city}.geojson"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(fc, f, ensure_ascii=False)

        all_features.extend(features)

    if len(SOURCES) > 1:
        fc_all = build_feature_collection("spain_all_zbe", all_features)
        out_path_all = f"{OUT_DIR}/spain_all_zbe.geojson"
        with open(out_path_all, "w", encoding="utf-8") as f:
            json.dump(fc_all, f, ensure_ascii=False)

    print("GeoJSON generado correctamente.")


if __name__ == "__main__":
    main()

