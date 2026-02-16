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
from typing import Optional
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


def _validate_image(candidate_url: str, timeout: int = 4) -> bool:
    # try head first since it's cheaper, fall back to get if that fails
    try:
        head = requests.head(candidate_url, timeout=timeout,
                             allow_redirects=True, verify=False)
        if head.status_code < 400:
            content_type = (head.headers.get("content-type") or "").lower()
            return "image" in content_type or candidate_url.lower().endswith(
                (".ico", ".png", ".jpg", ".jpeg", ".svg", ".webp")
            )
    except requests.RequestException:
        pass

    try:
        # some servers dont respond to head - do a streaming get so we dont download the whole thing
        get_resp = requests.get(
            candidate_url, timeout=timeout, stream=True, verify=False)
        content_type = (get_resp.headers.get("content-type") or "").lower()
        return get_resp.status_code < 400 and (
            "image" in content_type
            or candidate_url.lower().endswith((".ico", ".png", ".jpg", ".jpeg", ".svg", ".webp"))
        )
    except requests.RequestException:
        return False


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
        if _validate_image(candidate, timeout=timeout):
            return candidate

    return None
