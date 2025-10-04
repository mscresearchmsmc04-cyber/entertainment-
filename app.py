# Full Colab-ready app: register/login, admin upload/delete, cloudflared tunnel
# Paste the whole cell into Google Colab and run.

# Install dependencies & cloudflared (if not present)
import os, sys, subprocess, time, random, threading
from pathlib import Path

# install python deps (Flask is preinstalled in Colab but we ensure)
!pip install -q flask

# Install cloudflared .deb if cloudflared is not available
def install_cloudflared_if_needed():
    try:
        subprocess.run(["cloudflared","--version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("cloudflared already installed")
        return True
    except Exception:
        print("Installing cloudflared...")
        deb_url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb"
        fn = "cloudflared-linux-amd64.deb"
        # Download .deb
        subprocess.run(["wget","-q",deb_url,"-O",fn], check=True)
        # Install
        proc = subprocess.run(["dpkg","-i",fn], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0:
            # fix deps
            subprocess.run(["apt-get","-f","install","-y"], check=True)
        print("cloudflared installed")
        return True

install_cloudflared_if_needed()

# ---------- Flask app ----------
from flask import Flask, request, render_template_string, session, redirect, url_for, send_from_directory, flash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "colab_secret_key_for_demo"  # change for production!

# Storage
BASE_DIR = Path("/content/uploads_demo")
RESEARCH = BASE_DIR / "research"
VIDEOS = BASE_DIR / "videos"
IMAGES = BASE_DIR / "images"
for d in (RESEARCH, VIDEOS, IMAGES):
    d.mkdir(parents=True, exist_ok=True)

# In-memory users (demo). Pre-create admin
users = {"admin":"admin123"}

# Allowed extensions
ALLOWED_RESEARCH = {".pdf"}
ALLOWED_VIDEOS = {".mp4", ".webm", ".ogg", ".mov", ".avi"}
ALLOWED_IMAGES = {".png", ".jpg", ".jpeg", ".gif"}

# ---------- Templates ----------
# keep them here to be easy to paste/run
layout_css = """
<style>
  body { font-family: Arial, sans-serif; background: linear-gradient(135deg,#f6f9fc,#e9f1ff); margin:0; padding:20px; }
  .top { text-align:center; margin-bottom:20px; }
  .card-row { display:flex; gap:16px; justify-content:center; flex-wrap:wrap; }
  .card { width:220px; border-radius:12px; padding:16px; color:white; box-shadow:0 4px 12px rgba(0,0,0,0.12); text-align:center; text-decoration:none; }
  .videos { background:#3498db; }
  .research { background:#e67e22; }
  .images { background:#27ae60; }
  .admin { background:#8e44ad; }
  .logout { margin-top:18px; display:inline-block; color:#c0392b; }
  /* Grid for images */
  .img-grid { display:flex; flex-wrap:wrap; gap:12px; justify-content:center; }
  .img-grid img { width:180px; height:auto; border-radius:8px; box-shadow:0 2px 6px rgba(0,0,0,0.12); }
  /* video thumbnails */
  .video-item { margin-bottom:12px; }
  .file-list a { display:block; margin:6px 0; color:#063; text-decoration:none; }
  .admin-controls { margin-top:10px; }
  .btn { padding:8px 12px; border-radius:6px; border:none; cursor:pointer; }
  .btn-danger { background:#c0392b; color:white; }
  .btn-primary { background:#2980b9; color:white; }
  .small { font-size:0.9em; color:#222; }
  .msg { text-align:center; color:green; }
</style>
"""

home_page = layout_css + """
<div class="top">
  <h1>EduPortal Demo</h1>
  <p class="small">Register or login. Admin can upload/delete files.</p>
</div>
<div style="text-align:center;">
  <a href="/register" class="btn btn-primary">Register</a>
  &nbsp;
  <a href="/login" class="btn btn-primary">Login</a>
</div>
"""

register_page = layout_css + """
<div style="max-width:420px;margin:30px auto;background:white;padding:20px;border-radius:10px;">
  <h2 style="text-align:center;color:#16a085;">Register</h2>
  <form method="post">
    <input name="username" placeholder="username" required style="width:100%;padding:10px;margin:8px 0;">
    <input name="password" type="password" placeholder="password" required style="width:100%;padding:10px;margin:8px 0;">
    <div style="text-align:center;">
      <button type="submit" class="btn btn-primary">Create account</button>
    </div>
  </form>
  <p style="text-align:center;margin-top:12px;"><a href='/login'>Already have account? Login</a></p>
</div>
"""

login_page = layout_css + """
<div style="max-width:420px;margin:30px auto;background:white;padding:20px;border-radius:10px;">
  <h2 style="text-align:center;color:#2980b9;">Login</h2>
  <form method="post">
    <input name="username" placeholder="username" required style="width:100%;padding:10px;margin:8px 0;">
    <input name="password" type="password" placeholder="password" required style="width:100%;padding:10px;margin:8px 0;">
    <div style="text-align:center;">
      <button type="submit" class="btn btn-primary">Login</button>
    </div>
  </form>
  <p style="text-align:center;margin-top:12px;"><a href='/register'>Create account</a></p>
</div>
"""

dashboard_template = layout_css + """
<div class="top">
  <h2>Welcome, {{username}}</h2>
  <p class="small">Dashboard: View content. Admin can upload/delete.</p>
</div>

<div class="card-row">
  <div class="card videos">
    <h3>🎥 Videos</h3>
    <div style="margin-top:10px;">
      {% if videos %}
        {% for v in videos %}
          <div class="video-item">
            <video width="200" controls><source src="{{v}}" type="video/mp4">Your browser does not support video tag.</video><br>
            {% if is_admin %}
              <form method="post" action="/delete/videos" style="display:inline;">
                <input type="hidden" name="filename" value="{{v.split('/')[-1]}}">
                <button class="btn btn-danger" type="submit">Delete</button>
              </form>
            {% endif %}
          </div>
        {% endfor %}
      {% else %}
        <p class="small">No videos yet</p>
      {% endif %}
    </div>
  </div>

  <div class="card research">
    <h3>📚 Research Papers</h3>
    <div class="file-list" style="margin-top:10px;">
      {% if research %}
        {% for r in research %}
          <a href="{{r}}" target="_blank">{{r.split('/')[-1]}}</a>
          {% if is_admin %}
            <form method="post" action="/delete/research" style="display:inline;">
              <input type="hidden" name="filename" value="{{r.split('/')[-1]}}">
              <button class="btn btn-danger" type="submit">Delete</button>
            </form>
            <br>
          {% endif %}
        {% endfor %}
      {% else %}
        <p class="small">No research yet</p>
      {% endif %}
    </div>
  </div>

  <div class="card images">
    <h3>🖼 Images</h3>
    <div class="img-grid" style="margin-top:10px;">
      {% if images %}
        {% for i in images %}
          <div>
            <img src="{{i}}">
            {% if is_admin %}
              <form method="post" action="/delete/images">
                <input type="hidden" name="filename" value="{{i.split('/')[-1]}}">
                <div class="admin-controls"><button class="btn btn-danger" type="submit">Delete</button></div>
              </form>
            {% endif %}
          </div>
        {% endfor %}
      {% else %}
        <p class="small">No images yet</p>
      {% endif %}
    </div>
  </div>
</div>

{% if is_admin %}
<div style="max-width:800px;margin:20px auto;background:white;padding:16px;border-radius:10px;">
  <h3 style="text-align:center;">Admin Upload (research: .pdf, videos: .mp4/.avi, images: .jpg/.png)</h3>
  <div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap;">
    <form enctype="multipart/form-data" method="post" action="/upload/research">
      <input type="file" name="file" accept=".pdf" required><br><button class="btn btn-primary" type="submit">Upload Paper</button>
    </form>
    <form enctype="multipart/form-data" method="post" action="/upload/videos">
      <input type="file" name="file" accept="video/*" required><br><button class="btn btn-primary" type="submit">Upload Video</button>
    </form>
    <form enctype="multipart/form-data" method="post" action="/upload/images">
      <input type="file" name="file" accept="image/*" required><br><button class="btn btn-primary" type="submit">Upload Image</button>
    </form>
  </div>
</div>
{% endif %}

<div style="text-align:center;margin-top:18px;">
  <a class="logout" href="/logout">🚪 Logout</a>
</div>
"""

# ---------- Helper functions ----------
def list_public_urls():
    # build relative URLs to serve files
    vids = [f"/uploads/videos/{p.name}" for p in VIDEOS.iterdir() if p.is_file()]
    imgs = [f"/uploads/images/{p.name}" for p in IMAGES.iterdir() if p.is_file()]
    rps = [f"/uploads/research/{p.name}" for p in RESEARCH.iterdir() if p.is_file()]
    # sort to show newest last
    vids.sort(); imgs.sort(); rps.sort()
    return vids, imgs, rps

def allowed_filename(filename, allowed_set):
    ext = Path(filename).suffix.lower()
    return ext in allowed_set

# ---------- Flask routes ----------
@app.route("/")
def index():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return render_template_string(home_page)

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method=="POST":
        u = request.form.get("username").strip()
        p = request.form.get("password")
        if not u or not p:
            return "Missing", 400
        if u in users:
            return "<h3 style='text-align:center;color:red;'>Username exists</h3>" + render_template_string(register_page)
        users[u] = p
        return redirect(url_for("login"))
    return render_template_string(register_page)

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        u = request.form.get("username").strip()
        p = request.form.get("password")
        if u in users and users[u] == p:
            session["user"] = u
            return redirect(url_for("dashboard"))
        return "<h3 style='text-align:center;color:red;'>Incorrect credentials</h3>" + render_template_string(login_page)
    return render_template_string(login_page)

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    vids, imgs, rps = list_public_urls()
    return render_template_string(dashboard_template,
                                  username=session["user"],
                                  videos=vids, images=imgs, research=rps,
                                  is_admin=(session["user"]=="admin"))

# upload endpoints for admin
@app.route("/upload/<category>", methods=["POST"])
def upload_category(category):
    if "user" not in session or session["user"] != "admin":
        return "Unauthorized", 403
    f = request.files.get("file")
    if not f:
        return "No file", 400
    filename = secure_filename(f.filename)
    ext = Path(filename).suffix.lower()
    if category == "research":
        if not allowed_filename(filename, ALLOWED_RESEARCH):
            return "Bad extension for research", 400
        dest = RESEARCH / filename
    elif category == "videos":
        if not allowed_filename(filename, ALLOWED_VIDEOS):
            return "Bad extension for video", 400
        dest = VIDEOS / filename
    elif category == "images":
        if not allowed_filename(filename, ALLOWED_IMAGES):
            return "Bad extension for image", 400
        dest = IMAGES / filename
    else:
        return "Unknown category", 400
    f.save(str(dest))
    return redirect(url_for("dashboard"))

# delete endpoints for admin (POST)
@app.route("/delete/<category>", methods=["POST"])
def delete_category(category):
    if "user" not in session or session["user"] != "admin":
        return "Unauthorized", 403
    filename = request.form.get("filename")
    if not filename:
        return "Missing filename", 400
    safe = secure_filename(filename)
    if category == "research":
        p = RESEARCH / safe
    elif category == "videos":
        p = VIDEOS / safe
    elif category == "images":
        p = IMAGES / safe
    else:
        return "Unknown category", 400
    if p.exists():
        p.unlink()
        return redirect(url_for("dashboard"))
    return "File not found", 404

# serve uploaded files
@app.route("/uploads/<category>/<filename>")
def serve_upload(category, filename):
    safe = secure_filename(filename)
    if category == "research":
        folder = str(RESEARCH)
    elif category == "videos":
        folder = str(VIDEOS)
    elif category == "images":
        folder = str(IMAGES)
    else:
        return "Not found", 404
    return send_from_directory(folder, safe)

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("index"))

# ---------- Helper to find free TCP port ----------
import socket
def find_free_port():
    s = socket.socket()
    s.bind(('',0))
    port = s.getsockname()[1]
    s.close()
    return port

# ---------- Run Flask + cloudflared tunnel ----------
def start_flask_and_tunnel():
    port = find_free_port()
    print(f"Starting Flask on port {port} ...")
    # start cloudflared in background and capture output
    # use --no-autoupdate to avoid prompt
    tunnel_log = "/content/cloudflared_tunnel.log"
    # ensure any previous cloudflared process is killed
    try:
        subprocess.run(["pkill","cloudflared"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    # start cloudflared as background process, writing logs to file
    cmd = ["cloudflared","tunnel","--url",f"http://localhost:{port}","--no-autoupdate"]
    print("Launching cloudflared tunnel (background), logs ->", tunnel_log)
    # start tunnel with Popen so Flask can also start
    with open(tunnel_log,"w") as out:
        proc = subprocess.Popen(cmd, stdout=out, stderr=out, text=True)
    # small delay for tunnel to initialize
    time.sleep(2)
    # try to read the URL from log (give it a few seconds)
    public_url = None
    for _ in range(12):
        time.sleep(1)
        if os.path.exists(tunnel_log):
            txt = Path(tunnel_log).read_text(errors="ignore")
            # cloudflared prints "https://*.trycloudflare.com" line
            import re
            m = re.search(r"https://[a-z0-9\-]+\.trycloudflare\.com", txt)
            if m:
                public_url = m.group(0)
                break
    if not public_url:
        print("⚠️ Could not automatically find public URL in cloudflared logs. Open the log at", tunnel_log)
    else:
        print("🌍 Public URL:", public_url)
    # now run Flask (blocking)
    app.run(host="0.0.0.0", port=port, debug=False)

# Run in background thread so Colab cell doesn't block completely while printing
thread = threading.Thread(target=start_flask_and_tunnel, daemon=True)
thread.start()

print("App launching — give it ~5-10 seconds. Watch the output for the public URL printed by the script.")
