import json
import os
import time
import threading
import hashlib
from pathlib import Path
import requests
from flask import Flask, request, jsonify, render_template, send_from_directory, abort

app = Flask(__name__)
DATA_DIR = "/app/data"
MUSIC_ROOTS = ["/music"]
DB_FILE = os.path.join(DATA_DIR, "client.json")
SERVER_URL = os.environ.get("SERVER_URL", "http://host.docker.internal:40090")
DOWNLOAD_URL = os.environ.get("DOWNLOAD_URL", "")
USERNAME = os.environ.get("USERNAME", "")
HEARTBEAT_INTERVAL = 60

MUSIC_EXTS = {".mp3", ".flac", ".ogg", ".m4a", ".wav", ".wma", ".aac"}

os.makedirs(DATA_DIR, exist_ok=True)


def _load():
    if os.path.exists(DB_FILE):
        with open(DB_FILE) as f:
            data = json.load(f)
        if "selected_folders" in data and "folder_selections" not in data:
            user = data.get("username", "")
            data["folder_selections"] = {user: data.pop("selected_folders")}
            _save(data)
        if "download_url" not in data:
            data["download_url"] = DOWNLOAD_URL
            _save(data)
        return data
    return {"username": USERNAME, "server_url": SERVER_URL, "download_url": DOWNLOAD_URL,
            "files": [], "folder_selections": {}}


def _save(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _md5_first_bytes(filepath, max_bytes=299008):
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        h.update(f.read(max_bytes))
    return h.hexdigest()


def _selected_folders(cfg):
    return cfg.setdefault("folder_selections", {}).get(cfg.get("username", ""), [])


def _is_selected(path, selected):
    path_str = str(path)
    for sel in selected:
        if path_str == sel or path_str.startswith(sel.rstrip("/") + "/"):
            return True
    return False


def _scan_music():
    cfg = _load()
    selected = _selected_folders(cfg)
    files = []
    for root in MUSIC_ROOTS:
        rp = Path(root)
        if not rp.exists():
            continue
        for fpath in rp.rglob("*"):
            if fpath.suffix.lower() not in MUSIC_EXTS:
                continue
            if not _is_selected(fpath.parent, selected):
                continue
            try:
                stat = fpath.stat()
                rel = str(fpath.relative_to(rp))
                md5 = _md5_first_bytes(str(fpath))
                files.append({
                    "filename": f"{root}/{rel}",
                    "size": stat.st_size,
                    "md5": md5,
                    "bitrate": 128,
                    "frequency": 44100,
                    "length": 0,
                })
            except Exception:
                pass
    return files


def _register():
    cfg = _load()
    username = cfg.get("username") or USERNAME
    server = cfg.get("server_url") or SERVER_URL
    if not username:
        return
    try:
        resp = requests.post(f"{server}/api/register",
                             json={"username": username, "download_url": cfg.get("download_url", "")},
                             timeout=10)
        if resp.status_code == 409:
            requests.post(f"{server}/api/heartbeat",
                          json={"username": username, "download_url": cfg.get("download_url", "")},
                          timeout=10)
    except requests.RequestException:
        pass


def _sync():
    cfg = _load()
    username = cfg.get("username") or USERNAME
    server = cfg.get("server_url") or SERVER_URL
    if not username:
        return
    files = _scan_music()
    cfg["files"] = files
    _save(cfg)
    try:
        resp = requests.post(f"{server}/api/users/{username}/files",
                             json={"files": files, "download_url": cfg.get("download_url", "")},
                             timeout=30)
        if resp.status_code == 404:
            _register()
            requests.post(f"{server}/api/users/{username}/files",
                          json={"files": files, "download_url": cfg.get("download_url", "")},
                          timeout=30)
    except requests.RequestException:
        pass


def _heartbeat_loop():
    while True:
        time.sleep(HEARTBEAT_INTERVAL)
        cfg = _load()
        username = cfg.get("username") or USERNAME
        server = cfg.get("server_url") or SERVER_URL
        if not username:
            continue
        try:
            requests.post(f"{server}/api/heartbeat",
                          json={"username": username, "download_url": cfg.get("download_url", "")},
                          timeout=10)
        except requests.RequestException:
            pass


@app.route("/")
def index():
    cfg = _load()
    return render_template("index.html",
                           username=cfg.get("username", ""),
                           server_url=cfg.get("server_url", SERVER_URL),
                           download_url=cfg.get("download_url", DOWNLOAD_URL),
                           files=cfg.get("files", []),
                           music_roots=MUSIC_ROOTS,
                           selected_folders=_selected_folders(cfg))


@app.route("/download/<path:filename>")
def download(filename):
    path = filename.lstrip("/")
    for root in MUSIC_ROOTS:
        rp = Path(root).resolve()
        for candidate in [rp / path, rp / path.lstrip("music").lstrip("/")]:
            full = candidate.resolve()
            if full.exists() and full.is_file() and str(full).startswith(str(rp)):
                cfg = _load()
                selected = _selected_folders(cfg)
                if not selected or _is_selected(full.parent, selected):
                    rel = str(full.relative_to(rp))
                    return send_from_directory(str(rp), rel, as_attachment=True)
    abort(404)


@app.route("/api/config", methods=["GET", "POST"])
def config():
    cfg = _load()
    if request.method == "POST":
        data = request.get_json(force=True)
        if "username" in data:
            cfg["username"] = data["username"].strip()
        if "server_url" in data:
            cfg["server_url"] = data["server_url"].strip().rstrip("/")
        if "download_url" in data:
            cfg["download_url"] = data["download_url"].strip().rstrip("/")
        cfg.setdefault("folder_selections", {}).setdefault(cfg["username"], [])
        _save(cfg)
        threading.Thread(target=_register, daemon=True).start()
        threading.Thread(target=_sync, daemon=True).start()
        return jsonify({"status": "ok"})
    return jsonify(cfg)


@app.route("/api/scan", methods=["POST"])
def scan():
    threading.Thread(target=_sync, daemon=True).start()
    return jsonify({"status": "ok", "message": "Scan started"})


@app.route("/api/status")
def status():
    cfg = _load()
    return jsonify({
        "username": cfg.get("username", ""),
        "server_url": cfg.get("server_url", SERVER_URL),
        "download_url": cfg.get("download_url", DOWNLOAD_URL),
        "file_count": len(cfg.get("files", [])),
        "music_roots": MUSIC_ROOTS,
        "selected_folders": _selected_folders(cfg),
    })


@app.route("/api/browse")
def browse():
    path = request.args.get("path", "/music")
    if not any(path.startswith(r) for r in MUSIC_ROOTS):
        return jsonify({"error": "path outside music roots"}), 400
    p = Path(path)
    if not p.exists() or not p.is_dir():
        return jsonify({"error": "not found"}), 404
    dirs = []
    files = []
    try:
        for entry in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                dirs.append({"name": entry.name, "path": str(entry)})
            elif entry.suffix.lower() in MUSIC_EXTS:
                files.append({"name": entry.name, "path": str(entry)})
    except PermissionError:
        pass
    return jsonify({"current": str(p), "dirs": dirs, "files": files})


@app.route("/api/shared-folders", methods=["GET", "POST"])
def shared_folders():
    cfg = _load()
    if request.method == "POST":
        data = request.get_json(force=True)
        folders = data.get("folders", [])
        valid = []
        for f in folders:
            if any(f.startswith(r) for r in MUSIC_ROOTS) and Path(f).exists():
                valid.append(f)
        username = cfg.get("username", "")
        if username:
            cfg.setdefault("folder_selections", {})[username] = valid
        _save(cfg)
        threading.Thread(target=_sync, daemon=True).start()
        return jsonify({"status": "ok", "count": len(valid)})
    return jsonify(_selected_folders(cfg))


@app.route("/api/logout", methods=["POST"])
def logout():
    cfg = _load()
    username = cfg.get("username")
    server = cfg.get("server_url") or SERVER_URL
    if username:
        try:
            requests.delete(f"{server}/api/users/{username}", timeout=10)
        except requests.RequestException:
            pass
    cfg["username"] = ""
    _save(cfg)
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    _register()
    _sync()
    t = threading.Thread(target=_heartbeat_loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5000, debug=False)
