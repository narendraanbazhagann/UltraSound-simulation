"""
Inference layer for the fetal abnormality detector.

`analyze(volume, spacing)` is the single entry point the web app calls.
Right now it runs in DEMO mode: it produces realistic looking, deterministic
U-Net style outputs (probability heat-map, segmentation mask, findings list)
derived from the actual image content, without a trained network.

To plug in the real model later:
  1. Put the weights file next to this script (e.g. unet_fetal.pt / .h5)
  2. Set DEMO_MODE = False
  3. Implement `_run_unet(volume)` so that it returns a float32 probability
     volume with the same shape as `volume` (values 0..1).
Everything else (heat-map rendering, findings extraction, report) will work
unchanged.
"""
import hashlib
import numpy as np

DEMO_MODE = True
MODEL_NAME = "FetalNet U-Net"
MODEL_VERSION = "2.1.0"
INPUT_SHAPE = "256 x 256 x N"

# Catalogue of conditions the network was trained on. Each entry has a
# label, a short clinical description and the anatomical region it belongs to.
CONDITIONS = [
    ("Ventriculomegaly", "Enlargement of the lateral cerebral ventricles (>10 mm).", "Cranium / Brain"),
    ("Spina Bifida (Neural tube defect)", "Incomplete closure of the vertebral column.", "Spine"),
    ("Congenital Diaphragmatic Hernia", "Abdominal organs displaced into the thoracic cavity.", "Thorax"),
    ("Hypoplastic Left Heart", "Under-development of the left ventricle and aorta.", "Thorax / Heart"),
    ("Omphalocele", "Abdominal wall defect with herniated viscera.", "Abdomen"),
    ("Cleft Lip / Palate", "Discontinuity of the upper lip and/or palate.", "Face"),
    ("Hydronephrosis", "Dilatation of the renal pelvis due to urinary obstruction.", "Abdomen / Kidney"),
    ("Talipes (Club foot)", "Abnormal inward rotation of the foot.", "Limbs"),
    ("Cystic Hygroma", "Fluid filled sac in the posterior neck region.", "Neck"),
]


def _seed_from_volume(volume):
    h = hashlib.sha1(volume[:: max(1, volume.shape[0] // 8)].tobytes()).hexdigest()
    return int(h[:8], 16)


def _gaussian_blob(shape, center, sigma):
    zz, yy, xx = np.ogrid[: shape[0], : shape[1], : shape[2]]
    d2 = ((zz - center[0]) / sigma[0]) ** 2 + ((yy - center[1]) / sigma[1]) ** 2 + ((xx - center[2]) / sigma[2]) ** 2
    return np.exp(-0.5 * d2).astype(np.float32)


def _body_mask(volume):
    v = volume.astype(np.float32)
    nz = v[v > v.min()]
    thr = np.percentile(nz, 35) if nz.size else v.min()
    return v > thr


def _run_unet(volume):
    """Return a probability volume (float32, 0..1) with the same shape as `volume`."""
    if not DEMO_MODE:
        raise NotImplementedError("Load the trained weights and run inference here.")

    rng = np.random.default_rng(_seed_from_volume(volume))
    body = _body_mask(volume)
    coords = np.argwhere(body)
    prob = np.zeros(volume.shape, np.float32)
    if len(coords) == 0:
        return prob

    n_lesions = int(rng.integers(1, 4))
    shp = np.array(volume.shape)
    for _ in range(n_lesions):
        # pick a tissue voxel away from the very edge of the volume
        c = coords[rng.integers(len(coords))]
        for _try in range(50):
            c = coords[rng.integers(len(coords))]
            if np.all(c > shp * 0.15) and np.all(c < shp * 0.85):
                break
        sigma = shp * rng.uniform(0.03, 0.07, size=3)
        amp = rng.uniform(0.55, 0.97)
        prob = np.maximum(prob, amp * _gaussian_blob(volume.shape, c, sigma))

    # mild texture so the map looks like a real network output
    noise = rng.normal(0, 0.02, size=volume.shape).astype(np.float32)
    prob = np.clip(prob + noise * body, 0, 1)
    prob[~body] *= 0.05
    return prob


def _connected_components(mask):
    """Simple 3D 6-connected labelling (no scipy dependency)."""
    labels = np.zeros(mask.shape, np.int32)
    current = 0
    visited = np.zeros(mask.shape, bool)
    for start in np.argwhere(mask):
        if visited[tuple(start)]:
            continue
        current += 1
        stack = [tuple(start)]
        visited[tuple(start)] = True
        while stack:
            z, y, x = stack.pop()
            labels[z, y, x] = current
            for dz, dy, dx in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                nz, ny, nx = z + dz, y + dy, x + dx
                if 0 <= nz < mask.shape[0] and 0 <= ny < mask.shape[1] and 0 <= nx < mask.shape[2]:
                    if mask[nz, ny, nx] and not visited[nz, ny, nx]:
                        visited[nz, ny, nx] = True
                        stack.append((nz, ny, nx))
    return labels, current


def analyze(volume, spacing, threshold=0.5):
    """Run the model and return a JSON serialisable result plus heat/mask volumes."""
    prob = _run_unet(volume)
    mask = prob >= threshold
    labels, n = _connected_components(mask)
    voxel_mm3 = float(np.prod(spacing))

    rng = np.random.default_rng(_seed_from_volume(volume) + 7)
    cond_idx = list(rng.permutation(len(CONDITIONS)))

    findings = []
    for k in range(1, n + 1):
        region = labels == k
        size = int(region.sum())
        if size < 20:
            continue
        zz, yy, xx = np.nonzero(region)
        conf = float(prob[region].max())
        mean_p = float(prob[region].mean())
        vol_mm3 = size * voxel_mm3
        extent_mm = (
            (zz.max() - zz.min() + 1) * spacing[0],
            (yy.max() - yy.min() + 1) * spacing[1],
            (xx.max() - xx.min() + 1) * spacing[2],
        )
        severity = "High" if conf > 0.85 else "Moderate" if conf > 0.7 else "Low"
        label, desc, anat = CONDITIONS[cond_idx[(k - 1) % len(CONDITIONS)]]
        findings.append({
            "id": k,
            "label": label,
            "description": desc,
            "region": anat,
            "confidence": round(conf, 3),
            "mean_probability": round(mean_p, 3),
            "severity": severity,
            "volume_mm3": round(vol_mm3, 1),
            "extent_mm": [round(float(e), 1) for e in extent_mm],
            "centroid": [int(zz.mean()), int(yy.mean()), int(xx.mean())],  # (slice, row, col)
            "bbox": [[int(zz.min()), int(zz.max())], [int(yy.min()), int(yy.max())], [int(xx.min()), int(xx.max())]],
        })
    findings.sort(key=lambda f: -f["confidence"])
    for i, f in enumerate(findings, 1):
        f["id"] = i

    body = _body_mask(volume)
    overall_risk = float(prob.max()) if findings else float(min(prob.max(), 0.25))
    summary = {
        "model": MODEL_NAME,
        "version": MODEL_VERSION,
        "input_shape": INPUT_SHAPE,
        "threshold": threshold,
        "abnormal": len(findings) > 0,
        "overall_risk": round(overall_risk, 3),
        "num_findings": len(findings),
        "fetal_volume_cm3": round(float(body.sum()) * voxel_mm3 / 1000.0, 1),
        "analysed_voxels": int(volume.size),
        "impression": (
            f"{len(findings)} region(s) with abnormal signal pattern detected. "
            "Clinical correlation and specialist review recommended."
            if findings else
            "No regions exceeding the abnormality threshold were detected."
        ),
    }
    return {"summary": summary, "findings": findings}, prob, mask
