import os
import time
import uuid
import shutil

from flask import Flask, jsonify, render_template, request, abort, Response

import dicom_utils as du
import model

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE, "uploads")
DEMO_DIR = os.path.normpath(os.path.join(BASE, "..", "fetus-dicom"))
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024  # 1 GB

SERIES = {}   # series_id -> {"volume", "spacing", "meta", "heat", "mask", "result"}


def _get(series_id):
    s = SERIES.get(series_id)
    if s is None:
        abort(404, "Series not found. Please upload again.")
    return s


def _register(folder, source):
    data = du.load_series(folder)
    sid = uuid.uuid4().hex[:12]
    data["meta"]["series_id"] = sid
    data["meta"]["source"] = source
    data["meta"]["loaded_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    data.update({"heat": None, "mask": None, "result": None})
    SERIES[sid] = data
    return data["meta"]


@app.route("/")
def index():
    return render_template("index.html", model_name=model.MODEL_NAME,
                           model_version=model.MODEL_VERSION)


@app.post("/api/upload")
def upload():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files received"}), 400
    folder = os.path.join(UPLOAD_DIR, uuid.uuid4().hex)
    try:
        du.extract_uploads(files, folder)
        return jsonify(_register(folder, "upload"))
    except Exception as e:
        shutil.rmtree(folder, ignore_errors=True)
        return jsonify({"error": str(e)}), 400


@app.post("/api/demo")
def load_demo():
    if not os.path.isdir(DEMO_DIR):
        return jsonify({"error": "Demo dataset folder not found"}), 404
    try:
        return jsonify(_register(DEMO_DIR, "demo"))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/series/<sid>/meta")
def meta(sid):
    return jsonify(_get(sid)["meta"])


@app.get("/api/series/<sid>/slice/<axis>/<int:index>")
def slice_png(sid, axis, index):
    s = _get(sid)
    if axis not in du.AXES:
        abort(400)
    wc = float(request.args.get("wc", s["meta"]["default_wc"]))
    ww = float(request.args.get("ww", s["meta"]["default_ww"]))
    png = du.render_slice_png(s["volume"], s["spacing"], axis, index, wc, ww)
    return Response(png, mimetype="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/series/<sid>/heatmap/<axis>/<int:index>")
def heatmap_png(sid, axis, index):
    s = _get(sid)
    if axis not in du.AXES or s["heat"] is None:
        abort(404)
    png = du.render_heatmap_png(s["heat"], s["spacing"], axis, index, s["mask"])
    return Response(png, mimetype="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/series/<sid>/analyze")
def analyze(sid):
    s = _get(sid)
    t0 = time.time()
    result, heat, mask = model.analyze(s["volume"], s["spacing"])
    s["heat"], s["mask"], s["result"] = heat, mask, result
    result["summary"]["inference_time_s"] = round(time.time() - t0, 2)
    result["summary"]["analysed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return jsonify(result)


@app.get("/api/series/<sid>/result")
def result(sid):
    s = _get(sid)
    if s["result"] is None:
        abort(404)
    return jsonify(s["result"])


@app.get("/report/<sid>")
def report(sid):
    s = _get(sid)
    if s["result"] is None:
        abort(404, "Run the analysis first.")
    return render_template("report.html", meta=s["meta"], result=s["result"],
                           model_name=model.MODEL_NAME, model_version=model.MODEL_VERSION)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
