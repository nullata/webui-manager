# Copyright 2026 nullata/webui-manager
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from flask import current_app
import base64
import hashlib
from html.parser import HTMLParser
from typing import Callable, Optional
from urllib.parse import urlparse, urljoin

import requests
import urllib3
from cryptography.fernet import Fernet, InvalidToken

# self-signed certs are common in homelabs - suppress the noise
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class _IconParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        # collect href values from any <link> tag with "icon" in the rel attribute
        if tag.lower() != "link":
            return

        attrs_dict = {k.lower(): v for k, v in attrs}
        rel_value = (attrs_dict.get("rel") or "").lower()
        href = attrs_dict.get("href")
        if href and "icon" in rel_value:
            self.hrefs.append(href)


def run_with_app_context(app, fn: Callable, error_msg: str) -> None:
    # standard wrapper for background threads: app context + rollback/cleanup on failure
    from .models import db
    with app.app_context():
        try:
            fn()
        except Exception:
            db.session.rollback()
            app.logger.exception(error_msg)
        finally:
            db.session.remove()


def normalize_url(raw_url: str) -> str:
    # add http:// if the url doesn't already have a scheme
    value = (raw_url or "").strip()
    if not value:
        return value

    if not value.startswith(("http://", "https://")):
        return f"http://{value}"
    return value


def extract_host(value: str) -> str:
    # pull just the netloc part out of a url
    parsed = urlparse(normalize_url(value))
    return parsed.netloc


def _fernet() -> Fernet:
    # derive a valid fernet key from the app secret using sha256
    # falls back to SECRET_KEY if APP_CREDENTIALS_KEY isn't set
    configured_key = current_app.config.get("APP_CREDENTIALS_KEY")
    source = configured_key or current_app.secret_key
    digest = hashlib.sha256(str(source).encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret(secret: Optional[str]) -> Optional[str]:
    if not secret:
        return None
    return _fernet().encrypt(secret.encode("utf-8")).decode("utf-8")


def decrypt_secret(secret: Optional[str]) -> Optional[str]:
    if not secret:
        return None
    try:
        return _fernet().decrypt(secret.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        # decryption failed - key changed or data is corrupt
        return None


_IMAGE_EXTENSIONS = (".ico", ".png", ".jpg", ".jpeg", ".svg", ".webp")
_CONTENT_TYPE_MAP = {
    "ico": "image/x-icon",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "svg": "image/svg+xml",
    "webp": "image/webp",
}
_MAX_FAVICON_BYTES = 100 * 1024  # 100 KB cap - favicons are tiny


def _fetch_favicon_data_uri(candidate_url: str, timeout: int = 4) -> Optional[str]:
    # downloads the image and returns a base64 data URI so the browser never
    # needs to make a direct request to the service (handles self-signed certs)
    try:
        resp = requests.get(
            candidate_url, timeout=timeout, verify=False,
            allow_redirects=True, stream=True,
        )
        if resp.status_code >= 400:
            return None

        content_type = (resp.headers.get("content-type") or "").lower().split(";")[0].strip()
        ext = candidate_url.lower().rsplit(".", 1)[-1] if "." in candidate_url else ""

        is_image = "image" in content_type or candidate_url.lower().endswith(_IMAGE_EXTENSIONS)
        if not is_image:
            return None

        data = b""
        for chunk in resp.iter_content(8192):
            data += chunk
            if len(data) > _MAX_FAVICON_BYTES:
                return None

        if not data:
            return None

        # normalise content-type - some servers return generic octet-stream for .ico
        if not content_type.startswith("image/"):
            content_type = _CONTENT_TYPE_MAP.get(ext, "image/x-icon")

        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{content_type};base64,{encoded}"
    except requests.RequestException:
        return None


def resolve_favicon(site_url: str, timeout: int = 4) -> Optional[str]:
    normalized = normalize_url(site_url)
    if not normalized:
        return None

    parsed = urlparse(normalized)
    if not parsed.netloc:
        return None

    base_origin = f"{parsed.scheme}://{parsed.netloc}"
    candidates = []
    # track the final origin separately in case the site redirects to a different host
    final_origin = base_origin

    try:
        # fetch the page and parse out any <link rel="icon"> tags
        response = requests.get(
            normalized, timeout=timeout, allow_redirects=True, verify=False)
        response.raise_for_status()

        # use the post-redirect url as the base for resolving relative icon hrefs
        final_parsed = urlparse(response.url)
        final_origin = f"{final_parsed.scheme}://{final_parsed.netloc}"

        parser = _IconParser()
        # cap at 150k chars - enough to find the <head> without loading massive pages
        parser.feed(response.text[:150000])
        for href in parser.hrefs:
            candidates.append(urljoin(response.url, href))
    except requests.RequestException:
        pass

    # always fall back to /favicon.ico on both the final and original origin
    candidates.append(urljoin(final_origin, "/favicon.ico"))
    if final_origin != base_origin:
        candidates.append(urljoin(base_origin, "/favicon.ico"))

    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        data_uri = _fetch_favicon_data_uri(candidate, timeout=timeout)
        if data_uri:
            return data_uri

    return None
