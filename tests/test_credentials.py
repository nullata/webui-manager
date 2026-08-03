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

"""The credentials endpoint, including the decrypt-failure signal.

decrypt_secret() returns None both when nothing is stored and when the stored
ciphertext can't be read (the usual cause being SECRET_KEY rotated without
APP_CREDENTIALS_KEY set). The endpoint has to tell those apart, or the UI shows
an empty password field and the user goes hunting for a bug that isn't there.
"""

# Valid base64 Fernet-ish shape, but not encrypted with this install's key.
UNDECRYPTABLE = "gAAAAABm-this-is-not-a-valid-fernet-token"


def test_password_round_trips(client, seed):
    webui_id = seed("Plex", "https://plex.lan", credential_username="plexuser",
                    password="hunter2")
    body = client.post(f"/webuis/{webui_id}/credentials").get_json()
    assert body == {"username": "plexuser", "password": "hunter2", "decrypt_failed": False}


def test_undecryptable_password_is_flagged(client, seed):
    webui_id = seed("Broken", "https://broken.lan", credential_username="admin",
                    credential_password_encrypted=UNDECRYPTABLE)
    body = client.post(f"/webuis/{webui_id}/credentials").get_json()
    assert body["decrypt_failed"] is True
    assert body["password"] == ""
    assert body["username"] == "admin"


def test_no_stored_password_is_not_a_failure(client, seed):
    """The distinction that motivated the flag: nothing stored is not an error."""
    webui_id = seed("UserOnly", "https://useronly.lan", credential_username="justme")
    body = client.post(f"/webuis/{webui_id}/credentials").get_json()
    assert body["decrypt_failed"] is False
    assert body["password"] == ""
    assert body["username"] == "justme"


def test_no_credentials_at_all(client, seed):
    webui_id = seed("Bare", "https://bare.lan")
    body = client.post(f"/webuis/{webui_id}/credentials").get_json()
    assert body == {"username": "", "password": "", "decrypt_failed": False}


def test_credentials_require_a_session(anon_client, admin, seed):
    """`admin` matters: with no users at all, login_required sends you to
    first-run setup instead of the login page."""
    webui_id = seed("Plex", "https://plex.lan", credential_username="u", password="p")
    response = anon_client.post(f"/webuis/{webui_id}/credentials")
    assert response.status_code in (301, 302)
    assert "/login" in response.headers["Location"]


def test_unknown_service_404s(client):
    assert client.post("/webuis/999999/credentials").status_code == 404


def test_credentials_button_only_rendered_when_something_is_stored(client, seed):
    seed("WithCreds", "https://withcreds.lan", credential_username="u", password="p")
    seed("NoCreds", "https://nocreds.lan")
    html = client.get("/dashboard").get_data(as_text=True)
    assert html.count("credentials-btn") == 1
