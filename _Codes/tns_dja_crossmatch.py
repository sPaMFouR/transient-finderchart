#!/usr/bin/env python3
"""
Fetch classified TNS transients and cross-match their coordinates with
DAWN/DJA JWST coverage.

Required TNS credentials:

    export TNS_API_KEY="..."
    export TNS_BOT_ID="197912"
    export TNS_BOT_NAME="ARGUSBot"

Example:

    python3 tns_dja_crossmatch.py \
        --reported-within-days 30 \
        --output-dir results
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import requests


TNS_BASE_URL = "https://www.wis-tns.org/api/get"
TNS_SEARCH_URL = "https://www.wis-tns.org/search"
TNS_STAGED_PUBLIC_OBJECTS_URL = (
    "https://www.wis-tns.org/system/files/tns_public_objects/"
    "tns_public_objects.csv.zip"
)
DJA_API_BASE_URL = "https://grizli-cutout.herokuapp.com"
DJA_DASHBOARD_BASE_URL = "https://dawn-cph.github.io/dja/assets/dashboard"
MAST_API_URL = "https://mast.stsci.edu/api/v0/invoke"
DJA_DASHBOARD_TABLES = {
    "imaging": "imaging.csv",
    "nirspec": "nirspec.csv",
    "mirispec": "mirispec.csv",
}


@dataclass
class Transient:
    name: str
    prefix: str
    objid: str
    ra: float
    dec: float
    transient_type: str
    redshift: str
    host_name: str = ""
    host_redshift: str = ""
    public_timestamp: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch classified TNS transients and find matching DJA/JWST coverage."
    )
    parser.add_argument(
        "--tns-source",
        choices=("staged-csv", "web-csv", "api"),
        default="staged-csv",
        help=(
            "Fetch TNS rows from the daily staged public CSV by default. "
            "Use web-csv only for small search-page queries, api only for "
            "small authenticated API queries."
        ),
    )
    parser.add_argument(
        "--reported-within-days",
        type=float,
        default=None,
        help="Optional recent-publication filter. Default is no date cut.",
    )
    parser.add_argument(
        "--public-since",
        help="UTC lower bound for TNS public_timestamp, e.g. 2026-05-01 or 2026-05-01T00:00:00.",
    )
    parser.add_argument(
        "--all-tns",
        action="store_true",
        help="Do not add a public_timestamp lower bound. This can be large and slow.",
    )
    parser.add_argument(
        "--no-classified-search-filter",
        action="store_true",
        help="Do not send classified_sne=1 in the TNS search request.",
    )
    parser.add_argument("--redshift-min", type=float, default=None)
    parser.add_argument(
        "--redshift-max",
        type=float,
        default=0.025,
        help="Maximum SN redshift to fetch from TNS. Default: 0.025.",
    )
    parser.add_argument(
        "--tns-detail-mode",
        choices=("never", "missing", "all"),
        default="never",
        help="Authenticated API object lookups after search. Default never avoids TNS rate limits.",
    )
    parser.add_argument(
        "--tns-staged-csv",
        help=(
            "Optional local tns_public_objects.csv or .csv.zip file. "
            "If not supplied, the script downloads the current staged file."
        ),
    )
    parser.add_argument(
        "--tns-search-json",
        help="JSON object merged into each TNS search request for extra TNS filters.",
    )
    parser.add_argument(
        "--tns-input-csv",
        help="Skip TNS fetching and read name, ra, dec, type, redshift from this CSV.",
    )
    parser.add_argument("--max-transients", type=int)
    parser.add_argument("--tns-page-size", type=int, default=100)
    parser.add_argument("--tns-max-pages", type=int, default=1000)
    parser.add_argument("--tns-sleep", type=float, default=1.0)
    parser.add_argument("--dja-radius-arcmin", type=float, default=0.05)
    parser.add_argument("--nirspec-radius-arcsec", type=float, default=1.0)
    parser.add_argument("--dashboard-radius-arcmin", type=float, default=2.0)
    parser.add_argument(
        "--match-source",
        choices=("mast", "dja", "both"),
        default="mast",
        help=(
            "Footprint archive to cross-match. Default mast searches all MAST JWST "
            "CAOM footprints. dja searches only DAWN/DJA processed products."
        ),
    )
    parser.add_argument(
        "--mast-radius-arcsec",
        type=float,
        default=1.0,
        help="MAST cone radius around each SN coordinate. Default 1 arcsec.",
    )
    parser.add_argument(
        "--mast-pagesize",
        type=int,
        default=2000,
        help="Maximum MAST rows returned per SN coordinate.",
    )
    parser.add_argument(
        "--mast-public-only",
        action="store_true",
        help="Keep only PUBLIC JWST observations in MAST results.",
    )
    parser.add_argument(
        "--mast-sleep",
        type=float,
        default=0.0,
        help="Seconds to sleep between MAST coordinate queries.",
    )
    parser.add_argument("--skip-dashboard", action="store_true")
    parser.add_argument("--skip-dja-api", action="store_true")
    parser.add_argument("--instruments", default="NIRCAM,NIRISS,NIRSPEC,MIRI")
    parser.add_argument("--output-dir", default="tns_dja_results")
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser.parse_args()


def parse_iso_datetime(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if "T" not in text and " " not in text:
        text += "T00:00:00+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def first_value(row: dict[str, Any], keys: Iterable[str], default: Any = "") -> Any:
    for key in keys:
        if key in row and row[key] not in (None, "", [], {}):
            return row[key]
        current: Any = row
        for part in key.split("."):
            if not isinstance(current, dict) or part not in current:
                current = None
                break
            current = current[part]
        if current not in (None, "", [], {}):
            return current
    return default


def normalize_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return str(first_value(value, ("name", "value", "id"), ""))
    if isinstance(value, list):
        return ";".join(part for item in value if (part := normalize_scalar(item)))
    return str(value).strip()


def parse_ra(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    parts = text.replace("h", ":").replace("m", ":").replace("s", "").split(":")
    if len(parts) < 3:
        parts = text.split()
    if len(parts) < 3:
        return None
    try:
        return (float(parts[0]) + float(parts[1]) / 60.0 + float(parts[2]) / 3600.0) * 15.0
    except ValueError:
        return None


def parse_dec(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    sign = -1.0 if text.startswith("-") else 1.0
    text = text.lstrip("+-")
    parts = text.replace("d", ":").replace("m", ":").replace("s", "").split(":")
    if len(parts) < 3:
        parts = text.split()
    if len(parts) < 3:
        return None
    try:
        return sign * (float(parts[0]) + float(parts[1]) / 60.0 + float(parts[2]) / 3600.0)
    except ValueError:
        return None


def parse_dashboard_coord(value: str) -> tuple[float | None, float | None]:
    text = (value or "").strip().lower()
    if not text.startswith("j"):
        return None, None
    text = text[1:]
    split_at = max(text.find("p"), text.find("m"))
    if split_at <= 0:
        return None, None
    sign_char = text[split_at]
    ra_part = text[:split_at]
    dec_part = text[split_at + 1 :]
    if len(ra_part) < 4 or len(dec_part) < 4:
        return None, None
    try:
        ra = (float(ra_part[0:2]) + float(ra_part[2:4]) / 60.0 + float(ra_part[4:] or 0) / 3600.0) * 15.0
        dec = float(dec_part[0:2]) + float(dec_part[2:4]) / 60.0 + float(dec_part[4:] or 0) / 3600.0
    except ValueError:
        return None, None
    return ra, -dec if sign_char == "m" else dec


def angular_sep_arcsec(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    cos_sep = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(r1 - r2)
    cos_sep = max(-1.0, min(1.0, cos_sep))
    return math.degrees(math.acos(cos_sep)) * 3600.0


def read_csv_text(text: str) -> list[dict[str, str]]:
    clean = text.lstrip("\ufeff").strip()
    if not clean or clean.startswith("<"):
        return []
    return list(csv.DictReader(io.StringIO(clean)))


def read_tns_staged_csv_text(text: str) -> list[dict[str, str]]:
    clean = text.lstrip("\ufeff").strip()
    if not clean:
        return []
    lines = clean.splitlines()
    if not lines:
        return []
    if lines[0].lower().startswith('"objid"') or lines[0].lower().startswith("objid,"):
        csv_text = "\n".join(lines)
    else:
        csv_text = "\n".join(lines[1:])
    return list(csv.DictReader(io.StringIO(csv_text)))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


class TNSClient:
    def __init__(self, api_key: str, bot_id: str, bot_name: str, tns_type: str, timeout: float, sleep: float) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.sleep = sleep
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    f'tns_marker{{"tns_id": "{bot_id}", '
                    f'"type": "{tns_type}", "name": "{bot_name}"}}'
                )
            }
        )

    def post(self, endpoint: str, payload: dict[str, Any]) -> Any:
        url = f"{TNS_BASE_URL}/{endpoint.lstrip('/')}"
        for attempt in range(8):
            response = self.session.post(
                url,
                data={"api_key": self.api_key, "data": json.dumps(payload)},
                timeout=self.timeout,
            )
            if response.status_code not in (429, 503):
                break
            retry_after = response.headers.get("Retry-After")
            wait = float(retry_after) if retry_after and retry_after.isdigit() else min(600.0, 30.0 * 2**attempt)
            print(f"TNS rate limit on {endpoint}; sleeping {wait:.0f}s", file=sys.stderr)
            time.sleep(wait)
        if response.status_code >= 400:
            body = response.text.replace("\n", " ")[:1000]
            raise requests.HTTPError(f"{response.status_code} Client Error for {url}: {body}", response=response)
        time.sleep(self.sleep)
        return response.json()

    @staticmethod
    def reply(payload: Any) -> Any:
        if isinstance(payload, list):
            payload = payload[0] if payload else {}
        if not isinstance(payload, dict):
            return []
        data = payload.get("data", {})
        if isinstance(data, dict):
            return data.get("reply", data)
        return data

    def search(self, criteria: dict[str, Any]) -> list[dict[str, Any]]:
        reply = self.reply(self.post("search", criteria))
        if isinstance(reply, list):
            return reply
        if isinstance(reply, dict):
            for key in ("objects", "rows", "results"):
                if isinstance(reply.get(key), list):
                    return reply[key]
            return [reply] if reply else []
        return []

    def get_object(self, objname: str, objid: str = "") -> dict[str, Any]:
        # TNS Get Object requires objname, not name. objid may be blank.
        payload = {"objname": objname, "objid": objid, "photometry": "0", "spectra": "0"}
        reply = self.reply(self.post("object", payload))
        if isinstance(reply, list):
            return reply[0] if reply else {}
        return reply if isinstance(reply, dict) else {}


class DJAClient:
    def __init__(self, timeout: float) -> None:
        self.timeout = timeout
        self.session = requests.Session()

    def get_csv(self, endpoint: str, params: dict[str, Any]) -> list[dict[str, str]]:
        response = self.session.get(f"{DJA_API_BASE_URL}/{endpoint}", params=params, timeout=self.timeout)
        response.raise_for_status()
        return read_csv_text(response.text)

    def exposures(self, ra: float, dec: float, arcmin: float) -> list[dict[str, str]]:
        return self.get_csv("exposures", {"ra": ra, "dec": dec, "arcmin": arcmin})

    def associations(self, ra: float, dec: float, arcmin: float) -> list[dict[str, str]]:
        return self.get_csv("assoc", {"ra": ra, "dec": dec, "arcmin": arcmin, "output": "csv"})

    def mosaics(self, ra: float, dec: float, arcmin: float) -> list[dict[str, str]]:
        return self.get_csv("assoc_mosaic", {"coords": f"{ra},{dec},{arcmin}", "output": "csv"})

    def nirspec_slits(self, ra: float, dec: float, size_arcsec: float) -> list[dict[str, str]]:
        return self.get_csv("nirspec_slits", {"coords": f"{ra},{dec}", "size": size_arcsec, "output": "csv"})

    def nirspec_extractions(self, ra: float, dec: float, size_arcsec: float) -> list[dict[str, str]]:
        return self.get_csv("nirspec_extractions", {"coords": f"{ra},{dec}", "size": size_arcsec, "output": "csv"})


class MASTClient:
    def __init__(self, timeout: float) -> None:
        self.timeout = timeout
        self.session = requests.Session()

    def query_jwst_footprints(
        self,
        ra: float,
        dec: float,
        radius_arcsec: float,
        instruments: set[str],
        pagesize: int,
        public_only: bool,
    ) -> list[dict[str, Any]]:
        radius_deg = radius_arcsec / 3600.0
        filters: list[dict[str, Any]] = [
            {"paramName": "obs_collection", "values": ["JWST"]},
            {"paramName": "intentType", "values": ["science"]},
        ]
        if public_only:
            filters.append({"paramName": "dataRights", "values": ["PUBLIC"]})

        request = {
            "service": "Mast.Caom.Filtered.Position",
            "params": {
                "columns": (
                    "obs_collection,obs_id,obsid,proposal_id,proposal_pi,"
                    "dataproduct_type,instrument_name,filters,target_name,"
                    "t_min,t_max,s_ra,s_dec,em_min,em_max,obs_title,"
                    "calib_level,dataRights,sequence_number,s_region"
                ),
                "filters": filters,
                "position": f"{ra}, {dec}, {radius_deg}",
            },
            "format": "json",
            "pagesize": pagesize,
            "removenullcolumns": True,
            "timeout": int(self.timeout),
        }
        response = self.session.post(
            MAST_API_URL,
            data={"request": json.dumps(request)},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            body = response.text.replace("\n", " ")[:1000]
            raise requests.HTTPError(
                f"{response.status_code} Client Error for {MAST_API_URL}: {body}",
                response=response,
            )
        payload = response.json()
        if isinstance(payload, dict) and payload.get("status") == "ERROR":
            raise requests.HTTPError(f"MAST error: {payload.get('msg', payload)}")
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            return []
        return [row for row in rows if filter_instrument({k: str(v) for k, v in row.items()}, instruments)]


def transient_from_tns(search_row: dict[str, Any], object_row: dict[str, Any]) -> Transient | None:
    merged = dict(search_row)
    merged.update(object_row)
    ra = parse_ra(first_value(merged, ("radeg", "ra", "ra_deg", "objra")))
    dec = parse_dec(first_value(merged, ("decdeg", "dec", "declination", "objdec")))
    obj_type = normalize_scalar(
        first_value(
            merged,
            ("object_type.name", "objtype.name", "type.name", "object_type", "objtype", "type"),
        )
    )
    name = normalize_scalar(first_value(merged, ("objname", "name")))
    if ra is None or dec is None or not obj_type or not name:
        return None
    return Transient(
        name=name,
        prefix=normalize_scalar(first_value(merged, ("prefix",))),
        objid=normalize_scalar(first_value(merged, ("objid", "id"))),
        ra=ra,
        dec=dec,
        transient_type=obj_type,
        redshift=normalize_scalar(first_value(merged, ("redshift", "z", "spectroscopic_redshift"))),
        host_name=normalize_scalar(first_value(merged, ("hostname", "host.name", "host"))),
        host_redshift=normalize_scalar(first_value(merged, ("host_redshift", "host.z"))),
        public_timestamp=normalize_scalar(first_value(merged, ("public_timestamp", "public", "reporting_date"))),
    )


def split_tns_name(value: str) -> tuple[str, str]:
    text = value.strip()
    for prefix in ("SN", "AT"):
        if text.upper().startswith(prefix + " "):
            return prefix, text.split(None, 1)[1].strip()
    return "", text


def redshift_value(value: str) -> float | None:
    text = normalize_scalar(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def transient_from_search_row(row: dict[str, Any]) -> Transient | None:
    raw_name = normalize_scalar(first_value(row, ("objname", "name", "Name", "TNS Name")))
    prefix = normalize_scalar(first_value(row, ("prefix", "Prefix", "name_prefix")))
    if raw_name and not prefix:
        parsed_prefix, parsed_name = split_tns_name(raw_name)
        prefix = parsed_prefix
        raw_name = parsed_name

    ra = parse_ra(first_value(row, ("radeg", "ra", "RA", "ra_deg", "objra")))
    dec = parse_dec(first_value(row, ("decdeg", "dec", "DEC", "declination", "objdec")))
    obj_type = normalize_scalar(
        first_value(
            row,
            (
                "object_type.name",
                "objtype.name",
                "type.name",
                "object_type",
                "objtype",
                "type",
                "Type",
                "Obj. Type",
                "Object Type",
            ),
        )
    )
    redshift = normalize_scalar(first_value(row, ("redshift", "Redshift", "z", "spectroscopic_redshift")))
    if ra is None or dec is None or not obj_type or not raw_name:
        return None
    return Transient(
        name=raw_name,
        prefix=prefix,
        objid=normalize_scalar(first_value(row, ("objid", "id", "ID"))),
        ra=ra,
        dec=dec,
        transient_type=obj_type,
        redshift=redshift,
        host_name=normalize_scalar(first_value(row, ("hostname", "Host Name", "host.name", "host"))),
        host_redshift=normalize_scalar(first_value(row, ("host_redshift", "Host Redshift", "host.z"))),
        public_timestamp=normalize_scalar(
            first_value(row, ("public_timestamp", "Public", "public", "reporting_date", "time_received", "creationdate"))
        ),
    )


def load_transients_from_csv(path: Path) -> list[Transient]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    transients = []
    for row in rows:
        ra = parse_ra(first_value(row, ("ra", "RA", "radeg", "ra_deg")))
        dec = parse_dec(first_value(row, ("dec", "DEC", "decdeg", "dec_deg")))
        obj_type = normalize_scalar(first_value(row, ("type", "transient_type", "objtype", "object_type")))
        if ra is None or dec is None or not obj_type:
            continue
        transients.append(
            Transient(
                name=normalize_scalar(first_value(row, ("name", "objname", "tns_name"))),
                prefix=normalize_scalar(first_value(row, ("prefix",))),
                objid=normalize_scalar(first_value(row, ("objid", "id"))),
                ra=ra,
                dec=dec,
                transient_type=obj_type,
                redshift=normalize_scalar(first_value(row, ("redshift", "z"))),
                host_name=normalize_scalar(first_value(row, ("host_name", "hostname"))),
                host_redshift=normalize_scalar(first_value(row, ("host_redshift",))),
                public_timestamp=normalize_scalar(first_value(row, ("public_timestamp", "public"))),
            )
        )
    return transients


def build_tns_search_criteria(args: argparse.Namespace) -> dict[str, Any]:
    criteria: dict[str, Any] = {}
    if not args.no_classified_search_filter:
        criteria["classified_sne"] = "1"
    if args.redshift_min is not None:
        criteria["redshift_min"] = args.redshift_min
    if args.redshift_max is not None:
        criteria["redshift_max"] = args.redshift_max
    if not args.all_tns:
        if args.public_since:
            since = parse_iso_datetime(args.public_since)
            criteria["public_timestamp"] = since.strftime("%Y-%m-%d %H:%M:%S")
        elif args.reported_within_days is not None:
            since = datetime.now(timezone.utc) - timedelta(days=args.reported_within_days)
            criteria["public_timestamp"] = since.strftime("%Y-%m-%d %H:%M:%S")
    if args.tns_search_json:
        extra = json.loads(args.tns_search_json)
        if not isinstance(extra, dict):
            raise SystemExit("--tns-search-json must be a JSON object")
        criteria.update(extra)
    return criteria


def tns_search_csv_params(args: argparse.Namespace, page: int) -> dict[str, Any]:
    params: dict[str, Any] = {
        "format": "csv",
        "page": page,
        "num_page": args.tns_page_size,
        "order": "name",
        "sort": "asc",
        "classified_sne": "0" if args.no_classified_search_filter else "1",
        "redshift_min": "" if args.redshift_min is None else args.redshift_min,
        "redshift_max": "" if args.redshift_max is None else args.redshift_max,
        "isTNS_AT": "all",
        "public": "all",
        "name": "",
        "name_like": "0",
        "edit[objname]": "",
        "edit[type]": "",
        "type[]": "null",
        "display[redshift]": "1",
        "display[hostname]": "1",
        "display[host_redshift]": "1",
        "display[public]": "1",
        "display[internal_name]": "1",
        "display[discoverydate]": "1",
        "display[discoverymag]": "1",
        "display[discmagfilter]": "1",
    }
    if args.reported_within_days is not None:
        params["reported_within_last_value"] = args.reported_within_days
        params["reported_within_last_units"] = "days"
    return params


def tns_marker_headers() -> dict[str, str]:
    bot_id = os.environ.get("TNS_BOT_ID")
    bot_name = os.environ.get("TNS_BOT_NAME")
    tns_type = os.environ.get("TNS_TYPE", "bot")
    if not bot_id or not bot_name:
        return {}
    return {
        "User-Agent": (
            f'tns_marker{{"tns_id": "{bot_id}", '
            f'"type": "{tns_type}", "name": "{bot_name}"}}'
        )
    }


def browser_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0 Safari/537.36"
        )
    }


def filter_transient_list(transients: list[Transient], args: argparse.Namespace) -> list[Transient]:
    filtered: list[Transient] = []
    seen: set[str] = set()
    for transient in transients:
        if not args.no_classified_search_filter and not transient.transient_type.upper().startswith("SN"):
            continue
        z = redshift_value(transient.redshift)
        if args.redshift_min is not None and (z is None or z < args.redshift_min):
            continue
        if args.redshift_max is not None and (z is None or z > args.redshift_max):
            continue
        key = f"{transient.prefix}{transient.name}"
        if key in seen:
            continue
        seen.add(key)
        filtered.append(transient)
        if args.max_transients and len(filtered) >= args.max_transients:
            break
    return filtered


def read_tns_staged_csv_file(path: Path) -> list[dict[str, str]]:
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as zf:
            csv_names = [name for name in zf.namelist() if name.lower().endswith(".csv")]
            if not csv_names:
                raise SystemExit(f"No CSV file found inside {path}")
            with zf.open(csv_names[0]) as handle:
                return read_tns_staged_csv_text(handle.read().decode("utf-8", errors="replace"))
    return read_tns_staged_csv_text(path.read_text(encoding="utf-8", errors="replace"))


def fetch_tns_staged_csv_transients(args: argparse.Namespace) -> list[Transient]:
    if args.tns_staged_csv:
        rows = read_tns_staged_csv_file(Path(args.tns_staged_csv))
    else:
        api_key = os.environ.get("TNS_API_KEY")
        headers = tns_marker_headers()
        if not api_key or not headers:
            raise SystemExit(
                "The TNS staged CSV download needs TNS_API_KEY, TNS_BOT_ID, and TNS_BOT_NAME. "
                "Set those env vars, or provide --tns-staged-csv /path/to/tns_public_objects.csv.zip. "
                "For a small unauthenticated query, use --tns-source web-csv."
            )
        print("Downloading TNS staged public objects CSV...", file=sys.stderr)
        response = requests.post(
            TNS_STAGED_PUBLIC_OBJECTS_URL,
            headers=headers,
            data={"api_key": api_key},
            timeout=args.timeout,
        )
        if response.status_code >= 400:
            body = response.text.replace("\n", " ")[:1000]
            raise requests.HTTPError(
                f"{response.status_code} Client Error for {TNS_STAGED_PUBLIC_OBJECTS_URL}: {body}",
                response=response,
            )
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            csv_names = [name for name in zf.namelist() if name.lower().endswith(".csv")]
            if not csv_names:
                raise SystemExit("TNS staged zip did not contain a CSV file")
            with zf.open(csv_names[0]) as handle:
                rows = read_tns_staged_csv_text(handle.read().decode("utf-8", errors="replace"))

    transients = [transient for row in rows if (transient := transient_from_search_row(row))]
    return filter_transient_list(transients, args)


def fetch_tns_web_csv_transients(args: argparse.Namespace) -> list[Transient]:
    session = requests.Session()
    session.headers.update(browser_headers())
    transients: list[Transient] = []
    seen: set[str] = set()
    for page in range(args.tns_max_pages):
        print(f"TNS public CSV page {page}...", file=sys.stderr)
        params = tns_search_csv_params(args, page)
        for attempt in range(8):
            response = session.get(TNS_SEARCH_URL, params=params, timeout=args.timeout)
            if response.status_code not in (429, 503):
                break
            retry_after = response.headers.get("Retry-After")
            wait = float(retry_after) if retry_after and retry_after.isdigit() else min(600.0, 30.0 * 2**attempt)
            print(f"TNS public CSV rate limit; sleeping {wait:.0f}s", file=sys.stderr)
            time.sleep(wait)
        if response.status_code >= 400:
            body = response.text.replace("\n", " ")[:1000]
            raise requests.HTTPError(
                f"{response.status_code} Client Error for {TNS_SEARCH_URL}: {body}",
                response=response,
            )
        rows = read_csv_text(response.text)
        if not rows:
            break

        page_added = 0
        for row in rows:
            transient = transient_from_search_row(row)
            if transient is None:
                continue
            z = redshift_value(transient.redshift)
            if args.redshift_min is not None and (z is None or z < args.redshift_min):
                continue
            if args.redshift_max is not None and (z is None or z > args.redshift_max):
                continue
            key = f"{transient.prefix}{transient.name}"
            if key in seen:
                continue
            seen.add(key)
            transients.append(transient)
            page_added += 1
            if args.max_transients and len(transients) >= args.max_transients:
                return transients
        if len(rows) < args.tns_page_size or page_added == 0:
            break
    return transients


def fetch_tns_transients(args: argparse.Namespace) -> list[Transient]:
    api_key = os.environ.get("TNS_API_KEY")
    bot_id = os.environ.get("TNS_BOT_ID")
    bot_name = os.environ.get("TNS_BOT_NAME")
    tns_type = os.environ.get("TNS_TYPE", "bot")
    missing = [key for key, value in (("TNS_API_KEY", api_key), ("TNS_BOT_ID", bot_id), ("TNS_BOT_NAME", bot_name)) if not value]
    if missing:
        raise SystemExit(f"Missing TNS credential environment variable(s): {', '.join(missing)}")

    client = TNSClient(api_key or "", bot_id or "", bot_name or "", tns_type, args.timeout, args.tns_sleep)
    base_criteria = build_tns_search_criteria(args)
    transients: list[Transient] = []
    seen: set[str] = set()

    for page in range(args.tns_max_pages):
        criteria = dict(base_criteria)
        criteria.update({"page": page, "num_page": args.tns_page_size})
        print(f"TNS search page {page}...", file=sys.stderr)
        rows = client.search(criteria)
        if not rows:
            break

        for row in rows:
            name = normalize_scalar(first_value(row, ("objname", "name")))
            objid = normalize_scalar(first_value(row, ("objid", "id")))
            if not name or name in seen:
                continue
            seen.add(name)
            transient = transient_from_search_row(row)
            needs_detail = args.tns_detail_mode == "all" or (
                args.tns_detail_mode == "missing" and transient is None
            )
            if needs_detail:
                try:
                    obj = client.get_object(name, objid)
                except requests.RequestException as exc:
                    print(f"WARNING: failed TNS object lookup for {name}: {exc}", file=sys.stderr)
                    continue
                transient = transient_from_tns(row, obj)
            if transient is not None:
                z = redshift_value(transient.redshift)
                if args.redshift_min is not None and (z is None or z < args.redshift_min):
                    continue
                if args.redshift_max is not None and (z is None or z > args.redshift_max):
                    continue
                transients.append(transient)
            if args.max_transients and len(transients) >= args.max_transients:
                return transients

        if len(rows) < args.tns_page_size:
            break

    return transients


def download_dashboard_tables(timeout: float) -> list[dict[str, Any]]:
    session = requests.Session()
    out: list[dict[str, Any]] = []
    for table_name, filename in DJA_DASHBOARD_TABLES.items():
        url = f"{DJA_DASHBOARD_BASE_URL}/{filename}"
        try:
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"WARNING: failed to fetch {url}: {exc}", file=sys.stderr)
            continue
        for row in read_csv_text(response.text):
            row["_dashboard_table"] = table_name
            row["_dashboard_url"] = url
            ra = parse_ra(first_value(row, ("ra", "RA", "radeg", "ra_deg")))
            dec = parse_dec(first_value(row, ("dec", "DEC", "decdeg", "dec_deg")))
            if (ra is None or dec is None) and row.get("coords"):
                ra, dec = parse_dashboard_coord(row["coords"])
            if ra is not None and dec is not None:
                row["_ra_deg"] = ra
                row["_dec_deg"] = dec
                out.append(row)
    return out


def filter_instrument(row: dict[str, str], instruments: set[str]) -> bool:
    if not instruments:
        return True
    text = " ".join(
        normalize_scalar(first_value(row, keys)).upper()
        for keys in (
            ("instrume", "instrument", "instrument_name"),
            ("exp_type",),
            ("detector",),
            ("filter",),
            ("pupil",),
            ("grating",),
        )
    )
    return any(instrument in text for instrument in instruments)


def summarize_rows(rows: list[dict[str, str]], keys: tuple[str, ...], max_items: int = 8) -> str:
    values: list[str] = []
    for row in rows:
        value = normalize_scalar(first_value(row, keys))
        if value and value not in values:
            values.append(value)
        if len(values) >= max_items:
            break
    return ";".join(values)


def mjd_to_iso(value: Any) -> str:
    text = normalize_scalar(value)
    if not text:
        return ""
    try:
        mjd = float(text)
    except ValueError:
        return text
    epoch = datetime(1858, 11, 17, tzinfo=timezone.utc)
    return (epoch + timedelta(days=mjd)).strftime("%Y-%m-%dT%H:%M:%SZ")


def match_row(
    transient: Transient,
    source: str,
    rows: list[dict[str, str]],
    instrument: str,
    product: str = "",
    assoc: str = "",
    url: str = "",
    notes: str = "",
) -> dict[str, Any]:
    return {
        "match_source": source,
        "tns_name": transient.name,
        "tns_prefix": transient.prefix,
        "tns_ra": transient.ra,
        "tns_dec": transient.dec,
        "tns_type": transient.transient_type,
        "tns_redshift": transient.redshift,
        "separation_arcsec": "0.000",
        "instrument": instrument,
        "proposal_id": summarize_rows(rows, ("proposal_id", "program", "proposal")),
        "target": summarize_rows(rows, ("target", "targprop", "root")),
        "filter_or_grating": summarize_rows(rows, ("filter", "pupil", "grating", "bandpass")),
        "observed": summarize_rows(rows, ("dateobs", "date_obs", "expstart", "observed")),
        "release": "",
        "product_or_dataset": product,
        "assoc_name": assoc,
        "dja_table": "",
        "url": url,
        "notes": notes,
    }


def mast_matches_for_transient(
    transient: Transient,
    mast: MASTClient,
    args: argparse.Namespace,
    instruments: set[str],
) -> list[dict[str, Any]]:
    try:
        rows = mast.query_jwst_footprints(
            transient.ra,
            transient.dec,
            radius_arcsec=args.mast_radius_arcsec,
            instruments=instruments,
            pagesize=args.mast_pagesize,
            public_only=args.mast_public_only,
        )
    except requests.RequestException as exc:
        print(f"WARNING: MAST JWST footprint query failed for {transient.name}: {exc}", file=sys.stderr)
        return []

    matches: list[dict[str, Any]] = []
    seen_obs: set[str] = set()
    for row in rows:
        obsid = normalize_scalar(first_value(row, ("obsid",)))
        obs_id = normalize_scalar(first_value(row, ("obs_id",)))
        key = obsid or obs_id
        if key and key in seen_obs:
            continue
        if key:
            seen_obs.add(key)

        t_min = first_value(row, ("t_min",))
        t_max = first_value(row, ("t_max",))
        observed = mjd_to_iso(t_min)
        if t_max not in (None, ""):
            observed = f"{observed}/{mjd_to_iso(t_max)}" if observed else mjd_to_iso(t_max)

        instrument = normalize_scalar(first_value(row, ("instrument_name",))).upper()
        matches.append(
            {
                "match_source": "mast_caom_footprint",
                "tns_name": transient.name,
                "tns_prefix": transient.prefix,
                "tns_ra": transient.ra,
                "tns_dec": transient.dec,
                "tns_type": transient.transient_type,
                "tns_redshift": transient.redshift,
                "separation_arcsec": "0.000",
                "instrument": instrument,
                "proposal_id": first_value(row, ("proposal_id",)),
                "target": first_value(row, ("target_name",)),
                "filter_or_grating": first_value(row, ("filters",)),
                "observed": observed,
                "release": first_value(row, ("dataRights",)),
                "product_or_dataset": obs_id,
                "assoc_name": "",
                "dja_table": "",
                "url": "https://mast.stsci.edu/portal/Mashup/Clients/Mast/Portal.html",
                "notes": f"MAST CAOM JWST science footprint within {args.mast_radius_arcsec} arcsec.",
                "obs_id": obs_id,
                "obsid": obsid,
                "data_rights": first_value(row, ("dataRights",)),
                "dataproduct_type": first_value(row, ("dataproduct_type",)),
                "calib_level": first_value(row, ("calib_level",)),
                "proposal_pi": first_value(row, ("proposal_pi",)),
                "obs_title": first_value(row, ("obs_title",)),
            }
        )

    if args.mast_sleep > 0:
        time.sleep(args.mast_sleep)
    return matches


def dja_matches_for_transient(transient: Transient, dja: DJAClient, args: argparse.Namespace, instruments: set[str]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []

    queries = (
        ("dja_exposure_footprint", lambda: dja.exposures(transient.ra, transient.dec, args.dja_radius_arcmin)),
        ("dja_association", lambda: dja.associations(transient.ra, transient.dec, args.dja_radius_arcmin)),
        ("dja_processed_mosaic", lambda: dja.mosaics(transient.ra, transient.dec, args.dja_radius_arcmin)),
    )
    for source, func in queries:
        try:
            rows = [row for row in func() if filter_instrument(row, instruments)]
        except requests.RequestException as exc:
            print(f"WARNING: {source} failed for {transient.name}: {exc}", file=sys.stderr)
            continue
        by_instr: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            instr = normalize_scalar(first_value(row, ("instrume", "instrument", "instrument_name"))).upper() or "JWST"
            by_instr.setdefault(instr, []).append(row)
        for instr, instr_rows in by_instr.items():
            matches.append(
                match_row(
                    transient,
                    source,
                    instr_rows,
                    instr,
                    product=summarize_rows(instr_rows, ("dataset", "file", "root")),
                    assoc=summarize_rows(instr_rows, ("assoc_name",)),
                    notes=f"{len(instr_rows)} rows include or are near the transient coordinate.",
                )
            )

    if "NIRSPEC" in instruments:
        for source, func in (
            ("dja_nirspec_slit", lambda: dja.nirspec_slits(transient.ra, transient.dec, args.nirspec_radius_arcsec)),
            ("dja_nirspec_extraction", lambda: dja.nirspec_extractions(transient.ra, transient.dec, args.nirspec_radius_arcsec)),
        ):
            try:
                rows = func()
            except requests.RequestException as exc:
                print(f"WARNING: {source} failed for {transient.name}: {exc}", file=sys.stderr)
                continue
            if rows:
                matches.append(
                    match_row(
                        transient,
                        source,
                        rows,
                        "NIRSPEC",
                        product=summarize_rows(rows, ("file", "root", "msametfl")),
                        notes=f"{len(rows)} rows within {args.nirspec_radius_arcsec} arcsec.",
                    )
                )

    return matches


def dashboard_matches_for_transient(
    transient: Transient,
    dashboard_rows: list[dict[str, Any]],
    radius_arcmin: float,
    instruments: set[str],
) -> list[dict[str, Any]]:
    matches = []
    max_sep = radius_arcmin * 60.0
    for row in dashboard_rows:
        sep = angular_sep_arcsec(transient.ra, transient.dec, float(row["_ra_deg"]), float(row["_dec_deg"]))
        if sep > max_sep:
            continue
        instrument = normalize_scalar(first_value(row, ("exp_type", "instrument", "instrume"))).upper()
        if instruments and not any(item in instrument for item in instruments):
            continue
        match = match_row(
            transient,
            "dawn_dashboard_center",
            [row],
            instrument,
            notes="Rough match to dashboard target center; not a footprint test.",
        )
        match["separation_arcsec"] = f"{sep:.3f}"
        match["release"] = first_value(row, ("release",))
        match["dja_table"] = row.get("_dashboard_table", "")
        match["url"] = row.get("_dashboard_url", "")
        matches.append(match)
    return matches


def transient_rows(transients: list[Transient]) -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "prefix": t.prefix,
            "objid": t.objid,
            "ra": f"{t.ra:.8f}",
            "dec": f"{t.dec:.8f}",
            "type": t.transient_type,
            "redshift": t.redshift,
            "host_name": t.host_name,
            "host_redshift": t.host_redshift,
            "public_timestamp": t.public_timestamp,
        }
        for t in transients
    ]


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    instruments = {item.strip().upper() for item in args.instruments.split(",") if item.strip()}

    if args.tns_input_csv:
        transients = load_transients_from_csv(Path(args.tns_input_csv))
    elif args.tns_source == "staged-csv":
        transients = fetch_tns_staged_csv_transients(args)
    elif args.tns_source == "web-csv":
        transients = fetch_tns_web_csv_transients(args)
    else:
        transients = fetch_tns_transients(args)
    print(f"Classified transients with usable coordinates: {len(transients)}", file=sys.stderr)

    write_csv(
        output_dir / "tns_classified.csv",
        transient_rows(transients),
        ["name", "prefix", "objid", "ra", "dec", "type", "redshift", "host_name", "host_redshift", "public_timestamp"],
    )

    use_mast = args.match_source in ("mast", "both")
    use_dja = args.match_source in ("dja", "both") and not args.skip_dja_api

    dashboard_rows: list[dict[str, Any]] = []
    if use_dja and not args.skip_dashboard:
        dashboard_rows = download_dashboard_tables(args.timeout)
        print(f"DAWN dashboard rows with parsed coordinates: {len(dashboard_rows)}", file=sys.stderr)

    mast = MASTClient(args.timeout) if use_mast else None
    dja = DJAClient(args.timeout) if use_dja else None
    all_matches: list[dict[str, Any]] = []
    for index, transient in enumerate(transients, start=1):
        print(f"[{index}/{len(transients)}] JWST footprint match {transient.prefix}{transient.name}", file=sys.stderr)
        if mast is not None:
            all_matches.extend(mast_matches_for_transient(transient, mast, args, instruments))
        if dja is not None:
            all_matches.extend(dja_matches_for_transient(transient, dja, args, instruments))
        if dashboard_rows:
            all_matches.extend(dashboard_matches_for_transient(transient, dashboard_rows, args.dashboard_radius_arcmin, instruments))

    fields = [
        "match_source",
        "tns_name",
        "tns_prefix",
        "tns_ra",
        "tns_dec",
        "tns_type",
        "tns_redshift",
        "separation_arcsec",
        "instrument",
        "proposal_id",
        "target",
        "filter_or_grating",
        "observed",
        "release",
        "product_or_dataset",
        "assoc_name",
        "dja_table",
        "url",
        "notes",
        "obs_id",
        "obsid",
        "data_rights",
        "dataproduct_type",
        "calib_level",
        "proposal_pi",
        "obs_title",
    ]
    write_csv(output_dir / "jwst_matches.csv", all_matches, fields)

    summary = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "n_transients": len(transients),
        "n_matches": len(all_matches),
        "match_sources": sorted({row.get("match_source", "") for row in all_matches}),
        "outputs": {
            "tns_classified": str(output_dir / "tns_classified.csv"),
            "jwst_matches": str(output_dir / "jwst_matches.csv"),
        },
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
