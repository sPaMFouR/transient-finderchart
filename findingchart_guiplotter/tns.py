from __future__ import annotations

import csv
import io
import json
import os
import time
from typing import Any

import requests

from .models import Target


TNS_BASE_URL = "https://www.wis-tns.org/api/get"
TNS_SEARCH_URL = "https://www.wis-tns.org/search"


class TNSLookupError(RuntimeError):
    pass


def _first(row: dict[str, Any], keys: tuple[str, ...], default: Any = "") -> Any:
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


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return str(_first(value, ("name", "value", "id"), ""))
    if isinstance(value, list):
        return "; ".join(part for item in value if (part := _scalar(item)))
    return str(value).strip()


def _parse_ra(value: Any) -> float | None:
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


def _parse_dec(value: Any) -> float | None:
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
    parts = text.lstrip("+-").replace("d", ":").replace("m", ":").replace("s", "").split(":")
    if len(parts) < 3:
        parts = text.lstrip("+-").split()
    if len(parts) < 3:
        return None
    try:
        return sign * (float(parts[0]) + float(parts[1]) / 60.0 + float(parts[2]) / 3600.0)
    except ValueError:
        return None


def normalize_query_name(name: str) -> str:
    text = name.strip()
    for prefix in ("SN", "AT"):
        if text.upper().startswith(prefix + " "):
            return text.split(None, 1)[1].strip()
    return text


def target_from_row(row: dict[str, Any], fallback_name: str) -> Target | None:
    raw_name = _scalar(_first(row, ("objname", "name", "Name", "TNS Name"), fallback_name))
    prefix = _scalar(_first(row, ("prefix", "Prefix", "name_prefix"), ""))
    if raw_name.upper().startswith("SN "):
        prefix, raw_name = "SN", raw_name.split(None, 1)[1]
    elif raw_name.upper().startswith("AT "):
        prefix, raw_name = "AT", raw_name.split(None, 1)[1]
    ra = _parse_ra(_first(row, ("radeg", "ra", "RA", "ra_deg", "objra")))
    dec = _parse_dec(_first(row, ("decdeg", "dec", "DEC", "declination", "objdec")))
    if ra is None or dec is None:
        return None
    aliases = _scalar(_first(row, ("internal_names", "internal_name", "aliases"), ""))
    display = f"{prefix} {raw_name}".strip()
    return Target(
        display_name=display,
        tns_name=raw_name,
        prefix=prefix,
        objid=_scalar(_first(row, ("objid", "id", "ID"), "")),
        ra_deg=ra,
        dec_deg=dec,
        transient_type=_scalar(_first(row, ("object_type.name", "objtype.name", "type", "Type"), "")),
        redshift=_scalar(_first(row, ("redshift", "Redshift", "z"), "")),
        host_name=_scalar(_first(row, ("hostname", "Host Name", "host.name", "host"), "")),
        aliases=[part.strip() for part in aliases.replace(",", ";").split(";") if part.strip()],
    )


class TNSClient:
    def __init__(self, timeout: float = 45.0, sleep: float = 1.0) -> None:
        self.timeout = timeout
        self.sleep = sleep
        self.api_key = os.environ.get("TNS_API_KEY", "")
        self.bot_id = os.environ.get("TNS_BOT_ID", "")
        self.bot_name = os.environ.get("TNS_BOT_NAME", "")
        self.tns_type = os.environ.get("TNS_TYPE", "bot")
        self.session = requests.Session()

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key and self.bot_id and self.bot_name)

    def _marker_header(self) -> dict[str, str]:
        if not self.bot_id or not self.bot_name:
            return {}
        marker = f'tns_marker{{"tns_id": "{self.bot_id}", "type": "{self.tns_type}", "name": "{self.bot_name}"}}'
        return {"User-Agent": marker}

    def _post_api(self, endpoint: str, payload: dict[str, Any]) -> Any:
        if not self.has_credentials:
            raise TNSLookupError("TNS_API_KEY, TNS_BOT_ID, and TNS_BOT_NAME are required for API lookup.")
        response = self.session.post(
            f"{TNS_BASE_URL}/{endpoint}",
            headers=self._marker_header(),
            data={"api_key": self.api_key, "data": json.dumps(payload)},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise TNSLookupError(response.text.replace("\n", " ")[:500])
        time.sleep(self.sleep)
        return response.json()

    @staticmethod
    def _reply(payload: Any) -> Any:
        if isinstance(payload, list):
            payload = payload[0] if payload else {}
        if not isinstance(payload, dict):
            return {}
        data = payload.get("data", {})
        return data.get("reply", data) if isinstance(data, dict) else {}

    def lookup(self, name: str) -> Target:
        clean_name = normalize_query_name(name)
        if self.has_credentials:
            target = self._lookup_api(clean_name)
            if target is not None:
                return target
        target = self._lookup_public_csv(clean_name)
        if target is not None:
            return target
        raise TNSLookupError(f"No TNS target found for {name!r}.")

    def _lookup_api(self, clean_name: str) -> Target | None:
        candidates = [clean_name]
        if clean_name.lower().startswith("ztf"):
            search_payload = {"internal_name": clean_name, "num_page": 10}
        else:
            search_payload = {"objname": clean_name, "num_page": 10}
        reply = self._reply(self._post_api("search", search_payload))
        rows = reply if isinstance(reply, list) else reply.get("objects", []) if isinstance(reply, dict) else []
        for row in rows:
            name = _scalar(_first(row, ("objname", "name"), ""))
            if name and name not in candidates:
                candidates.append(name)
        for candidate in candidates:
            try:
                obj_reply = self._reply(self._post_api("object", {"objname": candidate, "photometry": "0", "spectra": "0"}))
            except TNSLookupError:
                continue
            if isinstance(obj_reply, dict):
                target = target_from_row(obj_reply, candidate)
                if target is not None:
                    return target
        for row in rows:
            target = target_from_row(row, clean_name)
            if target is not None:
                return target
        return None

    def _lookup_public_csv(self, clean_name: str) -> Target | None:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
                )
            }
        )
        params = {
            "format": "csv",
            "num_page": 50,
            "page": 0,
            "name": clean_name,
            "name_like": "1",
            "display[redshift]": "1",
            "display[hostname]": "1",
            "display[internal_name]": "1",
            "display[discoverydate]": "1",
        }
        response = session.get(TNS_SEARCH_URL, params=params, timeout=self.timeout)
        if response.status_code >= 400:
            raise TNSLookupError(response.text.replace("\n", " ")[:500])
        text = response.text.lstrip("\ufeff").strip()
        if not text or text.startswith("<"):
            return None
        for row in csv.DictReader(io.StringIO(text)):
            target = target_from_row(row, clean_name)
            if target is None:
                continue
            haystack = " ".join([target.display_name, target.tns_name, *target.aliases]).lower()
            if clean_name.lower() in haystack:
                return target
        return None
