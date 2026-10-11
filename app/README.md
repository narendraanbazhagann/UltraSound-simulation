# FetalScan AI - Prenatal DICOM Viewer & Abnormality Detection

A web based DICOM viewer (3D Slicer style) with an AI analysis panel that
highlights suspected fetal abnormalities on the scan.

## Run

```
cd app
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000 (or just double-click `run.bat` on Windows).

Shortcut for demos: http://127.0.0.1:5000/?demo=1&analyze=1 loads the sample
dataset and runs the analysis automatically.

## Features
- Upload one or many `.dcm` files or a `.zip` of a series
- Axial / Coronal / Sagittal views, slice slider, mouse wheel scrolling
- Window/level (drag), presets, invert, zoom (Ctrl+wheel), pan (right drag)
- Double-click a view to maximise it
- "Run AI Analysis": U-Net inference, probability heat-map overlay with
  segmentation contour, findings list (click a finding to jump to it)
- Printable report (`Report` button) that can be saved as PDF

## Project layout
```
app/
  app.py          Flask server and REST API
  dicom_utils.py  DICOM loading, volume building, slice / heat-map rendering
  model.py        Inference layer  <-- plug the trained U-Net in here
  templates/      index.html (viewer), report.html
  static/         style.css, app.js
fetus-dicom/      sample series (153 slices)
```

## Plugging in the real model
`model.py` currently runs in `DEMO_MODE` and synthesises a realistic
probability map from the image content. When the trained U-Net is ready:

1. Copy the weights next to `model.py`.
2. Set `DEMO_MODE = False`.
3. Implement `_run_unet(volume)` so it returns a float32 array with the same
   shape as `volume` containing per-voxel abnormality probabilities (0..1).

Thresholding, connected-component extraction, findings, heat-map rendering and
the report all work unchanged.

## API
| Method | Route | Purpose |
|---|---|---|
| POST | /api/upload | multipart `files` (dcm or zip) -> series metadata |
| POST | /api/demo | load bundled sample series |
| GET | /api/series/{id}/slice/{axis}/{i}?wc=&ww= | windowed PNG slice |
| POST | /api/series/{id}/analyze | run model, returns summary + findings |
| GET | /api/series/{id}/heatmap/{axis}/{i} | RGBA heat-map PNG |
| GET | /report/{id} | HTML report |
