#!/usr/bin/env python3
"""
Builds tirumala_graph.json (the offline ROAD network) from OpenStreetMap.

Run on your computer (needs internet once):
    python3 build_tirumala_graph.py                      # downloads from Overpass
    python3 build_tirumala_graph.py --input overpass.json  # or use a file you saved yourself

Output (host it at OFFLINE_GRAPH_URL):
    tirumala_graph.json = {"nodes":[[lat,lng],...],
                           "edges":[[a,b,meters,flags,oneway,nameIdx],...],
                           "names":["","Some Road",...]}
    flags : 1 = walkable, 2 = drivable          oneway: 1 = vehicles only a -> b

Map data (c) OpenStreetMap contributors, ODbL. Keep that credit somewhere in your app.
"""
import argparse, json, math, sys, urllib.parse, urllib.request
from collections import defaultdict

# south, west, north, east  -- keep the SAME as TIRUMALA_BOUNDS in OfflineMapManager.kt
BBOX = (13.62, 79.29, 13.73, 79.45)

WALK_HW = {"footway", "path", "steps", "pedestrian", "cycleway", "track", "living_street",
           "residential", "service", "unclassified", "tertiary", "tertiary_link", "secondary",
           "secondary_link", "primary", "primary_link", "trunk", "trunk_link", "road"}
DRIVE_HW = {"motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
            "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified",
            "residential", "living_street", "service", "road"}


def haversine(a, b):
    r = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = p2 - p1
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def fetch():
    s, w, n, e = BBOX
    query = f'[out:json][timeout:180];(way["highway"]({s},{w},{n},{e});>;);out body;'
    data = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request("https://overpass-api.de/api/interpreter", data=data,
                                 headers={"User-Agent": "tirumala-offline-graph-builder"})
    print("Downloading roads from Overpass ...", file=sys.stderr)
    with urllib.request.urlopen(req, timeout=240) as r:
        return json.load(r)


def build(osm):
    coords = {el["id"]: (el["lat"], el["lon"]) for el in osm["elements"] if el["type"] == "node"}
    names = [""]
    name_idx = {"": 0}
    raw_edges = []   # (osm_a, osm_b, meters, flags, oneway, nameIdx)

    for el in osm["elements"]:
        if el["type"] != "way":
            continue
        t = el.get("tags", {})
        hw = t.get("highway")
        if not hw:
            continue
        private = t.get("access") in ("no", "private") and t.get("foot") not in ("yes", "designated", "permissive")
        if private:
            continue
        flags = 0
        if hw in WALK_HW and t.get("foot") != "no":
            flags |= 1
        if (hw in DRIVE_HW and t.get("motor_vehicle") not in ("no", "private")
                and t.get("vehicle") not in ("no", "private") and t.get("access") not in ("no", "private")):
            flags |= 2
        if flags == 0:
            continue

        nodes = [n for n in el["nodes"] if n in coords]
        oneway = 0
        ow = t.get("oneway")
        if ow in ("yes", "1", "true") or t.get("junction") == "roundabout":
            oneway = 1
        elif ow == "-1":
            oneway = 1
            nodes.reverse()

        nm = t.get("name:en") or t.get("name") or t.get("ref") or ""
        if nm not in name_idx:
            name_idx[nm] = len(names)
            names.append(nm)

        for a, b in zip(nodes, nodes[1:]):
            if a == b:
                continue
            raw_edges.append((a, b, haversine(coords[a], coords[b]), flags, oneway, name_idx[nm]))

    # keep only the biggest connected piece (so every point can reach every other point)
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b, *_ in raw_edges:
        parent[find(a)] = find(b)
    sizes = defaultdict(int)
    for a, *_ in raw_edges:
        sizes[find(a)] += 1
    if not sizes:
        sys.exit("No roads found in the data.")
    main = max(sizes, key=sizes.get)

    used = sorted({n for a, b, *_ in raw_edges if find(a) == main for n in (a, b)})
    index = {n: i for i, n in enumerate(used)}
    out_nodes = [[round(coords[n][0], 6), round(coords[n][1], 6)] for n in used]
    out_edges = [[index[a], index[b], round(m, 1), f, o, nm]
                 for a, b, m, f, o, nm in raw_edges if find(a) == main]
    return {"nodes": out_nodes, "edges": out_edges, "names": names}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="Overpass JSON saved earlier (skips the download)")
    ap.add_argument("--output", default="tirumala_graph.json")
    args = ap.parse_args()

    if args.input:
        with open(args.input, encoding="utf-8") as f:
            osm = json.load(f)
    else:
        osm = fetch()
    g = build(osm)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(g, f, separators=(",", ":"), ensure_ascii=False)
    print(f"{len(g['nodes'])} nodes, {len(g['edges'])} edges, {len(g['names'])} names -> {args.output}",
          file=sys.stderr)


if __name__ == "__main__":
    main()