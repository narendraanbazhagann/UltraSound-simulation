# FetalScan AI

FetalScan AI is a Flask-based prenatal DICOM viewer with a browser interface
for reviewing image series and exploring simulated abnormality detections.

> **Important:** The repository intentionally excludes all DICOM datasets and
> runtime uploads. The included analysis pipeline runs in demo mode and is not
> a medical diagnostic device.

## Features

- Upload one or more DICOM files or a ZIP archive containing a series
- Axial, coronal, and sagittal slice views
- Window/level controls, inversion, zoom, pan, and slice navigation
- Demo U-Net-style probability heat map and segmentation overlay
- Findings list with confidence, severity, volume, and location details
- Printable HTML report

## Requirements

- Python 3.10 or newer
- A browser with JavaScript enabled

## Quick start

From the repository root:

```powershell
cd app
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000/> in a browser.

On Windows, `app\run.bat` can also install the requirements and start the
server.

## Using the application

1. Open the application in a browser.
2. Upload a DICOM series or a ZIP archive of DICOM files.
3. Review the axial, coronal, and sagittal views.
4. Select **Run AI Analysis** to generate the demo heat map and findings.
5. Open the generated report when needed.

The `/api/demo` endpoint expects a local dataset, but datasets are excluded
from this repository for privacy and size reasons.

## Replacing the demo model

The inference entry point is `app/model.py`. It currently generates
deterministic demo output from the image volume. To connect a trained model:

1. Place model weights in a local, ignored path.
2. Set `DEMO_MODE = False`.
3. Implement `_run_unet(volume)` so it returns a float32 probability volume
   with the same shape as the input and values between 0 and 1.

The existing thresholding, connected-component extraction, heat-map rendering,
findings, and report code can then be reused.

## Project layout

```text
app/
  app.py                 Flask server and REST API
  dicom_utils.py         DICOM loading and slice rendering
  model.py               Demo inference and result extraction
  templates/             Viewer and report pages
  static/                Browser JavaScript and CSS
  requirements.txt       Python dependencies
  run.bat                Windows startup helper
```

## API

| Method | Route | Purpose |
| --- | --- | --- |
| POST | `/api/upload` | Upload DICOM files or a ZIP series |
| POST | `/api/demo` | Load a local demo series, if one is provided |
| GET | `/api/series/{id}/meta` | Return series metadata |
| GET | `/api/series/{id}/slice/{axis}/{index}` | Return a windowed PNG slice |
| POST | `/api/series/{id}/analyze` | Run analysis and return findings |
| GET | `/api/series/{id}/result` | Return an existing analysis result |
| GET | `/api/series/{id}/heatmap/{axis}/{index}` | Return a heat-map PNG |
| GET | `/report/{id}` | Render the printable report |

## Privacy

DICOM files can contain protected health information in both metadata and
pixel data. Do not commit real patient data. The `.gitignore` rules exclude
the bundled dataset, uploaded files, and all files ending in `.dcm`.
