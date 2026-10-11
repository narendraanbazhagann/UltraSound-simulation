"""DICOM loading, volume building and slice rendering helpers."""
import io
import os
import zipfile
import tempfile

import numpy as np
import pydicom
from PIL import Image


def _collect_dicom_paths(folder):
    paths = []
    for root, _, files in os.walk(folder):
        for f in files:
            p = os.path.join(root, f)
            try:
                with open(p, "rb") as fh:
                    fh.seek(128)
                    if fh.read(4) == b"DICM":
                        paths.append(p)
                        continue
                # Some files have no preamble, try to parse anyway
                pydicom.dcmread(p, stop_before_pixels=True)
                paths.append(p)
            except Exception:
                pass
    return paths


def extract_uploads(file_storages, dest):
    """Save uploaded files (plain .dcm or .zip) into dest folder."""
    os.makedirs(dest, exist_ok=True)
    for fs in file_storages:
        name = os.path.basename(fs.filename or "file")
        target = os.path.join(dest, name)
        fs.save(target)
        if name.lower().endswith(".zip"):
            with zipfile.ZipFile(target) as z:
                z.extractall(dest)
            os.remove(target)


def load_series(folder):
    """Load every DICOM file in folder into a 3D volume.

    Returns dict with 'volume' (int16, shape [slices, rows, cols]),
    'spacing' (slice, row, col in mm) and 'meta' (patient/study info).
    """
    paths = _collect_dicom_paths(folder)
    if not paths:
        raise ValueError("No DICOM files found in upload.")

    datasets = []
    for p in paths:
        ds = pydicom.dcmread(p)
        if not hasattr(ds, "PixelData"):
            continue
        datasets.append(ds)
    if not datasets:
        raise ValueError("DICOM files contain no pixel data.")

    # Sort along the slice normal if positions exist, otherwise by instance number
    def sort_key(ds):
        ipp = getattr(ds, "ImagePositionPatient", None)
        iop = getattr(ds, "ImageOrientationPatient", None)
        if ipp is not None and iop is not None and len(iop) == 6:
            r = np.array(iop[:3], float)
            c = np.array(iop[3:], float)
            n = np.cross(r, c)
            return float(np.dot(np.array(ipp, float), n))
        return float(getattr(ds, "InstanceNumber", 0) or 0)

    datasets.sort(key=sort_key)

    ref = datasets[0]
    rows, cols = int(ref.Rows), int(ref.Columns)
    slices = []
    for ds in datasets:
        arr = ds.pixel_array.astype(np.float32)
        if arr.ndim == 3:          # multi-frame or RGB -> take first channel/frame
            arr = arr[..., 0] if arr.shape[-1] in (3, 4) else arr[0]
        if arr.shape != (rows, cols):
            arr = np.array(Image.fromarray(arr).resize((cols, rows)))
        slope = float(getattr(ds, "RescaleSlope", 1) or 1)
        inter = float(getattr(ds, "RescaleIntercept", 0) or 0)
        arr = arr * slope + inter
        if str(getattr(ds, "PhotometricInterpretation", "")) == "MONOCHROME1":
            arr = arr.max() - arr
        slices.append(arr)
    volume = np.stack(slices).astype(np.int16)

    ps = getattr(ref, "PixelSpacing", [1.0, 1.0])
    st = getattr(ref, "SliceThickness", None)
    if len(datasets) > 1:
        try:
            z0 = np.array(datasets[0].ImagePositionPatient, float)
            z1 = np.array(datasets[1].ImagePositionPatient, float)
            d = float(np.linalg.norm(z1 - z0))
            if d > 0:
                st = d
        except Exception:
            pass
    st = float(st or 1.0)
    spacing = (st, float(ps[0]), float(ps[1]))

    lo, hi = np.percentile(volume, [1, 99.5])
    meta = {
        "patient_name": str(getattr(ref, "PatientName", "Anonymous")),
        "patient_id": str(getattr(ref, "PatientID", "N/A")),
        "modality": str(getattr(ref, "Modality", "N/A")),
        "study_date": str(getattr(ref, "StudyDate", "") or "N/A"),
        "study_description": str(getattr(ref, "StudyDescription", "") or "N/A"),
        "series_description": str(getattr(ref, "SeriesDescription", "") or "N/A"),
        "manufacturer": str(getattr(ref, "Manufacturer", "") or "N/A"),
        "rows": rows,
        "cols": cols,
        "slices": len(datasets),
        "spacing": spacing,
        "bits": int(getattr(ref, "BitsStored", 16)),
        "min": float(volume.min()),
        "max": float(volume.max()),
        "default_wc": float((lo + hi) / 2),
        "default_ww": float(max(hi - lo, 1)),
    }
    return {"volume": volume, "spacing": spacing, "meta": meta}


AXES = ("axial", "coronal", "sagittal")


def slice_count(volume, axis):
    return {"axial": volume.shape[0], "coronal": volume.shape[1], "sagittal": volume.shape[2]}[axis]


def get_slice(volume, axis, index):
    index = int(np.clip(index, 0, slice_count(volume, axis) - 1))
    if axis == "axial":
        return volume[index]
    if axis == "coronal":
        return volume[:, index, :]
    return volume[:, :, index]


def _target_size(volume, spacing, axis):
    """Pixel size so that non-axial views keep correct physical aspect ratio."""
    sz, sr, sc = spacing
    ns, nr, nc = volume.shape
    if axis == "axial":
        return int(round(nc * sc / sr)), nr
    if axis == "coronal":
        return nc, int(round(ns * sz / sc))
    return nr, int(round(ns * sz / sr))


def render_slice_png(volume, spacing, axis, index, wc, ww):
    img = get_slice(volume, axis, index).astype(np.float32)
    lo = wc - ww / 2.0
    img = np.clip((img - lo) / max(ww, 1e-3), 0, 1) * 255
    pil = Image.fromarray(img.astype(np.uint8), mode="L")
    w, h = _target_size(volume, spacing, axis)
    if (w, h) != pil.size:
        pil = pil.resize((w, h), Image.BILINEAR)
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue()


def _colormap(v):
    """Jet-like colormap. v in [0,1] -> (r,g,b) uint8 arrays."""
    r = np.clip(1.5 - np.abs(4 * v - 3), 0, 1)
    g = np.clip(1.5 - np.abs(4 * v - 2), 0, 1)
    b = np.clip(1.5 - np.abs(4 * v - 1), 0, 1)
    return (r * 255).astype(np.uint8), (g * 255).astype(np.uint8), (b * 255).astype(np.uint8)


def render_heatmap_png(heat, spacing, axis, index, mask=None):
    """heat: float32 volume in [0,1]; returns RGBA PNG with alpha from heat."""
    h = get_slice(heat, axis, index).astype(np.float32)
    r, g, b = _colormap(h)
    alpha = (np.clip(h, 0, 1) ** 0.8 * 220).astype(np.uint8)
    rgba = np.dstack([r, g, b, alpha])
    if mask is not None:
        m = get_slice(mask, axis, index)
        # draw the segmentation contour in bright green
        edge = m ^ np.roll(m, 1, 0) | m ^ np.roll(m, 1, 1)
        rgba[edge] = (80, 255, 120, 255)
    pil = Image.fromarray(rgba, mode="RGBA")
    w, hh = _target_size(heat, spacing, axis)
    if (w, hh) != pil.size:
        pil = pil.resize((w, hh), Image.BILINEAR)
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue()
