import os
import sys
import json
import mimetypes

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CLIENTS_FOLDER = "./Clients"
CREDENTIALS = "credentials.json"
TOKEN_FILE = "token.json"
DRIVE_CONFIG = "drive_config.json"
SCOPES = ["https://www.googleapis.com/auth/drive"]

folder_cache = {}
file_cache = {}


def drive_query_escape(value):
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def get_drive_folder_id():
    if not os.path.exists(DRIVE_CONFIG):
        print("[ERR]  drive_config.json not found. Set your Drive Folder ID in the dashboard.")
        sys.exit(1)

    with open(DRIVE_CONFIG, encoding="utf-8") as f:
        config = json.load(f)

    folder_id = str(config.get("root_folder_id", "")).strip()

    if not folder_id:
        print("[ERR]  root_folder_id is empty in drive_config.json. Set it in the dashboard.")
        sys.exit(1)

    return folder_id


def is_service_account(creds_path):
    try:
        with open(creds_path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("type") == "service_account"
    except Exception:
        return False


def get_service():
    from googleapiclient.discovery import build

    if is_service_account(CREDENTIALS):
        print("[AUTH] Detected: Service Account")
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_file(
            CREDENTIALS,
            scopes=SCOPES,
        )

        return build("drive", "v3", credentials=creds, cache_discovery=False)

    print("[AUTH] Detected: OAuth 2.0")
    return get_oauth_service()


def get_oauth_service():
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("[AUTH] Refreshing OAuth token...")
            creds.refresh(Request())
        else:
            print("[AUTH] Opening browser for Google sign-in...")
            print("[AUTH] Sign in with the Google account that owns or can access the target Drive folder.")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS, SCOPES)
            creds = flow.run_local_server(port=0, open_browser=True)

        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

        print(f"[AUTH] Token saved to {TOKEN_FILE}")

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def get_root_metadata(service, folder_id):
    return service.files().get(
        fileId=folder_id,
        fields="id, name, mimeType, driveId",
        supportsAllDrives=True,
    ).execute()


def get_shared_drive_id(service, folder_id):
    try:
        meta = get_root_metadata(service, folder_id)

        if meta.get("mimeType") != "application/vnd.google-apps.folder":
            print("[ERR]  root_folder_id is not a Google Drive folder.")
            sys.exit(1)

        print(f"[INFO] Target folder: {meta.get('name')}")

        return meta.get("driveId")

    except Exception as e:
        print(f"[ERR]  Cannot access target Drive folder: {e}")
        print("[ERR]  Check folder ID and permissions.")
        sys.exit(1)


def list_all_files(service, query, fields, shared_drive_id=None):
    items = []
    page_token = None

    while True:
        kwargs = {
            "q": query,
            "fields": f"nextPageToken, files({fields})",
            "pageSize": 1000,
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
            "pageToken": page_token,
        }

        if shared_drive_id:
            kwargs["corpora"] = "drive"
            kwargs["driveId"] = shared_drive_id
        else:
            kwargs["corpora"] = "user"

        response = service.files().list(**kwargs).execute()
        items.extend(response.get("files", []))
        page_token = response.get("nextPageToken")

        if not page_token:
            break

    return items


def load_child_folders(service, parent_id, shared_drive_id=None):
    cache_key = ("folders", parent_id)

    if cache_key in folder_cache:
        return folder_cache[cache_key]

    query = (
        f"'{parent_id}' in parents "
        f"and mimeType='application/vnd.google-apps.folder' "
        f"and trashed=false"
    )

    items = list_all_files(
        service=service,
        query=query,
        fields="id, name",
        shared_drive_id=shared_drive_id,
    )

    mapping = {item["name"]: item["id"] for item in items}
    folder_cache[cache_key] = mapping

    return mapping


def get_or_create_folder(service, name, parent_id, shared_drive_id=None):
    folders = load_child_folders(service, parent_id, shared_drive_id)

    if name in folders:
        return folders[name]

    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }

    folder = service.files().create(
        body=metadata,
        fields="id",
        supportsAllDrives=True,
    ).execute()

    folder_id = folder["id"]
    folders[name] = folder_id

    print(f"[OK]   Created folder: {name}")

    return folder_id


def load_existing_files(service, folder_id, shared_drive_id=None):
    cache_key = ("files", folder_id)

    if cache_key in file_cache:
        return file_cache[cache_key]

    query = (
        f"'{folder_id}' in parents "
        f"and mimeType!='application/vnd.google-apps.folder' "
        f"and trashed=false"
    )

    items = list_all_files(
        service=service,
        query=query,
        fields="id, name",
        shared_drive_id=shared_drive_id,
    )

    names = {item["name"] for item in items}
    file_cache[cache_key] = names

    return names


def upload_file(service, local_path, filename, folder_id):
    from googleapiclient.http import MediaFileUpload

    mime, _ = mimetypes.guess_type(local_path)
    mime = mime or "application/octet-stream"

    media = MediaFileUpload(
        local_path,
        mimetype=mime,
        resumable=True,
    )

    metadata = {
        "name": filename,
        "parents": [folder_id],
    }

    service.files().create(
        body=metadata,
        media_body=media,
        fields="id",
        supportsAllDrives=True,
    ).execute()

    file_cache.setdefault(("files", folder_id), set()).add(filename)

    print(f"[OK]   Uploaded: {filename}")


def clients_folder_has_files():
    if not os.path.exists(CLIENTS_FOLDER):
        return False

    for _, _, files in os.walk(CLIENTS_FOLDER):
        if files:
            return True

    return False


def count_local_files():
    total = 0

    for _, _, files in os.walk(CLIENTS_FOLDER):
        total += len(files)

    return total


def sync_clients_folder(service, root_folder_id, shared_drive_id):
    print(f"[SCAN] Starting Drive sync → folder ID: {root_folder_id}")

    if shared_drive_id:
        print(f"[INFO] Shared Drive detected → ID: {shared_drive_id}")
    else:
        print("[INFO] My Drive folder")

    total_uploaded = 0
    total_skipped = 0
    total_errors = 0
    total_local = count_local_files()

    print(f"[SCAN] Local files found: {total_local}")

    for client in sorted(os.listdir(CLIENTS_FOLDER)):
        client_path = os.path.join(CLIENTS_FOLDER, client)

        if not os.path.isdir(client_path):
            continue

        client_id = get_or_create_folder(
            service=service,
            name=client,
            parent_id=root_folder_id,
            shared_drive_id=shared_drive_id,
        )

        for dirpath, _, filenames in os.walk(client_path):
            rel = os.path.relpath(dirpath, client_path)
            current_id = client_id

            if rel != ".":
                for part in rel.replace("\\", "/").split("/"):
                    current_id = get_or_create_folder(
                        service=service,
                        name=part,
                        parent_id=current_id,
                        shared_drive_id=shared_drive_id,
                    )

            existing_files = load_existing_files(
                service=service,
                folder_id=current_id,
                shared_drive_id=shared_drive_id,
            )

            for filename in sorted(filenames):
                local_path = os.path.join(dirpath, filename)

                if not os.path.isfile(local_path):
                    continue

                if filename in existing_files:
                    print(f"[SKIP] Already exists: {filename}")
                    total_skipped += 1
                    continue

                try:
                    upload_file(service, local_path, filename, current_id)
                    total_uploaded += 1
                except Exception as e:
                    print(f"[ERR]  Failed to upload {filename}: {e}")
                    total_errors += 1

    print(f"[DONE] Sync complete — {total_uploaded} uploaded, {total_skipped} skipped, {total_errors} error(s).")

    if total_errors:
        sys.exit(1)


if __name__ == "__main__":
    if not os.path.exists(CREDENTIALS):
        print("[ERR]  credentials.json not found.")
        sys.exit(1)

    if not os.path.exists(CLIENTS_FOLDER):
        print("[ERR]  Clients/ folder not found — run the invoice sorter first.")
        sys.exit(1)

    if not clients_folder_has_files():
        print("[ERR]  Clients/ folder is empty — run the invoice sorter first.")
        sys.exit(1)

    try:
        root_folder_id = get_drive_folder_id()
        service = get_service()
        shared_drive_id = get_shared_drive_id(service, root_folder_id)

        sync_clients_folder(
            service=service,
            root_folder_id=root_folder_id,
            shared_drive_id=shared_drive_id,
        )

    except KeyboardInterrupt:
        print("[ERR]  Sync cancelled by user.")
        sys.exit(1)

    except Exception as e:
        print(f"[ERR]  {e}")
        sys.exit(1)
