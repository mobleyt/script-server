"""
aviary.py — Minimal client for the Aviary REST API (see aviary-api.json).

Only the calls the uploader needs: list collections, look up a resource by
custom unique identifier, create a resource, and attach a media file by link
(Aviary downloads the file itself, so no media passes through this server).
"""

from urllib.parse import quote

import requests

TIMEOUT = (10, 60)  # connect, read (seconds)


class AviaryError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _error_message(resp):
    """Best human-readable message from an Aviary error response."""
    if resp.status_code == 401:
        # Aviary's own text here ("You need to sign in or sign up…") doesn't
        # point at the real fix.
        return ("Aviary rejected the API key. Check AVIARY_API_KEY in .env, "
                "then run: docker compose up -d aviary-uploader")
    try:
        body = resp.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        errors = body.get("errors") or body.get("error") or body.get("message")
        if isinstance(errors, dict):
            errors = [f"{k} {', '.join(v) if isinstance(v, list) else v}"
                      for k, v in errors.items()]
        if isinstance(errors, list) and errors:
            return "; ".join(str(e) for e in errors)
        if isinstance(errors, str) and errors:
            return errors
    if resp.status_code == 403:
        return "The API key isn't allowed to do this in Aviary"
    if resp.status_code == 404:
        return "Not found in Aviary"
    return f"Aviary returned HTTP {resp.status_code}"


class AviaryClient:
    def __init__(self, base_url, api_key, org_id, session=None):
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update({
            "Authorization": api_key,
            "organization-id": str(org_id),
            "Accept": "application/json",
            "User-Agent": "script-server-aviary-uploader",
        })

    def _request(self, method, path, **kwargs):
        try:
            resp = self.session.request(method, self.base_url + path,
                                        timeout=TIMEOUT, **kwargs)
        except requests.RequestException as e:
            raise AviaryError(502, f"Could not reach Aviary ({e.__class__.__name__})") from e
        if not resp.ok:
            raise AviaryError(resp.status_code, _error_message(resp))
        try:
            body = resp.json()
        except ValueError as e:
            raise AviaryError(502, "Aviary sent a response that isn't JSON") from e
        if isinstance(body, dict) and body.get("success") is False:
            raise AviaryError(422, _error_message(resp))
        return body

    # ---- collections -----------------------------------------------------

    def list_collections(self, page_size=100, max_pages=50):
        """All collections in the organization as [{id, title}], by title."""
        collections, seen = [], set()
        for page in range(1, max_pages + 1):
            body = self._request("GET", "/api/v1/collections",
                                 params={"page_size": page_size, "page_number": page})
            items = body.get("data", []) if isinstance(body, dict) else body
            if not isinstance(items, list):
                items = []
            for c in items:
                cid = c.get("id", c.get("collection_id"))
                if cid is None or cid in seen:
                    continue
                seen.add(cid)
                title = c.get("title") or c.get("name") or f"Collection {cid}"
                collections.append({"id": cid, "title": title})
            total = body.get("total_entries") if isinstance(body, dict) else None
            if len(items) < page_size or (total is not None and len(collections) >= total):
                break
        collections.sort(key=lambda c: str(c["title"]).lower())
        return collections

    # ---- resources -------------------------------------------------------

    def find_resource_by_cuid(self, cuid):
        """The existing resource with this custom unique identifier, or None.

        The same URL pattern also looks resources up by numeric ID, so the
        returned identifier is compared before treating it as a match.
        Aviary answers an unknown identifier with 403 "not authorized" rather
        than 404, so that counts as not found too; a real permission problem
        still surfaces when the resource is created.
        """
        try:
            body = self._request("GET", "/api/v1/resources/" + quote(cuid, safe=""))
        except AviaryError as e:
            if e.status in (403, 404, 422):
                return None
            raise
        data = body.get("data") if isinstance(body, dict) else None
        if isinstance(data, dict) and str(data.get("custom_unique_identifier", "")) == cuid:
            return data
        return None

    def create_resource(self, collection_id, row):
        """Create a resource from a parsed spreadsheet row. Returns its data."""
        form = [
            ("collection_id", str(collection_id)),
            ("title", row["title"]),
            ("access", row["access"]),
            ("is_featured", "true" if row.get("featured") else "false"),
        ]
        if row.get("cuid"):
            form.append(("custom_unique_identifier", row["cuid"]))
        for entry in row.get("metadata", []):
            field = entry["field"]
            # Each value/vocabulary pair opens a new element of metadata[field][].
            form.append((f"metadata[{field}][][value]", entry["value"]))
            form.append((f"metadata[{field}][][vocabulary]", entry.get("vocabulary", "")))
        body = self._request("POST", "/api/v1/resources", data=form)
        data = body.get("data", {}) if isinstance(body, dict) else {}
        resource = data.get("update") or data
        if not isinstance(resource, dict) or resource.get("id") is None:
            raise AviaryError(502, "Aviary didn't return the new resource's ID")
        return resource

    def add_media_link(self, resource_id, url, title):
        """Attach a media file that Aviary downloads from ``url``."""
        form = {
            "collection_resource_id": str(resource_id),
            "access": "true",
            "is_360": "false",
            "is_downloadable": "false",
            "media_file_link": url,
            "title": title,
            "display_name": title,
        }
        body = self._request("POST", "/api/v1/media_files", data=form)
        data = body.get("data", {}) if isinstance(body, dict) else {}
        return data if isinstance(data, dict) else {}
