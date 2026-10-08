"""Спецоблако — публичный просмотр файлов, загрузка только через секретную админку.

Запуск:
    python cloud.py                     → http://127.0.0.1:5007

Обязательные переменные окружения (задать в панели Render, НЕ в коде):
    CLOUD_PASS   — пароль секретной админки /admin (без него админка закрыта)
    SECRET_KEY   — ключ подписи сессий (длинная случайная строка)

Необязательно:
    CLOUD_MAX_MB — лимит файла в МБ (по умолчанию 500)
"""
import os, re, time, shutil, logging, io, zipfile
from datetime import datetime

from flask import Flask, request, jsonify, render_template, send_from_directory, abort, session, redirect, url_for, send_file

HERE = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(HERE, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
# СЕКРЕТНЫЙ КЛЮЧ — только из env. Без него сессии не работают (защита от дефолта в коде).
app.secret_key = os.environ.get("SECRET_KEY") or __import__("secrets").token_hex(32)

# Пароль админки — ТОЛЬКО из env. Если не задан — админка недоступна.
CLOUD_PASS = os.environ.get("CLOUD_PASS", "")
MAX_MB = int(os.environ.get("CLOUD_MAX_MB", 500))
MAX_BYTES = MAX_MB * 1024 * 1024

ALLOWED = {"txt","md","pdf","png","jpg","jpeg","gif","webp","svg","mp4","webm","mp3","wav",
           "zip","rar","7z","gz","doc","docx","xls","xlsx","ppt","pptx","json","csv","html","css","js"}


# ------------------------------------------------- public: просмотр --
@app.route("/")
def index():
    files = []
    for name in sorted(os.listdir(UPLOAD_DIR), key=lambda n: os.path.getmtime(os.path.join(UPLOAD_DIR,n)), reverse=True):
        p = os.path.join(UPLOAD_DIR, name)
        if os.path.isfile(p):
            files.append({
                "name": name,
                "size": os.path.getsize(p),
                "mtime": datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M"),
                "ext": name.rsplit(".",1)[-1].lower() if "." in name else "",
            })
    return render_template("index.html", files=files)


@app.route("/f/<path:name>")
def serve_file(name):
    safe = os.path.basename(name)
    p = os.path.join(UPLOAD_DIR, safe)
    if not os.path.isfile(p):
        abort(404)
    return send_from_directory(UPLOAD_DIR, safe)


@app.route("/dl/<path:name>")
def download_file(name):
    safe = os.path.basename(name)
    p = os.path.join(UPLOAD_DIR, safe)
    if not os.path.isfile(p):
        abort(404)
    return send_from_directory(UPLOAD_DIR, safe, as_attachment=True)


@app.route("/api/files")
def api_files():
    files = []
    for name in sorted(os.listdir(UPLOAD_DIR)):
        p = os.path.join(UPLOAD_DIR, name)
        if os.path.isfile(p):
            files.append({"name": name, "size": os.path.getsize(p),
                          "url": "/f/" + name, "dl": "/dl/" + name})
    return jsonify(files)


# ------------------------------------------------- секретная админка --
@app.route("/admin", methods=["GET", "POST"])
def admin():
    # если пароль не задан в env — админка физически закрыта
    if not CLOUD_PASS:
        return render_template("admin_login.html", error="Пароль не настроен. Задайте CLOUD_PASS в переменных окружения."), 503
    # уже вошёл
    if session.get("cloud_auth"):
        return render_template("admin.html", files=_filelist())
    if request.method == "POST":
        pw = (request.form.get("password") or "").strip()
        if pw == CLOUD_PASS:
            session["cloud_auth"] = True
            return render_template("admin.html", files=_filelist())
        return render_template("admin_login.html", error="Неверный пароль")
    return render_template("admin_login.html", error=None)


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.clear()
    return redirect(url_for("admin"))


def _filelist():
    out = []
    for name in sorted(os.listdir(UPLOAD_DIR)):
        p = os.path.join(UPLOAD_DIR, name)
        if os.path.isfile(p):
            out.append({"name": name,
                        "size": os.path.getsize(p),
                        "mtime": datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M")})
    return out


@app.route("/api/admin/upload", methods=["POST"])
def admin_upload():
    if not session.get("cloud_auth"):
        return jsonify({"error": "не авторизован"}), 401
    if "file" not in request.files:
        return jsonify({"error": "нет файла"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "нет имени"}), 400
    name = os.path.basename(f.filename)
    if "." in name and name.rsplit(".",1)[-1].lower() not in ALLOWED:
        return jsonify({"error": f"тип не разрешён. Разрешены: {', '.join(sorted(ALLOWED))}"}), 400
    # файлы в этом облаке НЕЛЬЗЯ удалить — поэтому перезапись существующего запрещена:
    # чтобы ничего не потерять, при совпадении имени добавляем суффикс.
    p = os.path.join(UPLOAD_DIR, name)
    if os.path.exists(p):
        base, dot, ext = name.rpartition(".")
        i = 1
        while os.path.exists(os.path.join(UPLOAD_DIR, f"{base}__{i}.{ext}" if dot else f"{base}__{i}")):
            i += 1
        name = f"{base}__{i}.{ext}" if dot else f"{base}__{i}"
    f.save(os.path.join(UPLOAD_DIR, name))
    return jsonify({"ok": True, "name": name, "note": "файл защищён от удаления"})


@app.route("/api/admin/backup", methods=["GET"])
def admin_backup():
    """Создаёт ZIP всех фото «на лету» в памяти и отдаёт его.
    НИЧЕГО не сохраняется на сервере — архив не занимает память/диск после отправки."""
    if not session.get("cloud_auth"):
        return jsonify({"error": "не авторизован"}), 401
    img_exts = {"png","jpg","jpeg","gif","webp","svg","bmp"}
    files = []
    if os.path.isdir(UPLOAD_DIR):
        for name in os.listdir(UPLOAD_DIR):
            p = os.path.join(UPLOAD_DIR, name)
            if os.path.isfile(p) and name.rsplit(".",1)[-1].lower() in img_exts:
                files.append((name, p))
    if not files:
        return jsonify({"error": "нет фото для бэкапа"}), 404
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, path in files:
            zf.write(path, arcname=name)
    buf.seek(0)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return send_file(buf, as_attachment=True,
                     download_name=f"backup_photos_{ts}.zip",
                     mimetype="application/zip")


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html") if os.path.exists(os.path.join(HERE,"templates","404.html")) else ("404", 404)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 5007)))
    ap.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    a = ap.parse_args()
    try:
        print("\n  Спецоблако  ->  http://%s:%d  | просмотр: /  | админка: /admin \n" % (a.host, a.port))
    except Exception:
        pass
    app.run(host=a.host, port=a.port, threaded=True, debug=False)