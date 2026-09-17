"""Defensible subset of raw ONS PPI and SPPI indices, preserving official CDIDs."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any
from urllib.parse import urljoin

import httpx

from scripts.config import MAX_DOWNLOAD_BYTES, REQUEST_TIMEOUT, USER_AGENT
from scripts.snapshots import Snapshot, build_snapshot
from scripts.time_series import Observation

DATASETS = {
    "ons_ppi": (
        "https://www.ons.gov.uk/economy/inflationandpriceindices/datasets/producerpriceindexstatisticalbulletindataset/current",
        {
            "G67M",
            "G6QR",
            "G6SI",
            "G8ZA",
            "GB7R",
            "GB7S",
            "GB8U",
            "GBA6",
            "GBA7",
            "GD6Y",
            "GHIK",
            "GHIL",
            "GHIM",
            "GHIP",
            "GHHV",
        },
    ),
    "ons_sppi": (
        "https://www.ons.gov.uk/economy/inflationandpriceindices/datasets/serviceproducerpriceindices/current",
        {
            "FUY4",
            "FUY5",
            "FUY6",
            "FUY7",
            "FUY8",
            "FUY9",
            "FUZ2",
            "FUZ3",
            "FUZ4",
            "FUZ5",
            "HQTH",
            "HQTI",
        },
    ),
}


@dataclass(frozen=True)
class ExtractedData:
    observations: list[Observation]
    snapshots: list[Snapshot]
    catalog: dict[str, dict[str, Any]]
    releases: list[datetime]
    availability_by_key: dict[tuple[str, date], tuple[datetime, str, date | None]]
    min_lag_days: int = 0
    max_lag_days: int = 0
    inferred_lag_days: int | None = None


def _reference(label: str) -> date | None:
    label = label.strip()
    for fmt in ("%Y %b",):
        try:
            return datetime.strptime(label, fmt).replace(tzinfo=UTC).date().replace(day=1)
        except ValueError:
            pass
    m = re.fullmatch(r"(\d{4}) Q([1-4])", label)
    return date(int(m.group(1)), 3 * int(m.group(2)) - 2, 1) if m else None


def parse_csv(
    body: bytes, source_id: str, selected: set[str], snapshot_id: str, url: str, collected: datetime
) -> tuple[
    list[Observation],
    dict[str, dict[str, Any]],
    datetime,
    dict[tuple[str, date], tuple[datetime, str, date | None]],
]:
    rows = list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))
    if (
        len(rows) < 10
        or rows[0][0] != "Title"
        or rows[1][0] != "CDID"
        or rows[4][0] != "Release Date"
    ):
        raise ValueError(f"{source_id} CSV structure drifted")
    positions = {cdid: i for i, cdid in enumerate(rows[1]) if cdid in selected}
    if set(positions) != selected:
        raise ValueError(f"{source_id} missing CDIDs {sorted(selected - set(positions))}")
    release_dates = {
        datetime.strptime(rows[4][i], "%d-%m-%Y").replace(tzinfo=UTC).date()
        for i in positions.values()
    }
    if len(release_dates) != 1:
        raise ValueError(f"{source_id} inconsistent release dates")
    released = datetime.combine(release_dates.pop(), time(7), tzinfo=UTC)
    observations = []
    catalog = {}
    availability = {}
    keys = set()
    for cdid, col in positions.items():
        series_id = f"ONS_{source_id.split('_')[1].upper()}_{cdid}_2015"
        title = rows[0][col]
        for row in rows[7:]:
            label = row[0].strip()
            if source_id == "ons_ppi" and not re.fullmatch(r"\d{4} [A-Z]{3}", label):
                continue
            if source_id == "ons_sppi" and not re.fullmatch(r"\d{4} Q[1-4]", label):
                continue
            reference = _reference(label)
            raw = row[col].strip() if col < len(row) else ""
            if reference is None or raw in {"", "..", "-"}:
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            key = (series_id, reference)
            if key in keys:
                raise ValueError(f"Duplicate {source_id} key {key}")
            keys.add(key)
            observations.append(Observation(series_id, reference, value, snapshot_id))
        catalog[series_id] = {
            "source_id": source_id,
            "name": title,
            "description": f"Raw ONS index, official CDID {cdid}; base year retained in series_id.",
            "frequency": "monthly" if source_id == "ons_ppi" else "quarterly",
            "unit": "index",
            "eco_group": "producer_prices",
            "source_url": url,
            "last_publish_date": released.date(),
        }
    latest = {
        sid: max(o.reference_date for o in observations if o.series_id == sid) for sid in catalog
    }
    for o in observations:
        current = o.reference_date == latest[o.series_id]
        availability[(o.series_id, o.reference_date)] = (
            released if current else collected,
            "official_timestamp" if current else "first_seen",
            released.date() if current else None,
        )
    minimum = 1000 if source_id == "ons_ppi" else 300
    if len(observations) < minimum:
        raise ValueError(f"{source_id} selected history unexpectedly short")
    return observations, catalog, released, availability


def collect() -> ExtractedData:
    fetched = datetime.now(UTC)
    all_obs = []
    snaps = []
    catalog = {}
    releases = []
    availability = {}
    with httpx.Client(
        timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    ) as client:
        for source_id, (landing, selected) in DATASETS.items():
            page = client.get(landing)
            page.raise_for_status()
            links = re.findall(
                r'href=["\']([^"\']*file\?uri=[^"\']+/current/[^"\']+\.csv)["\']',
                page.text,
                re.IGNORECASE,
            )
            links = [x for x in links if "/previous/" not in x]
            if len(links) != 1:
                raise ValueError(f"Expected one current {source_id} CSV, found {len(links)}")
            url = urljoin(landing, links[0])
            response = client.get(url)
            response.raise_for_status()
            body = response.content
            if not body or len(body) > MAX_DOWNLOAD_BYTES:
                raise ValueError(f"Invalid {source_id} size {len(body)}")
            digest = hashlib.sha256(body).hexdigest()
            obs, meta, released, avail = parse_csv(body, source_id, selected, digest, url, fetched)
            all_obs += obs
            catalog.update(meta)
            availability.update(avail)
            releases.append(released)
            snaps.append(
                build_snapshot(
                    source_id,
                    url,
                    f"{source_id}.csv",
                    body,
                    digest,
                    response.headers.get("etag"),
                    response.headers.get("last-modified"),
                    fetched,
                    released.date(),
                )
            )
    return ExtractedData(all_obs, snaps, catalog, releases, availability)
