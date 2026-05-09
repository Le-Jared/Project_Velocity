import os
import sys
import json
import mimetypes

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CLIENTS_FOLDER = "./Clients"
CREDENTIALS    = "credentials.json"
DRIVE_CONFIG   = "drive_config.json"
SCOPES         = ["https://www.googleapis.com/auth/drive"]


def get_drive_folder_id():
    if not os.path.exists(DRIVE_CONFIG):
        print("[ERR]  drive_config.json not found. Set your Drive Folder ID in the dashboard.")
        sys.exit(1)
    with open(DRIVE_CONFIG) as f:
        config = json.load(f)
    folder_id = config.get("root_folder_id", "").strip()
    if not folder_id:
        print("[ERR]  root_folder_id is empty in drive_config.json. Set it in the dashboard.")
        sys.exit(1)
    return folder_id


def get_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_file(CREDENTIALS, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)


def get_shared_drive_id(service, folder_id):
    """Return the Shared Drive ID if the folder lives in one, else None."""
    try:
        meta = service.files().get(
            fileId=folder_id,
            fields="driveId",
            supportsAllDrives=True
        ).execute()
        return meta.get("driveId")
    except Exception:
        return None


def get_or_create_folder(service, name, parent_id, shared_drive_id=None):
    query = (
        f"name='{name}' and mimeType='application/vnd.google-apps.folder'"
        f" and '{parent_id}' in parents and trashed=false"
    )
    list_kwargs = dict(
        q=query,
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    )
    if shared_drive_id:
        list_kwargs["corpora"]  = "drive"
        list_kwargs["driveId"]  = shared_drive_id

    results = service.files().list(**list_kwargs).execute()
    items   = results.get("files", [])
    if items:
        return items[0]["id"]

    meta = {
        "name":     name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents":  [parent_id],
    }
    folder = service.files().create(
        body=meta,
        fields="id",
        supportsAllDrives=True
    ).execute()
    print(f"[OK]   Created folder: {name}")
    return folder["id"]


def file_exists_in_folder(service, filename, folder_id, shared_drive_id=None):
    query = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    list_kwargs = dict(
        q=query,
        fields="files(id)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    )
    if shared_drive_id:
        list_kwargs["corpora"] = "drive"
        list_kwargs["driveId"] = shared_drive_id

    results = service.files().list(**list_kwargs).execute()
    return len(results.get("files", [])) > 0


def upload_file(service, local_path, filename, folder_id):
    from googleapiclient.http import MediaFileUpload
    mime, _ = mimetypes.guess_type(local_path)
    mime     = mime or "application/octet-stream"
    media    = MediaFileUpload(local_path, mimetype=mime, resumable=True)
    meta     = {"name": filename, "parents": [folder_id]}
    service.files().create(
        body=meta,
        media_body=media,
        fields="id",
        supportsAllDrives=True
    ).execute()
    print(f"[OK]   Uploaded: {filename}")


def sync_clients_folder(service, root_folder_id, shared_drive_id):
    print(f"[SCAN] Starting Drive sync → folder ID: {root_folder_id}")
    if shared_drive_id:
        print(f"[INFO] Shared Drive detected → ID: {shared_drive_id}")
    else:
        print(f"[INFO] No Shared Drive detected — using My Drive folder")

    total_uploaded = 0
    total_skipped  = 0

    for client in sorted(os.listdir(CLIENTS_FOLDER)):
        client_path = os.path.join(CLIENTS_FOLDER, client)
        if not os.path.isdir(client_path):
            continue
        client_id = get_or_create_folder(service, client, root_folder_id, shared_drive_id)

        for dirpath, dirnames, filenames in os.walk(client_path):
            rel        = os.path.relpath(dirpath, client_path)
            current_id = client_id
            if rel != ".":
                parts = rel.replace("\\", "/").split("/")
                for part in parts:
                    current_id = get_or_create_folder(service, part, current_id, shared_drive_id)

            for fname in filenames:
                fpath = os.path.join(dirpath, fname)
                if file_exists_in_folder(service, fname, current_id, shared_drive_id):
                    print(f"[SKIP] Already exists: {fname}")
                    total_skipped += 1
                else:
                    try:
                        upload_file(service, fpath, fname, current_id)
                        total_uploaded += 1
                    except Exception as e:
                        print(f"[ERR]  Failed to upload {fname}: {e}")

    print(f"[DONE] Sync complete — {total_uploaded} uploaded, {total_skipped} skipped.")


if __name__ == "__main__":
    if not os.path.exists(CREDENTIALS):
        print("[ERR]  credentials.json not found.")
        sys.exit(1)
    if not os.path.exists(CLIENTS_FOLDER):
        print("[ERR]  Clients/ folder not found — run the invoice sorter first.")
        sys.exit(1)
    try:
        root_folder_id   = get_drive_folder_id()
        service          = get_service()
        shared_drive_id  = get_shared_drive_id(service, root_folder_id)
        sync_clients_folder(service, root_folder_id, shared_drive_id)
    except Exception as e:
        print(f"[ERR]  {e}")
        sys.exit(1)
