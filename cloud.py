"""Спецоблако — публичный просмотр файлов, загрузка только через секретную админку.

ВСЁ В ОДНОМ ФАЙЛЕ: шаблоны встроены прямо сюда (не нужна папка templates/),
поэтому для загрузки на GitHub достаточно одного cloud.py.

Запуск:
    python cloud.py                     → http://127.0.0.1:5007

Обязательные переменные окружения (задать в панели Render, НЕ в коде):
    CLOUD_PASS   — пароль секретной админки /admin (без него админка закрыта)
    SECRET_KEY   — ключ подписи сессий (длинная случайная строка)

Необязательно:
    CLOUD_MAX_MB — лимит файла в МБ (по умолчанию 500)
"""
import os, re, io, zipfile, urllib.parse
from datetime import datetime

from flask import (Flask, request, jsonify, render_template_string,
                   send_from_directory, abort, session, redirect, url_for,
                   send_file)

HERE = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(HERE, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or __import__("secrets").token_hex(32)

CLOUD_PASS = os.environ.get("CLOUD_PASS", "")
MAX_MB = int(os.environ.get("CLOUD_MAX_MB", 500))
MAX_BYTES = MAX_MB * 1024 * 1024

ALLOWED = {"txt","md","pdf","png","jpg","jpeg","gif","webp","svg","mp4","webm","mp3","wav",
           "zip","rar","7z","gz","doc","docx","xls","xlsx","ppt","pptx","json","csv","html","css","js"}
IMG_EXTS = {"png","jpg","jpeg","gif","webp","svg","bmp"}


# ================================================================ ШАБЛОНЫ
T_INDEX = r'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Спецоблако</title>
<style>
  :root{--bg:#0b0e14;--panel:#11151d;--line:#1f2632;--txt:#e6ebf2;--mut:#8b94a7;--acc:#3ec6ff}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:radial-gradient(900px 500px at 50% -10%,#12203a 0%,var(--bg) 60%);color:var(--txt);font-family:'Segoe UI',sans-serif;min-height:100vh}
  header{display:flex;align-items:center;justify-content:space-between;padding:16px 26px;border-bottom:1px solid var(--line)}
  .logo{font-weight:800;font-size:20px;color:var(--acc);letter-spacing:.5px}
  .logo small{color:var(--mut);font-weight:400;font-size:12px;margin-left:10px}
  .admin-link{color:var(--mut);font-size:12px;text-decoration:none;border:1px solid var(--line);padding:6px 12px;border-radius:8px}
  .admin-link:hover{color:var(--acc);border-color:var(--acc)}
  main{max-width:1000px;margin:0 auto;padding:24px}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:14px}
  .file{border:1px solid var(--line);border-radius:12px;background:var(--panel);padding:16px;display:flex;flex-direction:column;gap:8px;transition:.15s}
  .file:hover{border-color:var(--acc);transform:translateY(-2px)}
  .file .ico{font-size:34px}
  .file .name{font-size:13px;font-weight:600;word-break:break-all}
  .file .meta{font-size:11px;color:var(--mut)}
  .empty{color:var(--mut);text-align:center;padding:60px;border:1px dashed var(--line);border-radius:14px}
  .f-ext{font-size:10px;color:var(--acc);text-transform:uppercase}
  .download{display:inline-block;margin-top:8px;padding:6px 12px;border-radius:8px;font-size:12px;font-weight:600;
    background:linear-gradient(135deg,#17a2ff,#0b78e8);color:#fff;text-decoration:none;text-align:center}
  .download:hover{filter:brightness(1.1)}
  .lightbox{display:none;position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:50;align-items:center;justify-content:center;flex-direction:column;padding:30px}
  .lightbox.show{display:flex}
  .lightbox img{max-width:92vw;max-height:84vh;border-radius:8px;box-shadow:0 10px 40px rgba(0,0,0,.7)}
  .lightbox .lb-bar{display:flex;align-items:center;gap:14px;margin-top:16px}
  .lb-name{color:#c3cbda;font-family:monospace;font-size:13px;word-break:break-all;max-width:70vw}
  .lb-btn{padding:7px 16px;border-radius:8px;border:none;cursor:pointer;font-size:13px;font-weight:600;
    background:linear-gradient(135deg,#17a2ff,#0b78e8);color:#fff}
  .lb-close{background:rgba(255,255,255,.15);color:#fff;font-size:20px;width:42px;height:42px;border-radius:50%;
    display:grid;place-items:center;cursor:pointer;border:none;position:absolute;top:18px;right:22px}
  .lb-close:hover{background:rgba(255,90,90,.6)}
</style>
</head>
<body>
<header>
  <div class="logo">СПЕЦОБЛАКО<small>публичный просмотр</small></div>
  <a class="admin-link" href="/admin">admin ↝</a>
</header>
<main>
  {% if files %}
  <div class="grid">
    {% for f in files %}
    <div class="file">
      <a class="file-view" href="/f/{{ f.name }}" data-img="{{ '1' if f.ext in IMG_EXTS else '0' }}" data-name="{{ f.name }}" style="text-decoration:none;color:inherit">
        <div class="ico">{% if f.ext in IMG_EXTS %}🖼️{% elif f.ext=='pdf' %}📄{% elif f.ext in ['zip','rar','7z','gz'] %}🗜️{% elif f.ext in ['mp4','webm'] %}🎬{% elif f.ext in ['mp3','wav'] %}🎵{% else %}📁{% endif %}</div>
        <div class="name">{{ f.name }}</div>
        <div class="meta">{{ "%.2f"|format(f.size/1024) }} КБ · {{ f.mtime }}</div>
        <div class="f-ext">{{ f.ext or 'file' }}</div>
      </a>
      <a class="download" href="/dl/{{ f.name }}">⬇ Скачать</a>
    </div>
    {% endfor %}
  </div>
  {% else %}
  <div class="empty">Облако пусто. Файлы пока никто не загрузил.</div>
  {% endif %}
</main>
<div class="lightbox" id="lightbox">
  <button class="lb-close" id="lbClose" title="Закрыть">✕</button>
  <img id="lbImg" alt="">
  <div class="lb-bar"><span class="lb-name" id="lbName"></span><a class="lb-btn" id="lbDl" href="#">⬇ Скачать</a></div>
</div>
<script>
  const lb=document.getElementById('lightbox');
  const lbImg=document.getElementById('lbImg'), lbName=document.getElementById('lbName');
  const lbDl=document.getElementById('lbDl'), lbClose=document.getElementById('lbClose');
  function openLb(src,n,dl){lbImg.src=src;lbName.textContent=n;lbDl.href=dl;lb.classList.add('show');}
  function closeLb(){lb.classList.remove('show');lbImg.src='';}
  lbClose.onclick=closeLb;
  lb.onclick=function(e){if(e.target===lb)closeLb();};
  document.addEventListener('keydown',function(e){if(e.key==='Escape')closeLb();});
  document.querySelectorAll('.file-view').forEach(function(a){
    a.addEventListener('click',function(e){if(a.dataset.img==='1'){e.preventDefault();openLb(a.href,a.dataset.name,'/dl/'+a.dataset.name);}});
  });
</script>
</body>
</html>'''

T_LOGIN = r'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Спецоблако — вход</title>
<style>
  :root{--bg:#0b0e14;--panel:#11151d;--line:#1f2632;--txt:#e6ebf2;--mut:#8b94a7;--acc:#3ec6ff;--err:#ff7a7a}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:radial-gradient(800px 400px at 50% 15%,#12203a 0%,var(--bg) 60%);color:var(--txt);font-family:'Segoe UI',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center}
  .card{width:340px;border:1px solid var(--line);border-radius:16px;background:var(--panel);padding:30px}
  h1{font-size:20px;color:var(--acc);margin-bottom:22px}
  .field{display:flex;flex-direction:column;gap:6px;margin-bottom:16px}
  .field label{font-size:12.5px;color:var(--mut)}
  .field input{background:#0a0f18;border:1px solid var(--line);border-radius:9px;color:var(--txt);padding:11px 13px;font-size:14px;outline:none}
  .field input:focus{border-color:var(--acc)}
  .btn{width:100%;background:linear-gradient(135deg,#17a2ff,#0b78e8);border:none;color:#fff;padding:12px;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer}
  .btn:hover{filter:brightness(1.1)}
  .err{color:var(--err);font-size:12.5px;margin-bottom:12px;min-height:16px}
</style>
</head>
<body>
<div class="card">
  <h1>Спецоблако · вход</h1>
  <div class="err">{{ error or '' }}</div>
  <form method="POST" action="/admin">
    <div class="field"><label>Пароль</label><input type="password" name="password" autofocus required></div>
    <button class="btn" type="submit">Войти</button>
  </form>
</div>
</body>
</html>'''

T_ADMIN = r'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Спецоблако — панель загрузки</title>
<style>
  :root{--bg:#0b0e14;--panel:#11151d;--line:#1f2632;--txt:#e6ebf2;--mut:#8b94a7;--acc:#3ec6ff;--ok:#41e08a}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:radial-gradient(900px 500px at 50% -10%,#12203a 0%,var(--bg) 60%);color:var(--txt);font-family:'Segoe UI',sans-serif;min-height:100vh}
  header{display:flex;align-items:center;justify-content:space-between;padding:14px 26px;border-bottom:1px solid var(--line)}
  .logo{font-weight:800;color:var(--acc)}
  .btn{border:1px solid var(--line);background:#0a0f18;color:var(--txt);padding:8px 14px;border-radius:9px;cursor:pointer;font-size:13px}
  .btn:hover{border-color:var(--acc);color:var(--acc)}
  main{max-width:800px;margin:0 auto;padding:24px}
  .upload-box{border:1px dashed var(--line);border-radius:14px;padding:30px;text-align:center;background:var(--panel)}
  #drop{border:2px dashed #2a3542;border-radius:12px;padding:40px;cursor:pointer;transition:.15s}
  #drop:hover{border-color:var(--acc);background:rgba(62,198,255,.03)}
  #drop.drag{border-color:var(--acc);background:rgba(62,198,255,.08)}
  .input-row{display:flex;gap:10px;justify-content:center;margin-top:16px;align-items:center}
  .btn.primary{background:linear-gradient(135deg,#17a2ff,#0b78e8);border:none;color:#fff;font-weight:600}
  .status{color:var(--ok);font-size:13px;margin-top:12px;min-height:18px}
  .f-list{margin-top:24px}
  .f-item{display:flex;align-items:center;justify-content:space-between;border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin-bottom:8px;background:var(--panel)}
  .f-item .name{font-weight:600;font-size:14px}
  .f-item .meta{font-size:12px;color:var(--mut);margin-top:2px}
  .f-item a{color:var(--acc);text-decoration:none;font-size:12.5px}
  .del-btn{background:rgba(255,90,90,.12);border-color:rgba(255,90,90,.4);color:#ff9a9a;font-size:12px}
  .del-btn:hover{border-color:#ff7a7a;color:#ff7a7a}
  .lock{color:var(--mut);font-size:12px;text-align:center;margin-top:18px;padding-top:14px;border-top:1px solid var(--line)}
</style>
</head>
<body>
<header>
  <div class="logo">СПЕЦОБЛАКО · панель загрузки</div>
  <div style="display:flex;gap:8px;align-items:center">
    <a class="btn" href="/" style="text-decoration:none">↗ просмотр</a>
    <form method="POST" action="/admin/logout" style="margin:0"><button class="btn" type="submit">Выйти</button></form>
  </div>
</header>
<main>
  <div class="upload-box">
    <div id="drop"><div style="font-size:40px">📤</div>
      <div style="margin-top:10px;color:var(--mut)">Перетащи файлы сюда или кликни, чтобы выбрать</div></div>
    <div class="input-row"><input type="file" id="fileInput" multiple><button class="btn primary" id="upBtn">Загрузить</button></div>
    <div class="status" id="status"></div>
    <div class="input-row" style="margin-top:18px">
      <button class="btn primary" id="backupBtn" type="button">📦 Скачать бэкап всех фото</button>
      <span style="color:var(--mut);font-size:11.5px">архив на лету, НЕ хранится на сервере</span>
    </div>
  </div>
  <div class="f-list" id="fileList">
    {% for f in files %}
    <div class="f-item">
      <div>
        <div class="name">{{ f.name }}</div>
        <div class="meta">{{ "%.2f"|format(f.size/1024) }} КБ · {{ f.mtime }}</div>
        <a href="/f/{{ f.name }}" target="_blank">открыть ↗</a>
      </div>
      <button class="btn del-btn" onclick="delFile('{{ f.name }}')">🗑 Удалить</button>
    </div>
    {% endfor %}
  </div>
  <div class="lock">🔒 Файлы защищены от удаления навечно.</div>
</main>
<script>
  const drop=document.getElementById('drop'), inp=document.getElementById('fileInput'), status=document.getElementById('status');
  drop.onclick=function(){inp.click();};
  drop.ondragover=function(e){e.preventDefault();drop.classList.add('drag');};
  drop.ondragleave=function(){drop.classList.remove('drag');};
  drop.ondrop=function(e){e.preventDefault();drop.classList.remove('drag');upload(e.dataTransfer.files);};
  inp.onchange=function(){upload(inp.files);};
  async function upload(files){
    status.textContent='Загрузка...'; let ok=0, fail=0;
    for(const file of files){
      const fd=new FormData(); fd.append('file', file);
      try{
        const r=await fetch('/api/admin/upload',{method:'POST',body:fd});
        const d=await r.json();
        if(r.ok && d.ok){ ok++; } else { fail++; status.textContent='Ошибка: '+(d.error||'неизвестна'); }
      }catch(e){ fail++; }
    }
    if(ok) status.textContent='✅ Загружено: '+ok+(fail? ' · ошибок: '+fail:'');
    setTimeout(function(){location.reload();}, 700);
  }
  document.getElementById('backupBtn').onclick=async function(){
    const btn=document.getElementById('backupBtn');
    btn.disabled=true; btn.textContent='Формирую архив...';
    try{
      const r=await fetch('/api/admin/backup');
      if(!r.ok){ const d=await r.json().catch(function(){return {};}); status.textContent='Ошибка: '+(d.error||'нет фото'); btn.disabled=false; btn.textContent='📦 Скачать бэкап всех фото'; return; }
      const blob=await r.blob();
      const url=URL.createObjectURL(blob);
      const a=document.createElement('a');
      const m=(r.headers.get('Content-Disposition')||'').match(/filename="?([^";]+)"?/);
      a.href=url; a.download=m?m[1]:'backup_photos.zip';
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(url);
      status.textContent='✅ Бэкап скачан. На сервере ничего не осталось.';
    }catch(e){ status.textContent='Ошибка: '+e.message; }
    finally { btn.disabled=false; btn.textContent='📦 Скачать бэкап всех фото'; }
  };
  async function delFile(name){
    if(!confirm('Удалить файл «'+name+'»?')) return;
    try{
      const r=await fetch('/api/admin/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name})});
      const d=await r.json();
      if(r.ok && d.ok){ status.textContent='🗑 Удалено: '+name; setTimeout(function(){location.reload();},600); }
      else { alert('Ошибка: '+(d.error||'не удалось')); }
    }catch(e){ alert('Ошибка: '+e.message); }
  }
</script>
</body>
</html>'''

T_404 = '''<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><title>404</title>
<style>body{background:#0b0e14;color:#8b94a7;font-family:monospace;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}div{text-align:center}big{font-size:60px;color:#3ec6ff}a{color:#3ec6ff;text-decoration:none}</style>
</head><body><div><big>404</big><p>Файл не найден</p><a href="/">← на главную</a></div></body></html>'''


# ================================================================ ПУБЛИЧНОЕ
@app.route("/")
def index():
    files = []
    if os.path.isdir(UPLOAD_DIR):
        for name in os.listdir(UPLOAD_DIR):
            p = os.path.join(UPLOAD_DIR, name)
            if os.path.isfile(p):
                files.append({
                    "name": name,
                    "size": os.path.getsize(p),
                    "mtime": datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M"),
                    "ext": name.rsplit(".",1)[-1].lower() if "." in name else "",
                })
    files.sort(key=lambda f: f["mtime"], reverse=True)
    return render_template_string(T_INDEX, files=files, IMG_EXTS=IMG_EXTS)


@app.route("/f/<path:name>")
def serve_file(name):
    safe = os.path.basename(name)
    if not os.path.isfile(os.path.join(UPLOAD_DIR, safe)):
        abort(404)
    return send_from_directory(UPLOAD_DIR, safe)


@app.route("/dl/<path:name>")
def download_file(name):
    safe = os.path.basename(name)
    if not os.path.isfile(os.path.join(UPLOAD_DIR, safe)):
        abort(404)
    return send_from_directory(UPLOAD_DIR, safe, as_attachment=True)


@app.route("/api/files")
def api_files():
    out = []
    if os.path.isdir(UPLOAD_DIR):
        for name in os.listdir(UPLOAD_DIR):
            p = os.path.join(UPLOAD_DIR, name)
            if os.path.isfile(p):
                out.append({"name": name, "size": os.path.getsize(p),
                            "url": "/f/" + name, "dl": "/dl/" + name})
    return jsonify(out)


# ================================================================ АДМИНКА
def _filelist():
    out = []
    if os.path.isdir(UPLOAD_DIR):
        for name in os.listdir(UPLOAD_DIR):
            p = os.path.join(UPLOAD_DIR, name)
            if os.path.isfile(p):
                out.append({"name": name, "size": os.path.getsize(p),
                            "mtime": datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M")})
    out.sort(key=lambda f: f["mtime"], reverse=True)
    return out


@app.route("/admin", methods=["GET", "POST"])
def admin():
    if not CLOUD_PASS:
        return render_template_string(T_LOGIN, error="Пароль не настроен. Задайте CLOUD_PASS в переменных окружения."), 503
    if session.get("cloud_auth"):
        return render_template_string(T_ADMIN, files=_filelist())
    if request.method == "POST":
        pw = (request.form.get("password") or "").strip()
        if pw == CLOUD_PASS:
            session["cloud_auth"] = True
            return render_template_string(T_ADMIN, files=_filelist())
        return render_template_string(T_LOGIN, error="Неверный пароль")
    return render_template_string(T_LOGIN, error=None)


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.clear()
    return redirect(url_for("admin"))


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
    p = os.path.join(UPLOAD_DIR, name)
    if os.path.exists(p):
        base, dot, ext = name.rpartition(".")
        i = 1
        while os.path.exists(os.path.join(UPLOAD_DIR, f"{base}__{i}.{ext}" if dot else f"{base}__{i}")):
            i += 1
        name = f"{base}__{i}.{ext}" if dot else f"{base}__{i}"
    f.save(os.path.join(UPLOAD_DIR, name))
    return jsonify({"ok": True, "name": name, "note": "файл защищён от удаления"})


@app.route("/api/admin/delete", methods=["POST"])
def admin_delete():
    """Удаление файла — ТОЛЬКО для авторизованного админа."""
    if not session.get("cloud_auth"):
        return jsonify({"error": "не авторизован"}), 401
    data = request.get_json(silent=True) or {}
    name = os.path.basename((data.get("name") or "").strip())
    if not name:
        return jsonify({"error": "нет имени файла"}), 400
    p = os.path.join(UPLOAD_DIR, name)
    if not os.path.isfile(p):
        return jsonify({"error": "файл не найден"}), 404
    os.remove(p)
    return jsonify({"ok": True, "deleted": name})


@app.route("/api/admin/backup", methods=["GET"])
def admin_backup():
    if not session.get("cloud_auth"):
        return jsonify({"error": "не авторизован"}), 401
    files = []
    if os.path.isdir(UPLOAD_DIR):
        for name in os.listdir(UPLOAD_DIR):
            p = os.path.join(UPLOAD_DIR, name)
            if os.path.isfile(p) and name.rsplit(".",1)[-1].lower() in IMG_EXTS:
                files.append((name, p))
    if not files:
        return jsonify({"error": "нет фото для бэкапа"}), 404
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, path in files:
            zf.write(path, arcname=name)
    buf.seek(0)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return send_file(buf, as_attachment=True, download_name=f"backup_photos_{ts}.zip",
                     mimetype="application/zip")


@app.errorhandler(404)
def not_found(e):
    return render_template_string(T_404)


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
