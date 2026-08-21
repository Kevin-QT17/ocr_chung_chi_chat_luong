#!/usr/bin/env python3
"""Thu thap URL va anh gallery san pham cong khai tren Hathyo.

Script chi dung Python standard library. Cac lenh duoc thiet ke de chay tu
thu muc goc du an, nhung moi duong dan deu duoc suy ra tu vi tri file script
de tranh ghi nham khi current working directory thay doi.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import html
import ipaddress
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence


USER_AGENT = "LazinetDataInternLogoCollector/1.0"
SITE_ORIGIN = "https://hathyo.com"
CATALOG_URL = f"{SITE_ORIGIN}/product"
ROBOTS_URL = f"{SITE_ORIGIN}/robots.txt"
SITEMAP_URL = f"{SITE_ORIGIN}/sitemap.xml"
EXPECTED_PRODUCT_COUNT = 306
REQUEST_TIMEOUT = 30
MAX_ATTEMPTS = 3
PAGE_DELAY = 1.0
IMAGE_DELAY = 0.3
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_HTML_BYTES = 10 * 1024 * 1024
MAX_SITEMAP_BYTES = 50 * 1024 * 1024
MAX_SITEMAPS = 64
MAX_CATALOG_PAGES = 100

PRODUCT_HEADER = (
    "ma_san_pham",
    "ten_san_pham",
    "url_san_pham",
    "so_url_anh_phat_hien",
    "so_anh_tai_thanh_cong",
    "so_anh_trung",
    "so_anh_loi",
    "trang_thai_truy_cap",
    "http_status",
    "ghi_chu",
)

IMAGE_HEADER = (
    "ma_anh",
    "ma_san_pham",
    "thu_tu_anh",
    "ten_file",
    "duong_dan_anh",
    "url_san_pham",
    "url_anh",
    "nguon_phat_hien",
    "la_anh_gallery",
    "http_status",
    "mime_type",
    "kich_thuoc_byte",
    "sha256",
    "trang_thai_tai",
    "la_anh_trung",
    "duong_dan_file_goc",
    "ghi_chu",
)

PRODUCT_STATES = {
    "chua_tai",
    "da_khao_sat",
    "da_tai",
    "da_tai_co_ngoai_le",
    "loi_truy_cap",
    "khong_co_anh",
    "can_kiem_tra",
}
IMAGE_STATES = {
    "chua_tai",
    "da_tai",
    "trung_sha256",
    "loi_http",
    "loi_dinh_dang",
    "qua_lon",
    "url_khong_hop_le",
    "khong_the_tai_cong_khai",
}
IMAGE_ERROR_STATES = {
    "loi_http",
    "loi_dinh_dang",
    "qua_lon",
    "url_khong_hop_le",
}
IMAGE_RECORDED_ERROR_STATES = IMAGE_ERROR_STATES | {"khong_the_tai_cong_khai"}
IMAGE_TERMINAL_ERROR_STATES = {
    "loi_dinh_dang",
    "qua_lon",
    "url_khong_hop_le",
}
PRODUCT_SUCCESS_STATES = {
    "da_khao_sat",
    "da_tai",
    "da_tai_co_ngoai_le",
    "khong_co_anh",
    "can_kiem_tra",
}
PUBLIC_UNAVAILABLE_STATE = "khong_the_tai_cong_khai"
PRODUCT_EXCEPTION_STATE = "da_tai_co_ngoai_le"
PUBLIC_UNAVAILABLE_NOTE = (
    "cloudfront_tra_403_sau_khi_da_thu_lai;khong_co_file_vat_ly"
)
PUBLIC_UNAVAILABLE_EMPTY_FIELDS = (
    "ten_file",
    "duong_dan_anh",
    "sha256",
    "kich_thuoc_byte",
    "duong_dan_file_goc",
)
KNOWN_PUBLIC_403_EXCEPTIONS = {
    "anh_000693": (
        "san_pham_0262",
        "https://d134sx875xrex2.cloudfront.net/"
        "ypUkidkQwV_HT%20Gold%20Nuti%20+%20(1).jpg",
    ),
    "anh_000696": (
        "san_pham_0262",
        "https://d134sx875xrex2.cloudfront.net/PLNPsCO22x_HT%20Nuti+.jpg",
    ),
}
IMAGE_MIME = {
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tif": "image/tiff",
}


class CollectorError(RuntimeError):
    """Loi da duoc du kien va co the bao gon cho nguoi dung."""


class DataIntegrityError(CollectorError):
    """CSV hoac file anh hien co khong nhat quan."""


class SafetyGateError(CollectorError):
    """Dieu kien an toan de tai toan bo chua dat."""


class HttpFetchError(CollectorError):
    def __init__(
        self,
        url: str,
        message: str,
        *,
        status: int | None = None,
        attempts: int = 0,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.status = status
        self.attempts = attempts


class DownloadTooLarge(CollectorError):
    def __init__(self, status: int | None, size: int | None) -> None:
        super().__init__("Anh vuot qua gioi han 10 MiB")
        self.status = status
        self.size = size


class InvalidImageFormat(CollectorError):
    def __init__(
        self,
        status: int,
        size: int,
        header_mime: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.size = size
        self.header_mime = header_mime


@dataclass(frozen=True)
class Layout:
    script: Path
    root: Path
    data_root: Path
    image_root: Path
    table_root: Path
    label_root: Path
    scripts_root: Path
    product_csv: Path
    image_csv: Path

    @classmethod
    def from_script(cls) -> "Layout":
        script = Path(__file__).resolve()
        root = script.parent.parent
        data_root = root / "data" / "du_lieu_logo"
        return cls(
            script=script,
            root=root,
            data_root=data_root,
            image_root=data_root / "anh_goc",
            table_root=data_root / "bang_du_lieu",
            label_root=data_root / "nhan",
            scripts_root=root / "scripts",
            product_csv=data_root / "bang_du_lieu" / "san_pham.csv",
            image_csv=data_root / "bang_du_lieu" / "anh.csv",
        )

    def required_directories(self) -> tuple[Path, ...]:
        return (
            self.root,
            self.data_root,
            self.image_root,
            self.table_root,
            self.label_root,
            self.scripts_root,
        )


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    headers: Mapping[str, str]
    data: bytes


@dataclass
class RobotsPolicy:
    parser: urllib.robotparser.RobotFileParser
    status: int
    allowed: bool
    missing: bool = False
    crawl_delay: float | None = None

    def can_fetch(self, url: str) -> bool:
        return self.missing or self.parser.can_fetch(USER_AGENT, url)


@dataclass
class DiscoveryResult:
    urls: set[str] = field(default_factory=set)
    sources: dict[str, set[str]] = field(default_factory=dict)
    sitemap_attempted: bool = False
    sitemap_used: bool = False
    catalog_pages: int = 0
    warnings: list[str] = field(default_factory=list)

    def add(self, url: str, source: str) -> None:
        self.urls.add(url)
        self.sources.setdefault(url, set()).add(source)


@dataclass
class ImageCandidate:
    url: str
    sources: set[str] = field(default_factory=set)
    signals: set[str] = field(default_factory=set)
    order: int = 0


@dataclass
class ParsedProduct:
    name: str
    candidates: list[ImageCandidate]


@dataclass
class DownloadedImage:
    temp_path: Path | None
    final_url: str
    http_status: int
    header_mime: str
    size: int
    sha256: str
    extension: str
    actual_mime: str


@dataclass
class VerificationResult:
    ok: bool
    stats: dict[str, int]
    problems: list[str]


def print_kv(label: str, value: object) -> None:
    print(f"{label}: {value}")


def clean_note(value: object, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:limit]


def append_note(existing: str, note: str) -> str:
    note = clean_note(note)
    if not note:
        return existing
    parts = [part.strip() for part in existing.split(";") if part.strip()]
    if note not in parts:
        parts.append(note)
    return "; ".join(parts)[:1000]


def parse_nonnegative_int(value: str, field_name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise DataIntegrityError(f"{field_name} khong phai so nguyen: {value!r}") from exc
    if number < 0:
        raise DataIntegrityError(f"{field_name} phai >= 0: {value!r}")
    return number


def numeric_suffix(value: str) -> int:
    match = re.search(r"(\d+)$", value)
    return int(match.group(1)) if match else -1


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def is_hathyo_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    hostname = hostname.rstrip(".").casefold()
    return hostname == "hathyo.com" or hostname.endswith(".hathyo.com")


def normalize_url(raw: str, base_url: str | None = None) -> str | None:
    raw = html.unescape(raw or "").strip()
    if not raw or raw.casefold().startswith("data:"):
        return None
    absolute = urllib.parse.urljoin(base_url, raw) if base_url else raw
    try:
        parts = urllib.parse.urlsplit(absolute)
        if parts.scheme.casefold() not in {"http", "https"}:
            return None
        if not parts.hostname or parts.username is not None or parts.password is not None:
            return None
        if any(ord(character) < 32 for character in absolute):
            return None
        hostname = parts.hostname.rstrip(".").casefold().encode("idna").decode("ascii")
        port = parts.port
    except (UnicodeError, ValueError):
        return None
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    default_port = (parts.scheme.casefold() == "http" and port == 80) or (
        parts.scheme.casefold() == "https" and port == 443
    )
    netloc = hostname if port is None or default_port else f"{hostname}:{port}"
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    return urllib.parse.urlunsplit(
        (parts.scheme.casefold(), netloc, path, parts.query, "")
    )


def is_public_image_url(url: str) -> bool:
    try:
        parts = urllib.parse.urlsplit(url)
        hostname = parts.hostname
    except ValueError:
        return False
    if not hostname:
        return False
    lowered = hostname.rstrip(".").casefold()
    if lowered in {"localhost", "localhost.localdomain"} or lowered.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def is_product_url(url: str) -> bool:
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    if not is_hathyo_host(parts.hostname):
        return False
    path = urllib.parse.unquote(parts.path).rstrip("/").casefold()
    if re.fullmatch(r"/product/[^/]+", path):
        return True
    if path == "/product" and parts.query:
        query = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
        return any(key.casefold() in {"id", "product_id", "slug"} for key in query)
    return False


def decode_body(data: bytes, headers: Mapping[str, str]) -> str:
    content_type = headers.get("Content-Type", "")
    match = re.search(r"charset\s*=\s*[\"']?([^;\"'\s]+)", content_type, re.I)
    charsets = [match.group(1)] if match else []
    charsets.extend(["utf-8", "windows-1258"])
    for charset in charsets:
        try:
            return data.decode(charset)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


def optional_content_length(value: str | None) -> int | None:
    if not value:
        return None
    try:
        number = int(value)
    except ValueError:
        return None
    return number if number >= 0 else None


class RateLimiter:
    def __init__(self) -> None:
        self.delays = {"page": PAGE_DELAY, "image": IMAGE_DELAY}
        self.last_started = {"page": 0.0, "image": 0.0}

    def set_page_delay(self, seconds: float) -> None:
        self.delays["page"] = max(PAGE_DELAY, seconds)

    def wait(self, kind: str) -> None:
        delay = self.delays[kind]
        elapsed = time.monotonic() - self.last_started[kind]
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self.last_started[kind] = time.monotonic()


class HttpClient:
    def __init__(self) -> None:
        self.limiter = RateLimiter()

    @staticmethod
    def _request(
        url: str,
        *,
        accept: str,
        referer: str | None = None,
    ) -> urllib.request.Request:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Encoding": "identity",
        }
        if referer:
            headers["Referer"] = referer
        return urllib.request.Request(url, headers=headers, method="GET")

    @staticmethod
    def _retryable_status(status: int | None) -> bool:
        return status in {408, 425, 429, 500, 502, 503, 504}

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None = None) -> float:
        if retry_after:
            try:
                return min(30.0, max(0.0, float(retry_after)))
            except ValueError:
                pass
        return float(2 ** (attempt - 1))

    def fetch_bytes(
        self,
        url: str,
        *,
        kind: str = "page",
        accept: str = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.1",
        max_bytes: int = MAX_HTML_BYTES,
    ) -> FetchResult:
        last_error: BaseException | None = None
        last_status: int | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self.limiter.wait(kind)
            try:
                request = self._request(url, accept=accept)
                with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                    status = int(response.getcode() or 200)
                    declared = optional_content_length(
                        response.headers.get("Content-Length")
                    )
                    if declared is not None and declared > max_bytes:
                        raise HttpFetchError(
                            url,
                            f"Phan hoi vuot gioi han {max_bytes} byte",
                            status=status,
                            attempts=attempt,
                        )
                    data = response.read(max_bytes + 1)
                    if len(data) > max_bytes:
                        raise HttpFetchError(
                            url,
                            f"Phan hoi vuot gioi han {max_bytes} byte",
                            status=status,
                            attempts=attempt,
                        )
                    return FetchResult(
                        url=url,
                        final_url=response.geturl(),
                        status=status,
                        headers=response.headers,
                        data=data,
                    )
            except urllib.error.HTTPError as exc:
                last_error = exc
                last_status = exc.code
                if not self._retryable_status(exc.code) or attempt == MAX_ATTEMPTS:
                    break
                time.sleep(self._backoff(attempt, exc.headers.get("Retry-After")))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt == MAX_ATTEMPTS:
                    break
                time.sleep(self._backoff(attempt))
            except HttpFetchError:
                raise
        raise HttpFetchError(
            url,
            clean_note(last_error or "Loi HTTP khong xac dinh"),
            status=last_status,
            attempts=MAX_ATTEMPTS,
        )

    def download_image(self, url: str, referer: str) -> DownloadedImage:
        last_error: BaseException | None = None
        last_status: int | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            temp_path: Path | None = None
            self.limiter.wait("image")
            try:
                request = self._request(
                    url,
                    accept="image/avif,image/webp,image/apng,image/*,*/*;q=0.1",
                    referer=referer,
                )
                with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                    status = int(response.getcode() or 200)
                    last_status = status
                    declared = optional_content_length(
                        response.headers.get("Content-Length")
                    )
                    if declared is not None and declared > MAX_IMAGE_BYTES:
                        raise DownloadTooLarge(status, declared)
                    descriptor, temp_name = tempfile.mkstemp(
                        prefix="hathyo_anh_", suffix=".download"
                    )
                    os.close(descriptor)
                    temp_path = Path(temp_name)
                    digest = hashlib.sha256()
                    total = 0
                    prefix = bytearray()
                    with temp_path.open("wb") as output:
                        while True:
                            chunk = response.read(64 * 1024)
                            if not chunk:
                                break
                            total += len(chunk)
                            if total > MAX_IMAGE_BYTES:
                                raise DownloadTooLarge(status, total)
                            if len(prefix) < 16:
                                prefix.extend(chunk[: 16 - len(prefix)])
                            digest.update(chunk)
                            output.write(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    header_mime = response.headers.get("Content-Type", "").split(";", 1)[0]
                    header_mime = header_mime.strip().casefold()
                    extension = detect_image_format(bytes(prefix))
                    if extension is None:
                        raise InvalidImageFormat(
                            status,
                            total,
                            header_mime,
                            "Noi dung khong co magic bytes cua dinh dang anh duoc ho tro",
                        )
                    final_url = normalize_url(response.geturl())
                    if not final_url or not is_public_image_url(final_url):
                        raise DataIntegrityError("URL dich sau redirect khong hop le/cong khai")
                    payload = DownloadedImage(
                        temp_path=temp_path,
                        final_url=final_url,
                        http_status=status,
                        header_mime=header_mime,
                        size=total,
                        sha256=digest.hexdigest(),
                        extension=extension,
                        actual_mime=IMAGE_MIME[extension],
                    )
                    temp_path = None
                    return payload
            except DownloadTooLarge:
                raise
            except urllib.error.HTTPError as exc:
                last_error = exc
                last_status = exc.code
                if not self._retryable_status(exc.code) or attempt == MAX_ATTEMPTS:
                    break
                time.sleep(self._backoff(attempt, exc.headers.get("Retry-After")))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt == MAX_ATTEMPTS:
                    break
                time.sleep(self._backoff(attempt))
            finally:
                if temp_path is not None:
                    try:
                        temp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
        raise HttpFetchError(
            url,
            clean_note(last_error or "Khong tai duoc anh"),
            status=last_status,
            attempts=MAX_ATTEMPTS,
        )


def read_csv_rows(path: Path, header: Sequence[str]) -> list[dict[str, str]]:
    if not path.exists():
        return []
    if not path.is_file():
        raise DataIntegrityError(f"Duong dan CSV khong phai file: {path}")
    with path.open("rb") as raw:
        if raw.read(3) != b"\xef\xbb\xbf":
            raise DataIntegrityError(f"CSV khong co BOM UTF-8-SIG: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != tuple(header):
            raise DataIntegrityError(f"Header CSV khong dung quy dinh: {path}")
        rows: list[dict[str, str]] = []
        for line_number, row in enumerate(reader, start=2):
            if None in row:
                raise DataIntegrityError(f"CSV co cot du tai dong {line_number}: {path}")
            if any(row.get(column) is None for column in header):
                raise DataIntegrityError(
                    f"CSV thieu cot tai dong {line_number}: {path}"
                )
            rows.append({column: row.get(column, "") for column in header})
        return rows


def atomic_write_csv(
    path: Path,
    header: Sequence[str],
    rows: Iterable[Mapping[str, object]],
) -> None:
    if not path.parent.is_dir():
        raise CollectorError(f"Thu muc CSV khong ton tai: {path.parent}")
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            newline="",
            dir=path.parent,
            prefix=f"{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            writer = csv.DictWriter(
                stream,
                fieldnames=list(header),
                extrasaction="ignore",
                lineterminator="\n",
            )
            writer.writeheader()
            for row in rows:
                writer.writerow({column: row.get(column, "") for column in header})
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def validate_product_rows(rows: Sequence[Mapping[str, str]]) -> None:
    ids: set[str] = set()
    urls: set[str] = set()
    for row in rows:
        product_id = row["ma_san_pham"]
        if not re.fullmatch(r"san_pham_\d{4,}", product_id):
            raise DataIntegrityError(f"ma_san_pham khong hop le: {product_id!r}")
        if product_id in ids:
            raise DataIntegrityError(f"Trung ma_san_pham: {product_id}")
        ids.add(product_id)
        url = normalize_url(row["url_san_pham"])
        if not url or not is_product_url(url):
            raise DataIntegrityError(f"url_san_pham khong hop le: {row['url_san_pham']!r}")
        if url in urls:
            raise DataIntegrityError(f"Trung url_san_pham: {url}")
        urls.add(url)
        if row["trang_thai_truy_cap"] not in PRODUCT_STATES:
            raise DataIntegrityError(
                f"trang_thai_truy_cap khong hop le: {row['trang_thai_truy_cap']}"
            )
        for field_name in (
            "so_url_anh_phat_hien",
            "so_anh_tai_thanh_cong",
            "so_anh_trung",
            "so_anh_loi",
        ):
            parse_nonnegative_int(row[field_name], field_name)


def validate_image_rows(
    rows: Sequence[Mapping[str, str]],
    valid_product_ids: set[str],
) -> None:
    ids: set[str] = set()
    keys: set[tuple[str, str]] = set()
    product_orders: set[tuple[str, int]] = set()
    for row in rows:
        image_id = row["ma_anh"]
        if not re.fullmatch(r"anh_\d{6,}", image_id):
            raise DataIntegrityError(f"ma_anh khong hop le: {image_id!r}")
        if image_id in ids:
            raise DataIntegrityError(f"Trung ma_anh: {image_id}")
        ids.add(image_id)
        product_id = row["ma_san_pham"]
        if product_id not in valid_product_ids:
            raise DataIntegrityError(f"Anh tham chieu san pham khong ton tai: {image_id}")
        order = parse_nonnegative_int(row["thu_tu_anh"], "thu_tu_anh")
        if order < 1:
            raise DataIntegrityError(f"thu_tu_anh phai >= 1: {image_id}")
        order_key = (product_id, order)
        if order_key in product_orders:
            raise DataIntegrityError(f"Trung thu_tu_anh: {order_key}")
        product_orders.add(order_key)
        state = row["trang_thai_tai"]
        if state not in IMAGE_STATES:
            raise DataIntegrityError(f"Trang thai anh khong hop le: {image_id}")
        url = normalize_url(row["url_anh"])
        if not url and state != "url_khong_hop_le":
            raise DataIntegrityError(f"url_anh khong hop le: {image_id}")
        key = (product_id, url or row["url_anh"].strip())
        if key in keys:
            raise DataIntegrityError(f"Trung dong anh theo san pham+URL: {key}")
        keys.add(key)
        if row["la_anh_gallery"] not in {"0", "1"}:
            raise DataIntegrityError(f"la_anh_gallery khong phai 0/1: {image_id}")
        if row["la_anh_trung"] not in {"0", "1"}:
            raise DataIntegrityError(f"la_anh_trung khong phai 0/1: {image_id}")
        if row["kich_thuoc_byte"]:
            parse_nonnegative_int(row["kich_thuoc_byte"], "kich_thuoc_byte")
        if row["sha256"] and not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
            raise DataIntegrityError(f"SHA-256 khong hop le: {image_id}")


def load_tables(layout: Layout) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    product_exists = layout.product_csv.exists()
    image_exists = layout.image_csv.exists()
    if image_exists and not product_exists:
        raise DataIntegrityError("Chi mot trong hai CSV ton tai; dung de tranh mat du lieu")
    products = read_csv_rows(layout.product_csv, PRODUCT_HEADER)
    # Co the xay ra neu dung dung sau khi san_pham.csv moi duoc replace lan dau.
    # Tao lai anh.csv rong trong --khao-sat la an toan vi chua co download nao.
    images = read_csv_rows(layout.image_csv, IMAGE_HEADER) if image_exists else []
    validate_product_rows(products)
    validate_image_rows(images, {row["ma_san_pham"] for row in products})
    return products, images


def check_layout(layout: Layout, require_csv: bool = False) -> None:
    missing = [str(path) for path in layout.required_directories() if not path.is_dir()]
    if missing:
        raise CollectorError("Thieu thu muc bat buoc: " + ", ".join(missing))
    if require_csv and (not layout.product_csv.is_file() or not layout.image_csv.is_file()):
        raise CollectorError("Chua co san_pham.csv va anh.csv; hay chay --khao-sat truoc")


def check_robots(client: HttpClient) -> RobotsPolicy:
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(ROBOTS_URL)
    try:
        result = client.fetch_bytes(
            ROBOTS_URL,
            kind="page",
            accept="text/plain,*/*;q=0.1",
            max_bytes=1024 * 1024,
        )
    except HttpFetchError as exc:
        if exc.status in {404, 410}:
            return RobotsPolicy(parser=parser, status=exc.status, allowed=True, missing=True)
        if exc.status in {401, 403}:
            return RobotsPolicy(parser=parser, status=exc.status, allowed=False)
        raise CollectorError(f"Khong xac minh duoc robots.txt: {exc}") from exc
    parser.parse(decode_body(result.data, result.headers).splitlines())
    allowed = parser.can_fetch(USER_AGENT, CATALOG_URL)
    delay = parser.crawl_delay(USER_AGENT)
    if delay is None:
        delay = parser.crawl_delay("*")
    numeric_delay = float(delay) if isinstance(delay, (int, float)) else None
    if numeric_delay is not None:
        client.limiter.set_page_delay(numeric_delay)
    return RobotsPolicy(
        parser=parser,
        status=result.status,
        allowed=allowed,
        crawl_delay=numeric_delay,
    )


class CatalogLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.base_href: str | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attr = {key.casefold(): value or "" for key, value in attrs}
        tag = tag.casefold()
        if tag == "base" and attr.get("href") and self.base_href is None:
            self.base_href = attr["href"]
        if tag == "a" and attr.get("href"):
            evidence = " ".join(
                (attr.get("rel", ""), attr.get("class", ""), attr.get("id", ""))
            ).casefold()
            self.links.append((attr["href"], evidence))


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def sitemap_payload(result: FetchResult) -> bytes:
    encoding = result.headers.get("Content-Encoding", "").casefold()
    if result.final_url.casefold().endswith(".gz") or "gzip" in encoding:
        try:
            payload = gzip.decompress(result.data)
        except OSError as exc:
            raise CollectorError(f"Sitemap gzip khong hop le: {result.final_url}") from exc
        if len(payload) > MAX_SITEMAP_BYTES:
            raise CollectorError(f"Sitemap giai nen vuot gioi han: {result.final_url}")
        return payload
    return result.data


def discover_sitemap(client: HttpClient, aggregate: DiscoveryResult) -> None:
    aggregate.sitemap_attempted = True
    queue = [SITEMAP_URL]
    visited: set[str] = set()
    while queue and len(visited) < MAX_SITEMAPS:
        sitemap_url = queue.pop(0)
        normalized_sitemap = normalize_url(sitemap_url)
        if (
            not normalized_sitemap
            or normalized_sitemap in visited
            or not is_hathyo_host(urllib.parse.urlsplit(normalized_sitemap).hostname)
        ):
            continue
        visited.add(normalized_sitemap)
        try:
            result = client.fetch_bytes(
                normalized_sitemap,
                kind="page",
                accept="application/xml,text/xml,*/*;q=0.1",
                max_bytes=MAX_SITEMAP_BYTES,
            )
            root = ET.fromstring(sitemap_payload(result))
        except (HttpFetchError, CollectorError, ET.ParseError) as exc:
            aggregate.warnings.append(
                f"Khong doc duoc sitemap {normalized_sitemap}: {clean_note(exc)}"
            )
            continue
        root_kind = local_name(root.tag)
        if root_kind == "sitemapindex":
            for child in root:
                if local_name(child.tag) != "sitemap":
                    continue
                loc = next(
                    (
                        element.text
                        for element in child
                        if local_name(element.tag) == "loc" and element.text
                    ),
                    None,
                )
                child_url = normalize_url(loc or "", result.final_url)
                if child_url and child_url not in visited:
                    queue.append(child_url)
        elif root_kind == "urlset":
            for child in root:
                if local_name(child.tag) != "url":
                    continue
                loc = next(
                    (
                        element.text
                        for element in child
                        if local_name(element.tag) == "loc" and element.text
                    ),
                    None,
                )
                product_url = normalize_url(loc or "", result.final_url)
                if product_url and is_product_url(product_url):
                    aggregate.add(product_url, "sitemap")
                    aggregate.sitemap_used = True
        else:
            aggregate.warnings.append(
                f"Root sitemap khong phai urlset/sitemapindex: {normalized_sitemap}"
            )
    if queue:
        aggregate.warnings.append(f"Da dung o gioi han {MAX_SITEMAPS} sitemap")


def is_pagination_link(url: str, evidence: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    path = parts.path.rstrip("/").casefold()
    if not is_hathyo_host(parts.hostname) or is_product_url(url):
        return False
    if path != "/product":
        return False
    query_keys = {
        key.casefold()
        for key in urllib.parse.parse_qs(parts.query, keep_blank_values=True)
    }
    return bool(
        {"page", "paged", "p"} & query_keys
        or re.search(r"\b(next|pagination|load[-_ ]?more)\b", evidence)
    )


def discover_catalog(client: HttpClient, aggregate: DiscoveryResult) -> None:
    queue = [CATALOG_URL]
    visited: set[str] = set()
    while queue and len(visited) < MAX_CATALOG_PAGES:
        page_url = queue.pop(0)
        normalized_page = normalize_url(page_url)
        if not normalized_page or normalized_page in visited:
            continue
        visited.add(normalized_page)
        try:
            result = client.fetch_bytes(normalized_page, kind="page")
        except HttpFetchError as exc:
            aggregate.warnings.append(
                f"Khong doc duoc trang danh muc {normalized_page}: {clean_note(exc)}"
            )
            continue
        aggregate.catalog_pages += 1
        parser = CatalogLinkParser()
        parser.feed(decode_body(result.data, result.headers))
        base_url = normalize_url(parser.base_href or "", result.final_url) or result.final_url
        for href, evidence in parser.links:
            linked = normalize_url(href, base_url)
            if not linked:
                continue
            if is_product_url(linked):
                aggregate.add(linked, "catalog")
            elif is_pagination_link(linked, evidence) and linked not in visited:
                queue.append(linked)
    if queue:
        aggregate.warnings.append(
            f"Da dung o gioi han {MAX_CATALOG_PAGES} trang danh muc"
        )


POSITIVE_TERMS = (
    "product",
    "gallery",
    "image",
    "photo",
    "carousel",
    "slider",
    "swiper",
    "thumbnail",
)
NEGATIVE_TERMS = (
    "favicon",
    "avatar",
    "placeholder",
    "loading",
    "spinner",
    "social",
    "facebook",
    "instagram",
    "youtube",
    "site-logo",
    "brand-logo",
)
NEGATIVE_CONTAINERS = ("header", "footer", "navbar", "navigation", "menu", "advert")
JSON_IMAGE_KEYS = {
    "image",
    "images",
    "imageurl",
    "image_url",
    "contenturl",
    "thumbnailurl",
    "thumbnail",
}


def parse_srcset(value: str) -> list[str]:
    results: list[str] = []
    for part in value.split(","):
        candidate = part.strip().split()
        if candidate:
            results.append(candidate[0])
    return results


def json_image_urls(value: object, source: str = "json") -> Iterator[tuple[str, str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = re.sub(r"[^a-z0-9_]", "", str(key).casefold())
            if normalized_key in JSON_IMAGE_KEYS:
                yield from image_value_urls(child, f"{source}:{key}")
            elif isinstance(child, (dict, list)):
                yield from json_image_urls(child, source)
    elif isinstance(value, list):
        for child in value:
            yield from json_image_urls(child, source)


def image_value_urls(value: object, source: str) -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield value, source
    elif isinstance(value, list):
        for item in value:
            yield from image_value_urls(item, source)
    elif isinstance(value, dict):
        emitted = False
        for key in ("url", "contentUrl", "thumbnailUrl", "@id"):
            child = value.get(key)
            if isinstance(child, str):
                emitted = True
                yield child, f"{source}:{key}"
        if not emitted:
            yield from json_image_urls(value, source)


class ProductHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, str]] = []
        self.raw_candidates: list[tuple[str, str, set[str], str]] = []
        self.base_href: str | None = None
        self.h1_values: list[str] = []
        self.title_values: list[str] = []
        self.og_title: str = ""
        self._h1_buffer: list[str] | None = None
        self._title_buffer: list[str] | None = None
        self._script_type: str | None = None
        self._script_buffer: list[str] = []
        self.json_blocks: list[tuple[str, str]] = []

    def _context(self, attrs: Mapping[str, str]) -> str:
        current = " ".join(
            (attrs.get("class", ""), attrs.get("id", ""), attrs.get("role", ""))
        ).casefold()
        ancestors = " ".join(
            f"{tag} {context}" for tag, context in self.stack[-8:]
        )
        return f"{ancestors} {current}".strip()

    def _add_candidate(
        self,
        raw_url: str,
        source: str,
        context: str,
        descriptive_text: str = "",
    ) -> None:
        signals = {
            term
            for term in POSITIVE_TERMS
            if term in context or term in descriptive_text.casefold()
        }
        self.raw_candidates.append((raw_url, source, signals, f"{context} {descriptive_text}"))

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        tag = tag.casefold()
        attr = {key.casefold(): value or "" for key, value in attrs}
        context = self._context(attr)
        if self._h1_buffer is not None and tag != "h1":
            pass
        if tag == "h1" and self._h1_buffer is None:
            self._h1_buffer = []
        if tag == "title" and self._title_buffer is None:
            self._title_buffer = []
        if tag == "base" and attr.get("href") and self.base_href is None:
            self.base_href = attr["href"]
        if tag == "img":
            description = " ".join((attr.get("alt", ""), attr.get("title", "")))
            for name in ("src", "data-src", "data-lazy-src", "data-original"):
                if attr.get(name):
                    self._add_candidate(
                        attr[name], f"img:{name}", context, description
                    )
            if attr.get("srcset"):
                for raw in parse_srcset(attr["srcset"]):
                    self._add_candidate(raw, "img:srcset", context, description)
        elif tag == "source" and attr.get("srcset"):
            for raw in parse_srcset(attr["srcset"]):
                self._add_candidate(raw, "source:srcset", context)
        elif tag == "meta":
            property_name = (attr.get("property") or attr.get("name") or "").casefold()
            content = attr.get("content", "")
            if property_name == "og:title" and content and not self.og_title:
                self.og_title = content
            if property_name.startswith("og:image") and content:
                self._add_candidate(content, f"meta:{property_name}", "gallery og:image")
        elif tag == "script":
            script_type = attr.get("type", "").split(";", 1)[0].strip().casefold()
            if script_type in {"application/json", "application/ld+json"}:
                self._script_type = script_type
                self._script_buffer = []
        void_tags = {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }
        if tag not in void_tags:
            own_context = " ".join(
                (attr.get("class", ""), attr.get("id", ""), attr.get("role", ""))
            ).casefold()
            self.stack.append((tag, own_context))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "h1" and self._h1_buffer is not None:
            value = normalize_space(" ".join(self._h1_buffer))
            if value:
                self.h1_values.append(value)
            self._h1_buffer = None
        if tag == "title" and self._title_buffer is not None:
            value = normalize_space(" ".join(self._title_buffer))
            if value:
                self.title_values.append(value)
            self._title_buffer = None
        if tag == "script" and self._script_type:
            self.json_blocks.append((self._script_type, "".join(self._script_buffer)))
            self._script_type = None
            self._script_buffer = []
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if self._h1_buffer is not None:
            self._h1_buffer.append(data)
        if self._title_buffer is not None:
            self._title_buffer.append(data)
        if self._script_type:
            self._script_buffer.append(data)


def obvious_non_product_image(raw_url: str, context: str) -> bool:
    decoded_url = html.unescape(raw_url).casefold()
    lowered_context = html.unescape(context).casefold()
    lowered = f"{decoded_url} {lowered_context}"
    if any(term in lowered for term in NEGATIVE_TERMS):
        return True
    if any(term in lowered for term in NEGATIVE_CONTAINERS) and not any(
        term in lowered for term in ("product", "gallery", "carousel", "swiper")
    ):
        return True
    if "hathyo" in lowered_context and "logo" in lowered_context:
        return True
    try:
        basename = Path(urllib.parse.urlsplit(decoded_url).path).name
    except ValueError:
        basename = ""
    return bool(re.search(r"(?:hathyo[-_ ]*logo|logo[-_ ]*hathyo)", basename))


def parse_product_html(
    document: str,
    product_url: str,
    final_url: str,
) -> ParsedProduct:
    parser = ProductHTMLParser()
    parser.feed(document)
    base_url = normalize_url(parser.base_href or "", final_url) or final_url
    raw_items = list(parser.raw_candidates)
    for script_type, block in parser.json_blocks:
        try:
            value = json.loads(block)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        source = "json_ld" if script_type == "application/ld+json" else "json"
        for raw_url, provenance in json_image_urls(value, source):
            raw_items.append((raw_url, provenance, {"json", "image"}, "json image"))
    merged: dict[str, ImageCandidate] = {}
    for position, (raw_url, source, signals, context) in enumerate(raw_items, start=1):
        if obvious_non_product_image(raw_url, context):
            continue
        if not signals:
            # Anh trung tinh ngoai vung product/gallery khong du tin cay de tai.
            continue
        normalized = normalize_url(raw_url, base_url)
        if not normalized or not is_public_image_url(normalized):
            continue
        candidate = merged.get(normalized)
        if candidate is None:
            candidate = ImageCandidate(url=normalized, order=position)
            merged[normalized] = candidate
        candidate.sources.add(source)
        candidate.signals.update(signals or {"neutral"})
    candidates = sorted(merged.values(), key=lambda item: (item.order, item.url))
    fallback_slug = urllib.parse.unquote(
        urllib.parse.urlsplit(product_url).path.rstrip("/").rsplit("/", 1)[-1]
    )
    name = next(
        (
            normalize_space(value)
            for value in (
                parser.h1_values[0] if parser.h1_values else "",
                parser.og_title,
                parser.title_values[0] if parser.title_values else "",
                fallback_slug,
            )
            if normalize_space(value)
        ),
        fallback_slug,
    )
    return ParsedProduct(name=name, candidates=candidates)


def new_product_row(product_id: str, url: str, sources: set[str]) -> dict[str, str]:
    return {
        "ma_san_pham": product_id,
        "ten_san_pham": "",
        "url_san_pham": url,
        "so_url_anh_phat_hien": "0",
        "so_anh_tai_thanh_cong": "0",
        "so_anh_trung": "0",
        "so_anh_loi": "0",
        "trang_thai_truy_cap": "chua_tai",
        "http_status": "",
        "ghi_chu": f"nguon_phat_hien={'|'.join(sorted(sources))}",
    }


def new_image_row(
    image_id: str,
    product: Mapping[str, str],
    order: int,
    candidate: ImageCandidate,
) -> dict[str, str]:
    return {
        "ma_anh": image_id,
        "ma_san_pham": product["ma_san_pham"],
        "thu_tu_anh": str(order),
        "ten_file": "",
        "duong_dan_anh": "",
        "url_san_pham": product["url_san_pham"],
        "url_anh": candidate.url,
        "nguon_phat_hien": "|".join(sorted(candidate.sources)),
        "la_anh_gallery": "1",
        "http_status": "",
        "mime_type": "",
        "kich_thuoc_byte": "",
        "sha256": "",
        "trang_thai_tai": "chua_tai",
        "la_anh_trung": "0",
        "duong_dan_file_goc": "",
        "ghi_chu": "dau_hieu_gallery=" + "|".join(sorted(candidate.signals)),
    }


def sort_products(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(rows, key=lambda row: numeric_suffix(row["ma_san_pham"]))


def sort_images(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(rows, key=lambda row: numeric_suffix(row["ma_anh"]))


def recompute_product_counters(
    product: dict[str, str],
    images: Sequence[Mapping[str, str]],
    *,
    after_download: bool = False,
) -> None:
    own = [
        row
        for row in images
        if row["ma_san_pham"] == product["ma_san_pham"]
        and row["la_anh_gallery"] == "1"
    ]
    product["so_url_anh_phat_hien"] = str(len(own))
    product["so_anh_tai_thanh_cong"] = str(
        sum(row["trang_thai_tai"] == "da_tai" for row in own)
    )
    product["so_anh_trung"] = str(
        sum(row["trang_thai_tai"] == "trung_sha256" for row in own)
    )
    error_count = sum(
        row["trang_thai_tai"] in IMAGE_RECORDED_ERROR_STATES for row in own
    )
    product["so_anh_loi"] = str(error_count)
    if not own:
        product["trang_thai_truy_cap"] = "khong_co_anh"
    elif after_download:
        blocking = any(
            row["trang_thai_tai"] in {"chua_tai", "loi_http"} for row in own
        )
        has_exception = any(
            row["trang_thai_tai"]
            in IMAGE_TERMINAL_ERROR_STATES | {PUBLIC_UNAVAILABLE_STATE}
            for row in own
        )
        if blocking:
            product["trang_thai_truy_cap"] = "can_kiem_tra"
        elif has_exception:
            product["trang_thai_truy_cap"] = PRODUCT_EXCEPTION_STATE
        else:
            product["trang_thai_truy_cap"] = "da_tai"


def run_environment_check(layout: Layout) -> int:
    missing: list[str] = []
    for path in layout.required_directories():
        exists = path.is_dir()
        print_kv(f"thu_muc[{path}]", exists)
        if not exists:
            missing.append(str(path))
    if missing:
        raise CollectorError("Thieu thu muc bat buoc; khong thuc hien kiem tra mang")
    for path in (layout.table_root, layout.image_root):
        writable = os.access(path, os.W_OK)
        print_kv(f"quyen_ghi[{path}]", writable)
        if not writable:
            raise CollectorError(f"Khong co quyen ghi (kiem tra os.access): {path}")
    print_kv("python", sys.version.split()[0])
    print_kv("duong_dan_du_an", layout.root)
    client = HttpClient()
    robots = check_robots(client)
    print_kv("robots_http_status", robots.status)
    print_kv("robots_cho_phep_product", robots.allowed)
    if not robots.allowed:
        raise CollectorError("robots.txt khong cho phep truy cap /product")
    catalog = client.fetch_bytes(CATALOG_URL, kind="page")
    print_kv("hathyo_http_status", catalog.status)
    print_kv("kiem_tra_tao_file_du_lieu", False)
    return 0


def run_survey(layout: Layout) -> int:
    check_layout(layout)
    client = HttpClient()
    robots = check_robots(client)
    print_kv("robots_cho_phep_product", robots.allowed)
    if not robots.allowed:
        raise CollectorError("robots.txt khong cho phep truy cap trang san pham")
    products, images = load_tables(layout)
    discovery = DiscoveryResult()
    discover_sitemap(client, discovery)
    discover_catalog(client, discovery)
    products_by_url = {
        normalize_url(row["url_san_pham"]) or row["url_san_pham"]: row
        for row in products
    }
    next_product_number = max(
        (numeric_suffix(row["ma_san_pham"]) for row in products), default=0
    )
    for url in sorted(discovery.urls):
        if url not in products_by_url:
            next_product_number += 1
            product = new_product_row(
                f"san_pham_{next_product_number:04d}",
                url,
                discovery.sources.get(url, set()),
            )
            products.append(product)
            products_by_url[url] = product
        else:
            sources = "|".join(sorted(discovery.sources.get(url, set())))
            if sources:
                products_by_url[url]["ghi_chu"] = append_note(
                    products_by_url[url]["ghi_chu"],
                    f"nguon_phat_hien={sources}",
                )
    products = sort_products(products)
    atomic_write_csv(layout.product_csv, PRODUCT_HEADER, products)
    atomic_write_csv(layout.image_csv, IMAGE_HEADER, sort_images(images))
    image_by_key = {
        (row["ma_san_pham"], normalize_url(row["url_anh"]) or row["url_anh"]): row
        for row in images
    }
    next_image_number = max(
        (numeric_suffix(row["ma_anh"]) for row in images), default=0
    )
    pages_accessible = 0
    current_image_urls: set[tuple[str, str]] = set()
    no_image_count = 0
    ordered_product_urls = sorted(
        discovery.urls,
        key=lambda url: numeric_suffix(products_by_url[url]["ma_san_pham"]),
    )
    total_products = len(ordered_product_urls)
    for product_position, product_url in enumerate(ordered_product_urls, start=1):
        if product_position == 1 or product_position % 10 == 0:
            print_kv(
                "tien_do_khao_sat",
                f"{product_position}/{total_products}",
            )
            sys.stdout.flush()
        product = products_by_url[product_url]
        if not robots.can_fetch(product_url):
            product["trang_thai_truy_cap"] = "loi_truy_cap"
            product["http_status"] = ""
            product["ghi_chu"] = append_note(product["ghi_chu"], "robots_disallow")
            atomic_write_csv(layout.product_csv, PRODUCT_HEADER, products)
            continue
        try:
            response = client.fetch_bytes(product_url, kind="page")
            parsed = parse_product_html(
                decode_body(response.data, response.headers),
                product_url,
                response.final_url,
            )
        except HttpFetchError as exc:
            product["trang_thai_truy_cap"] = "loi_truy_cap"
            product["http_status"] = str(exc.status or "")
            product["ghi_chu"] = append_note(
                product["ghi_chu"], f"loi_truy_cap={clean_note(exc)}"
            )
            atomic_write_csv(layout.product_csv, PRODUCT_HEADER, products)
            continue
        pages_accessible += 1
        product["ten_san_pham"] = parsed.name
        product["http_status"] = str(response.status)
        max_order = max(
            (
                int(row["thu_tu_anh"])
                for row in images
                if row["ma_san_pham"] == product["ma_san_pham"]
            ),
            default=0,
        )
        for candidate in parsed.candidates:
            key = (product["ma_san_pham"], candidate.url)
            current_image_urls.add(key)
            existing = image_by_key.get(key)
            if existing:
                existing["nguon_phat_hien"] = "|".join(
                    sorted(
                        set(filter(None, existing["nguon_phat_hien"].split("|")))
                        | candidate.sources
                    )
                )
                existing["ghi_chu"] = append_note(
                    existing["ghi_chu"],
                    "dau_hieu_gallery=" + "|".join(sorted(candidate.signals)),
                )
                continue
            next_image_number += 1
            max_order += 1
            row = new_image_row(
                f"anh_{next_image_number:06d}",
                product,
                max_order,
                candidate,
            )
            images.append(row)
            image_by_key[key] = row
        recompute_product_counters(product, images)
        if parsed.candidates:
            own_states = {
                row["trang_thai_tai"]
                for row in images
                if row["ma_san_pham"] == product["ma_san_pham"]
                and row["la_anh_gallery"] == "1"
            }
            if own_states & IMAGE_ERROR_STATES:
                product["trang_thai_truy_cap"] = "can_kiem_tra"
            elif "chua_tai" in own_states:
                product["trang_thai_truy_cap"] = "da_khao_sat"
            else:
                product["trang_thai_truy_cap"] = "da_tai"
        else:
            no_image_count += 1
            if not any(
                row["ma_san_pham"] == product["ma_san_pham"] for row in images
            ):
                product["trang_thai_truy_cap"] = "khong_co_anh"
        images = sort_images(images)
        atomic_write_csv(layout.image_csv, IMAGE_HEADER, images)
        atomic_write_csv(layout.product_csv, PRODUCT_HEADER, products)
    print_kv("so_url_san_pham_duy_nhat", len(discovery.urls))
    print_kv("so_trang_truy_cap_duoc", pages_accessible)
    print_kv("so_url_anh_phat_hien", len(current_image_urls))
    print_kv("so_san_pham_khong_co_anh", no_image_count)
    print_kv("co_thu_sitemap", discovery.sitemap_attempted)
    print_kv("co_dung_sitemap", discovery.sitemap_used)
    print_kv("so_trang_danh_muc", discovery.catalog_pages)
    for warning in discovery.warnings:
        print(f"CANH_BAO: {warning}")
    if len(discovery.urls) != EXPECTED_PRODUCT_COUNT:
        print(
            "CAN_KIEM_TRA: So URL san pham khac 306; "
            "CSV da duoc ghi, khong tu dong tai toan bo."
        )
        return 3
    return 0


def detect_image_format(prefix: bytes) -> str | None:
    if prefix.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP":
        return "webp"
    if prefix.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if prefix.startswith(b"BM"):
        return "bmp"
    if prefix.startswith((b"II*\x00", b"MM\x00*")):
        return "tif"
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_prefix(path: Path, size: int = 16) -> bytes:
    with path.open("rb") as stream:
        return stream.read(size)


def safe_project_path(layout: Layout, stored: str) -> Path:
    if not stored:
        raise DataIntegrityError("Duong dan file trong CSV bi trong")
    candidate = (layout.root / stored).resolve()
    image_root = layout.image_root.resolve()
    try:
        candidate.relative_to(image_root)
    except ValueError as exc:
        raise DataIntegrityError(f"Duong dan vuot ngoai anh_goc: {stored}") from exc
    return candidate


def relative_project_path(layout: Layout, path: Path) -> str:
    return str(path.resolve().relative_to(layout.root.resolve()))


def build_hash_index(
    layout: Layout,
    images: Sequence[Mapping[str, str]],
) -> dict[str, Path]:
    index: dict[str, Path] = {}
    owner_paths: set[Path] = set()
    for row in sorted(images, key=lambda item: numeric_suffix(item["ma_anh"])):
        if row["trang_thai_tai"] != "da_tai":
            continue
        path = safe_project_path(layout, row["duong_dan_anh"])
        if not path.is_file():
            raise DataIntegrityError(f"Anh da_tai bi thieu: {path}")
        if path in owner_paths:
            raise DataIntegrityError(f"Hai dong da_tai cung tro mot file: {path}")
        owner_paths.add(path)
        actual_hash = sha256_file(path)
        if actual_hash != row["sha256"]:
            raise DataIntegrityError(f"SHA-256 CSV khong khop file: {path}")
        previous = index.get(actual_hash)
        if previous is not None and previous != path:
            raise DataIntegrityError(
                f"Da co hai file vat ly trung SHA-256: {previous} va {path}"
            )
        index[actual_hash] = path
    return index


def trial_is_complete(
    products: Sequence[Mapping[str, str]],
    images: Sequence[Mapping[str, str]],
) -> bool:
    selected = sort_products(list(products))[: min(5, len(products))]
    if not selected:
        return False
    for product in selected:
        if product["trang_thai_truy_cap"] not in {"da_tai", "khong_co_anh"}:
            return False
        own = [
            row
            for row in images
            if row["ma_san_pham"] == product["ma_san_pham"]
            and row["la_anh_gallery"] == "1"
        ]
        if any(row["trang_thai_tai"] not in {"da_tai", "trung_sha256"} for row in own):
            return False
    return True


def check_trial_result(
    layout: Layout,
    selected: Sequence[Mapping[str, str]],
    images: Sequence[Mapping[str, str]],
) -> list[str]:
    """Kiem tra tu dong cac dieu kien co the xac minh sau luot thu <=5."""
    problems: list[str] = []
    selected_ids = {row["ma_san_pham"] for row in selected}
    selected_directories = [
        path
        for path in layout.image_root.iterdir()
        if path.is_dir() and path.name in selected_ids
    ]
    if len(selected_directories) > 5:
        problems.append("Luot thu tao nhieu hon 5 thu muc san pham")
    physical_hashes: dict[str, Path] = {}
    for row in images:
        if row["ma_san_pham"] not in selected_ids or row["la_anh_gallery"] != "1":
            continue
        if not row["url_san_pham"] or not row["url_anh"]:
            problems.append(f"Thieu URL truy vet: {row['ma_anh']}")
        state = row["trang_thai_tai"]
        if state == "da_tai":
            try:
                path = safe_project_path(layout, row["duong_dan_anh"])
            except DataIntegrityError as exc:
                problems.append(str(exc))
                continue
            if not path.is_file():
                problems.append(f"Thieu file anh: {path}")
                continue
            actual_format = detect_image_format(read_prefix(path))
            actual_hash = sha256_file(path)
            if actual_format is None:
                problems.append(f"File khong co magic bytes anh hop le: {path}")
            if actual_hash != row["sha256"]:
                problems.append(f"SHA CSV khong khop file: {path}")
            previous = physical_hashes.get(actual_hash)
            if previous is not None and previous != path:
                problems.append(f"Hai file vat ly trung SHA: {previous} va {path}")
            physical_hashes[actual_hash] = path
        elif state == "trung_sha256":
            try:
                original = safe_project_path(layout, row["duong_dan_file_goc"])
            except DataIntegrityError as exc:
                problems.append(str(exc))
                continue
            if not original.is_file() or sha256_file(original) != row["sha256"]:
                problems.append(f"File goc anh trung khong hop le: {row['ma_anh']}")
        else:
            problems.append(f"Anh chua hoan tat {row['ma_anh']}: {state}")
    for path in layout.root.rglob("*"):
        lower_name = path.name.casefold()
        if path.is_dir() and lower_name == "__pycache__":
            problems.append(f"Con __pycache__: {path}")
        elif path.is_file() and lower_name.endswith((".tmp", ".part", ".bak")):
            problems.append(f"Con file tam: {path}")
    return problems


def persist_download_state(
    layout: Layout,
    products: list[dict[str, str]],
    images: list[dict[str, str]],
    product: dict[str, str],
) -> None:
    recompute_product_counters(product, images, after_download=True)
    atomic_write_csv(layout.image_csv, IMAGE_HEADER, sort_images(images))
    atomic_write_csv(layout.product_csv, PRODUCT_HEADER, sort_products(products))


def run_download(
    layout: Layout,
    *,
    limit: int | None,
    retry_errors: bool,
) -> int:
    check_layout(layout, require_csv=True)
    products, images = load_tables(layout)
    if not products:
        raise SafetyGateError("san_pham.csv khong co san pham de tai")
    selected_count = min(limit if limit is not None else len(products), len(products))
    if selected_count > 5 and not trial_is_complete(products, images):
        raise SafetyGateError(
            "Chua hoan thanh/kiem tra luot thu 5 san pham; "
            "hay chay --tai-anh --gioi-han-san-pham 5 truoc"
        )
    client = HttpClient()
    robots = check_robots(client)
    if not robots.allowed:
        raise CollectorError("robots.txt khong cho phep truy cap trang san pham")
    hash_index = build_hash_index(layout, images)
    selected = sort_products(products)
    if limit is not None:
        selected = selected[:limit]
    blocked = [
        product["url_san_pham"]
        for product in selected
        if not robots.can_fetch(product["url_san_pham"])
    ]
    if blocked:
        raise CollectorError(
            "robots.txt chan trang san pham; dung truoc khi tai anh: "
            + ", ".join(blocked[:5])
        )
    states_to_attempt = {"chua_tai"}
    if retry_errors:
        states_to_attempt |= IMAGE_ERROR_STATES
    attempted = 0
    successful = 0
    duplicates = 0
    failed = 0
    for product in selected:
        own_rows = [
            row
            for row in sort_images(images)
            if row["ma_san_pham"] == product["ma_san_pham"]
            and row["la_anh_gallery"] == "1"
            and row["trang_thai_tai"] in states_to_attempt
        ]
        if not own_rows:
            recompute_product_counters(product, images, after_download=True)
            continue
        product_directory = layout.image_root / product["ma_san_pham"]
        product_directory.mkdir(exist_ok=True)
        for row in own_rows:
            attempted += 1
            for field_name in (
                "ten_file",
                "duong_dan_anh",
                "http_status",
                "mime_type",
                "kich_thuoc_byte",
                "sha256",
                "duong_dan_file_goc",
            ):
                row[field_name] = ""
            row["la_anh_trung"] = "0"
            normalized_url = normalize_url(row["url_anh"])
            if not normalized_url or not is_public_image_url(normalized_url):
                row["trang_thai_tai"] = "url_khong_hop_le"
                row["ghi_chu"] = append_note(row["ghi_chu"], "URL anh khong hop le")
                failed += 1
                persist_download_state(layout, products, images, product)
                continue
            payload: DownloadedImage | None = None
            try:
                payload = client.download_image(normalized_url, row["url_san_pham"])
                row["http_status"] = str(payload.http_status)
                row["mime_type"] = payload.actual_mime
                row["kich_thuoc_byte"] = str(payload.size)
                row["sha256"] = payload.sha256
                if payload.header_mime and payload.header_mime != payload.actual_mime:
                    row["ghi_chu"] = append_note(
                        row["ghi_chu"],
                        f"content_type_header={payload.header_mime}",
                    )
                original = hash_index.get(payload.sha256)
                if original is not None:
                    row["ten_file"] = ""
                    row["duong_dan_anh"] = ""
                    row["trang_thai_tai"] = "trung_sha256"
                    row["la_anh_trung"] = "1"
                    row["duong_dan_file_goc"] = relative_project_path(
                        layout, original
                    )
                    duplicates += 1
                    continue
                order = int(row["thu_tu_anh"])
                filename = (
                    f"anh_{order:03d}_{payload.sha256[:8]}.{payload.extension}"
                )
                destination = product_directory / filename
                if destination.exists():
                    existing_hash = sha256_file(destination)
                    if existing_hash != payload.sha256:
                        raise DataIntegrityError(
                            f"Khong ghi de file da ton tai khac SHA: {destination}"
                        )
                else:
                    if payload.temp_path.drive.casefold() != destination.drive.casefold():
                        raise SafetyGateError(
                            "Thu muc tam va du an khac volume; dung de tranh copy khong atomic"
                        )
                    try:
                        os.rename(payload.temp_path, destination)
                    except OSError as exc:
                        raise SafetyGateError(
                            f"Khong chuyen duoc file tam vao du an: {clean_note(exc)}"
                        ) from exc
                    payload.temp_path = None
                row["ten_file"] = filename
                row["duong_dan_anh"] = relative_project_path(layout, destination)
                row["trang_thai_tai"] = "da_tai"
                row["la_anh_trung"] = "0"
                row["duong_dan_file_goc"] = row["duong_dan_anh"]
                hash_index[payload.sha256] = destination
                successful += 1
            except DownloadTooLarge as exc:
                row["http_status"] = str(exc.status or "")
                row["kich_thuoc_byte"] = str(exc.size or "")
                row["sha256"] = ""
                row["trang_thai_tai"] = "qua_lon"
                row["la_anh_trung"] = "0"
                row["ghi_chu"] = append_note(row["ghi_chu"], str(exc))
                failed += 1
            except HttpFetchError as exc:
                row["http_status"] = str(exc.status or "")
                row["sha256"] = ""
                row["trang_thai_tai"] = "loi_http"
                row["la_anh_trung"] = "0"
                row["ghi_chu"] = append_note(
                    row["ghi_chu"], f"loi_http={clean_note(exc)}"
                )
                failed += 1
            except SafetyGateError:
                row["mime_type"] = ""
                row["kich_thuoc_byte"] = ""
                row["sha256"] = ""
                row["trang_thai_tai"] = "chua_tai"
                row["la_anh_trung"] = "0"
                raise
            except InvalidImageFormat as exc:
                row["http_status"] = str(exc.status)
                row["mime_type"] = exc.header_mime
                row["kich_thuoc_byte"] = str(exc.size)
                row["sha256"] = ""
                row["trang_thai_tai"] = "loi_dinh_dang"
                row["la_anh_trung"] = "0"
                row["ghi_chu"] = append_note(row["ghi_chu"], str(exc))
                failed += 1
            except DataIntegrityError as exc:
                row["sha256"] = ""
                row["trang_thai_tai"] = "loi_dinh_dang"
                row["la_anh_trung"] = "0"
                row["ghi_chu"] = append_note(row["ghi_chu"], str(exc))
                failed += 1
            finally:
                if payload is not None and payload.temp_path is not None:
                    try:
                        payload.temp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                persist_download_state(layout, products, images, product)
    atomic_write_csv(layout.image_csv, IMAGE_HEADER, sort_images(images))
    atomic_write_csv(layout.product_csv, PRODUCT_HEADER, sort_products(products))
    print_kv("so_anh_da_thu", attempted)
    print_kv("so_anh_tai_thanh_cong", successful)
    print_kv("so_anh_trung", duplicates)
    print_kv("so_anh_loi", failed)
    if limit is not None and limit <= 5:
        trial_problems = check_trial_result(layout, selected, images)
        for problem in trial_problems:
            print(f"LOI_KIEM_TRA_THU: {problem}")
        print_kv("kiem_tra_luot_thu_hop_le", not trial_problems)
        if trial_problems:
            return 4
    return 0 if failed == 0 else 1


def finalize_known_public_403_exceptions(
    layout: Layout,
    products: list[dict[str, str]],
    images: list[dict[str, str]],
) -> None:
    image_by_id = {row["ma_anh"]: row for row in images}
    product_by_id = {row["ma_san_pham"]: row for row in products}
    target_rows: list[dict[str, str]] = []

    for row in images:
        if (
            row["trang_thai_tai"] == PUBLIC_UNAVAILABLE_STATE
            and row["ma_anh"] not in KNOWN_PUBLIC_403_EXCEPTIONS
        ):
            raise DataIntegrityError(
                "Trang thai khong_the_tai_cong_khai ngoai danh sach duyet: "
                f"{row['ma_anh']}"
            )

    for image_id, (product_id, source_url) in KNOWN_PUBLIC_403_EXCEPTIONS.items():
        row = image_by_id.get(image_id)
        if row is None:
            raise DataIntegrityError(f"Thieu dong ngoai le da duyet: {image_id}")
        if row["ma_san_pham"] != product_id:
            raise DataIntegrityError(f"Sai ma_san_pham cua ngoai le: {image_id}")
        if row["url_anh"] != source_url:
            raise DataIntegrityError(f"URL nguon ngoai le da thay doi: {image_id}")
        if row["trang_thai_tai"] not in {
            "loi_http",
            PUBLIC_UNAVAILABLE_STATE,
        }:
            raise DataIntegrityError(
                f"Trang thai truoc khi chot ngoai le khong hop le: {image_id}"
            )
        if row["http_status"] != "403":
            raise DataIntegrityError(f"Ngoai le khong co HTTP 403: {image_id}")
        nonempty = [
            field_name
            for field_name in PUBLIC_UNAVAILABLE_EMPTY_FIELDS
            if row[field_name]
        ]
        if nonempty:
            raise DataIntegrityError(
                f"Ngoai le co du lieu file/hash tai {image_id}: "
                + ", ".join(nonempty)
            )
        if row["mime_type"]:
            raise DataIntegrityError(f"Ngoai le co MIME tai {image_id}")
        if row["la_anh_trung"] != "0":
            raise DataIntegrityError(f"Ngoai le co la_anh_trung != 0: {image_id}")
        if (
            row["trang_thai_tai"] == PUBLIC_UNAVAILABLE_STATE
            and row["ghi_chu"] != PUBLIC_UNAVAILABLE_NOTE
        ):
            raise DataIntegrityError(f"Ghi chu ngoai le khong hop le: {image_id}")
        target_rows.append(row)

    product_id = "san_pham_0262"
    product = product_by_id.get(product_id)
    if product is None:
        raise DataIntegrityError(f"Thieu san pham ngoai le da duyet: {product_id}")
    if product["trang_thai_truy_cap"] not in {
        "can_kiem_tra",
        PRODUCT_EXCEPTION_STATE,
    }:
        raise DataIntegrityError(
            "Trang thai san pham truoc khi chot ngoai le khong hop le: "
            f"{product_id}={product['trang_thai_truy_cap']}"
        )
    target_ids = set(KNOWN_PUBLIC_403_EXCEPTIONS)
    unresolved_for_product = [
        row["ma_anh"]
        for row in images
        if row["ma_san_pham"] == product_id
        and row["la_anh_gallery"] == "1"
        and row["trang_thai_tai"] in {"chua_tai", "loi_http"}
        and row["ma_anh"] not in target_ids
    ]
    if unresolved_for_product:
        raise DataIntegrityError(
            f"{product_id} con anh chua xu ly ngoai danh sach ngoai le: "
            + ", ".join(unresolved_for_product)
        )

    image_changed = False
    for row in target_rows:
        if row["trang_thai_tai"] == "loi_http":
            row["trang_thai_tai"] = PUBLIC_UNAVAILABLE_STATE
            row["ghi_chu"] = PUBLIC_UNAVAILABLE_NOTE
            image_changed = True
    product_changed = product["trang_thai_truy_cap"] != PRODUCT_EXCEPTION_STATE
    if product_changed:
        product["trang_thai_truy_cap"] = PRODUCT_EXCEPTION_STATE

    if image_changed:
        atomic_write_csv(layout.image_csv, IMAGE_HEADER, images)
    if product_changed:
        atomic_write_csv(layout.product_csv, PRODUCT_HEADER, products)


def verify_csv_rows(
    layout: Layout,
    products: Sequence[Mapping[str, str]],
    images: Sequence[Mapping[str, str]],
    problems: list[str],
) -> None:
    product_by_id = {row["ma_san_pham"]: row for row in products}
    grouped: dict[str, list[Mapping[str, str]]] = {}
    for row in images:
        grouped.setdefault(row["ma_san_pham"], []).append(row)
        if row["url_san_pham"] != product_by_id[row["ma_san_pham"]]["url_san_pham"]:
            problems.append(f"url_san_pham khong khop tai {row['ma_anh']}")
    for product in products:
        own = [
            row
            for row in grouped.get(product["ma_san_pham"], [])
            if row["la_anh_gallery"] == "1"
        ]
        expected = {
            "so_url_anh_phat_hien": len(own),
            "so_anh_tai_thanh_cong": sum(
                row["trang_thai_tai"] == "da_tai" for row in own
            ),
            "so_anh_trung": sum(
                row["trang_thai_tai"] == "trung_sha256" for row in own
            ),
            "so_anh_loi": sum(
                row["trang_thai_tai"] in IMAGE_RECORDED_ERROR_STATES for row in own
            ),
        }
        for field_name, value in expected.items():
            if product[field_name] != str(value):
                problems.append(
                    f"{product['ma_san_pham']}: {field_name}={product[field_name]}, "
                    f"thuc_te={value}"
                )
        exception_rows = [
            row
            for row in own
            if row["trang_thai_tai"]
            in IMAGE_TERMINAL_ERROR_STATES | {PUBLIC_UNAVAILABLE_STATE}
        ]
        product_has_exception_state = (
            product["trang_thai_truy_cap"] == PRODUCT_EXCEPTION_STATE
        )
        if bool(exception_rows) != product_has_exception_state:
            problems.append(
                f"Trang thai ngoai le san pham khong khop: {product['ma_san_pham']}"
            )
        if product["trang_thai_truy_cap"] not in {
            "da_tai",
            "khong_co_anh",
            PRODUCT_EXCEPTION_STATE,
        }:
            problems.append(
                f"San pham chua o trang thai ket thuc: "
                f"{product['ma_san_pham']}={product['trang_thai_truy_cap']}"
            )


def run_verification(
    layout: Layout,
    *,
    limit: int | None = None,
    emit: bool = True,
) -> VerificationResult:
    check_layout(layout, require_csv=True)
    products, images = load_tables(layout)
    if limit is None:
        finalize_known_public_403_exceptions(layout, products, images)
    if limit is not None:
        products = products[:limit]
        selected_product_ids = {row["ma_san_pham"] for row in products}
        images = [
            row for row in images if row["ma_san_pham"] in selected_product_ids
        ]
    problems: list[str] = []
    verify_csv_rows(layout, products, images, problems)
    owner_paths: dict[Path, Mapping[str, str]] = {}
    missing_rows = 0
    sha256_errors = 0
    stored_original_hashes: set[str] = set()
    for row in images:
        state = row["trang_thai_tai"]
        if not row["nguon_phat_hien"]:
            problems.append(f"Anh thieu nguon_phat_hien: {row['ma_anh']}")
        if not row["url_san_pham"] or (
            not row["url_anh"] and state != "url_khong_hop_le"
        ):
            problems.append(f"Anh thieu URL truy vet: {row['ma_anh']}")
        if state == "da_tai":
            try:
                path = safe_project_path(layout, row["duong_dan_anh"])
            except DataIntegrityError as exc:
                missing_rows += 1
                problems.append(str(exc))
                continue
            if not path.is_file():
                missing_rows += 1
                problems.append(f"Dong CSV khong tim thay file: {row['ma_anh']}")
                continue
            if path in owner_paths:
                problems.append(f"Hai dong da_tai cung so huu file: {path}")
            owner_paths[path] = row
            actual_hash = sha256_file(path)
            actual_format = detect_image_format(read_prefix(path))
            if actual_hash != row["sha256"]:
                sha256_errors += 1
                problems.append(f"SHA khong khop: {path}")
            if actual_format is None or path.suffix.casefold() != f".{actual_format}":
                problems.append(f"Magic bytes/duoi file khong khop: {path}")
            if str(path.stat().st_size) != row["kich_thuoc_byte"]:
                problems.append(f"Kich thuoc CSV khong khop: {path}")
            if path.stat().st_size > MAX_IMAGE_BYTES:
                problems.append(f"File vuot 10 MiB: {path}")
            if row["sha256"]:
                stored_original_hashes.add(row["sha256"])
            if row["la_anh_trung"] != "0":
                problems.append(f"Anh da_tai co la_anh_trung != 0: {row['ma_anh']}")
            if row["mime_type"] != IMAGE_MIME.get(actual_format or "", ""):
                problems.append(f"MIME CSV khong khop magic bytes: {row['ma_anh']}")
            expected_name = (
                f"anh_{int(row['thu_tu_anh']):03d}_{row['sha256'][:8]}"
                f"{path.suffix.casefold()}"
            )
            if path.name.casefold() != expected_name.casefold():
                problems.append(f"Ten file khong dung quy tac: {path}")
        elif state == "trung_sha256":
            try:
                original = safe_project_path(layout, row["duong_dan_file_goc"])
            except DataIntegrityError as exc:
                missing_rows += 1
                problems.append(str(exc))
                continue
            if not original.is_file():
                missing_rows += 1
                problems.append(f"Anh trung khong tim thay file goc: {row['ma_anh']}")
            else:
                if sha256_file(original) != row["sha256"]:
                    sha256_errors += 1
                    problems.append(
                        f"Anh trung co SHA khong khop file goc: {row['ma_anh']}"
                    )
                if limit is not None and detect_image_format(read_prefix(original)) is None:
                    problems.append(
                        f"File goc anh trung khong co magic bytes hop le: "
                        f"{row['ma_anh']}"
                    )
            if row["la_anh_trung"] != "1":
                problems.append(f"Anh trung thieu co la_anh_trung=1: {row['ma_anh']}")
            if row["ten_file"] or row["duong_dan_anh"]:
                problems.append(
                    f"Anh trung khong duoc co file vat ly rieng: {row['ma_anh']}"
                )
        elif state == "chua_tai":
            problems.append(f"Anh con chua tai: {row['ma_anh']}")
        elif state == "loi_http":
            problems.append(f"Anh dang o trang thai loi {state}: {row['ma_anh']}")
        elif state == PUBLIC_UNAVAILABLE_STATE:
            expected = KNOWN_PUBLIC_403_EXCEPTIONS.get(row["ma_anh"])
            if (
                expected is None
                or row["ma_san_pham"] != expected[0]
                or row["url_anh"] != expected[1]
            ):
                problems.append(
                    f"Ngoai le 403 khong nam trong danh sach duyet: {row['ma_anh']}"
                )
            if row["http_status"] != "403":
                problems.append(f"Ngoai le khong co HTTP 403: {row['ma_anh']}")
            if row["ghi_chu"] != PUBLIC_UNAVAILABLE_NOTE:
                problems.append(f"Ghi chu ngoai le khong hop le: {row['ma_anh']}")
            nonempty = [
                field_name
                for field_name in PUBLIC_UNAVAILABLE_EMPTY_FIELDS
                if row[field_name]
            ]
            if nonempty:
                problems.append(
                    f"Ngoai le co du lieu file/hash tai {row['ma_anh']}: "
                    + ", ".join(nonempty)
                )
            if row["mime_type"]:
                problems.append(f"Ngoai le co MIME tai {row['ma_anh']}")
            if row["la_anh_trung"] != "0":
                problems.append(
                    f"Ngoai le co la_anh_trung != 0: {row['ma_anh']}"
                )
        elif state in IMAGE_TERMINAL_ERROR_STATES:
            unexpected_file_fields = [
                field_name
                for field_name in (
                    "ten_file",
                    "duong_dan_anh",
                    "sha256",
                    "duong_dan_file_goc",
                )
                if row[field_name]
            ]
            if unexpected_file_fields:
                problems.append(
                    f"Anh ket thuc {state} co du lieu file tai {row['ma_anh']}: "
                    + ", ".join(unexpected_file_fields)
                )
            if row["la_anh_trung"] != "0":
                problems.append(
                    f"Anh ket thuc {state} co la_anh_trung != 0: {row['ma_anh']}"
                )
    if limit is None:
        physical_files = sorted(
            path for path in layout.image_root.rglob("*") if path.is_file()
        )
    else:
        selected_directories = [
            layout.image_root / product["ma_san_pham"] for product in products
        ]
        physical_files = sorted(
            path
            for directory in selected_directories
            if directory.is_dir()
            for path in directory.rglob("*")
            if path.is_file()
        )
    physical_hashes: dict[str, list[Path]] = {}
    total_bytes = 0
    untracked = 0
    for path in physical_files:
        total_bytes += path.stat().st_size
        digest = sha256_file(path)
        physical_hashes.setdefault(digest, []).append(path)
        if path.resolve() not in {item.resolve() for item in owner_paths}:
            untracked += 1
            problems.append(f"File khong co dong CSV da_tai: {path}")
        if detect_image_format(read_prefix(path)) is None:
            problems.append(f"File vat ly khong phai dinh dang anh ho tro: {path}")
    for digest, paths in physical_hashes.items():
        if len(paths) > 1:
            problems.append(
                f"Nhieu file vat ly trung SHA {digest}: "
                + ", ".join(str(path) for path in paths)
            )
    residue: list[Path] = []
    for path in layout.root.rglob("*"):
        lower_name = path.name.casefold()
        if path.is_dir() and lower_name in {"__pycache__", "cache"}:
            residue.append(path)
        elif path.is_file() and (
            lower_name.endswith((".tmp", ".part", ".bak"))
            or lower_name.endswith((".pyc", ".pyo"))
        ):
            residue.append(path)
    for path in residue:
        problems.append(f"File/thu muc tam hoac cache con sot: {path}")
    if len(physical_files) != len(physical_hashes):
        problems.append("So file vat ly khong bang so SHA vat ly duy nhat")
    if len(physical_files) != len(stored_original_hashes):
        problems.append("So file vat ly khong bang so SHA da_tai duy nhat trong CSV")
    stats = {
        "so_san_pham_duoc_kiem_tra": len(products),
        "so_anh_thuoc_pham_vi": len(images),
        "so_url_san_pham_duy_nhat": len(
            {normalize_url(row["url_san_pham"]) for row in products}
        ),
        "so_san_pham_truy_cap_thanh_cong": sum(
            row["trang_thai_truy_cap"] in PRODUCT_SUCCESS_STATES for row in products
        ),
        "so_san_pham_loi": sum(
            row["trang_thai_truy_cap"] == "loi_truy_cap" for row in products
        ),
        "so_url_anh_phat_hien": len(
            {
                (row["ma_san_pham"], normalize_url(row["url_anh"]))
                for row in images
                if row["la_anh_gallery"] == "1"
            }
        ),
        "so_anh_tai_thanh_cong": sum(
            row["trang_thai_tai"] == "da_tai" for row in images
        ),
        "so_sha256_duy_nhat": len(
            {
                row["sha256"]
                for row in images
                if row["sha256"]
                and row["trang_thai_tai"] in {"da_tai", "trung_sha256"}
            }
        ),
        "so_luot_anh_trung": sum(
            row["trang_thai_tai"] == "trung_sha256" for row in images
        ),
        "so_anh_trung": sum(
            row["trang_thai_tai"] == "trung_sha256" for row in images
        ),
        "so_anh_loi": sum(
            row["trang_thai_tai"] in IMAGE_ERROR_STATES for row in images
        ),
        "so_anh_khong_the_tai_cong_khai": sum(
            row["trang_thai_tai"] == PUBLIC_UNAVAILABLE_STATE for row in images
        ),
        "so_loi_sha256": sha256_errors,
        "so_anh_loi_http": sum(
            row["trang_thai_tai"] == "loi_http" for row in images
        ),
        "so_anh_loi_dinh_dang": sum(
            row["trang_thai_tai"] == "loi_dinh_dang" for row in images
        ),
        "tong_dung_luong_anh": total_bytes,
        "so_file_vat_ly": len(physical_files),
        "so_sha256_file_vat_ly": len(physical_hashes),
        "so_dong_csv_khong_tim_thay_file": missing_rows,
        "so_file_khong_co_dong_csv": untracked,
        "so_file_tam_hoac_cache": len(residue),
        "co_file_rac": int(bool(residue)),
    }
    stats["hoan_thanh_co_ngoai_le"] = (
        not problems and stats["so_anh_khong_the_tai_cong_khai"] > 0
    )
    if emit:
        for label, value in stats.items():
            print_kv(label, value)
        if (
            limit is None
            and stats["so_url_san_pham_duy_nhat"] != EXPECTED_PRODUCT_COUNT
        ):
            print(
                "CAN_KIEM_TRA: So URL san pham khac 306; "
                "can doi chieu thu cong truoc khi tai toan bo."
            )
        for problem in problems:
            print(f"LOI_KIEM_TRA: {problem}")
        print_kv("ket_qua_hop_le", not problems)
    return VerificationResult(ok=not problems, stats=stats, problems=problems)


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("phai la so nguyen") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("phai lon hon 0")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Khao sat va tai anh gallery san pham cong khai tren Hathyo."
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--kiem-tra-moi-truong",
        action="store_true",
        help="Kiem tra thu muc, quyen ghi, website va robots.txt; khong tao du lieu.",
    )
    modes.add_argument(
        "--khao-sat",
        action="store_true",
        help="Phat hien san pham va URL gallery; khong tai file anh.",
    )
    modes.add_argument(
        "--tai-anh",
        action="store_true",
        help="Tai cac anh chua tai trong anh.csv.",
    )
    modes.add_argument(
        "--kiem-tra-ket-qua",
        action="store_true",
        help="Doi chieu CSV, magic bytes, SHA-256 va file vat ly.",
    )
    parser.add_argument(
        "--gioi-han-san-pham",
        type=positive_int,
        metavar="N",
        help=(
            "Chi xu ly N san pham dau; dung voi "
            "--tai-anh hoac --kiem-tra-ket-qua."
        ),
    )
    parser.add_argument(
        "--thu-lai-loi",
        action="store_true",
        help="Thu lai cac dong anh loi; chi dung voi --tai-anh.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.gioi_han_san_pham is not None and not (
        args.tai_anh or args.kiem_tra_ket_qua
    ):
        parser.error(
            "--gioi-han-san-pham chi dung voi "
            "--tai-anh/--kiem-tra-ket-qua"
        )
    if args.thu_lai_loi and not args.tai_anh:
        parser.error("--thu-lai-loi chi dung voi --tai-anh")
    layout = Layout.from_script()
    try:
        if args.kiem_tra_moi_truong:
            return run_environment_check(layout)
        if args.khao_sat:
            return run_survey(layout)
        if args.tai_anh:
            return run_download(
                layout,
                limit=args.gioi_han_san_pham,
                retry_errors=args.thu_lai_loi,
            )
        result = run_verification(
            layout,
            limit=args.gioi_han_san_pham,
        )
        return 0 if result.ok else 4
    except SafetyGateError as exc:
        print(f"CAN_KIEM_TRA: {clean_note(exc)}", file=sys.stderr)
        return 3
    except DataIntegrityError as exc:
        print(f"LOI_DU_LIEU: {clean_note(exc)}", file=sys.stderr)
        return 4
    except CollectorError as exc:
        print(f"LOI: {clean_note(exc)}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"LOI_HE_THONG: {clean_note(exc)}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("DA_DUNG: Nguoi dung ngat chuong trinh.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
