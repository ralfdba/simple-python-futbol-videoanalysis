# -*- coding: utf-8 -*-
# Anotador de jugadas desde video con soporte .env y batch
# Teclas en la ventana: g=gol, t=tiro, p=pase, f=falta, o=amarilla, r=roja, q=salir/avanzar

import os
from dotenv import load_dotenv
import cv2
import pandas as pd
from pathlib import Path
from datetime import timedelta
from typing import List, Optional, Tuple

# -------------------- Config por defecto (puedes sobreescribir por .env) --------------------
DEFAULT_FPS_SAMPLE = 5       # muestreo de frames para detección de cortes
DEFAULT_HIST_JUMP = 0.55     # umbral (0..1 aprox) para proponer “corte”
DEFAULT_OUTPUT_DIR = "."

# -------------------- Utilidades --------------------
def ts_to_clock(sec: float) -> str:
    return str(timedelta(seconds=int(sec)))

def _safe_fps(cap: cv2.VideoCapture) -> float:
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 1e-6:
        return 25.0
    return fps

def _detect_cuts(cap: cv2.VideoCapture, fps: float, fps_sample: int, hist_jump: float, total_frames: int) -> List[int]:
    """Detecta cortes de escena por diferencia de histogramas HSV."""
    cuts = [0]
    prev_hist = None
    # aseguramos step >=1
    step = int(max(1, fps // max(1, fps_sample)))
    for f in range(0, total_frames, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, frame = cap.read()
        if not ok:
            break
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
        hist = cv2.normalize(hist, hist).flatten()
        if prev_hist is not None:
            diff = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA)
            if diff > hist_jump:
                cuts.append(f)
        prev_hist = hist
    if total_frames > 0:
        cuts.append(total_frames - 1)
    return cuts

def _export_excel(df: pd.DataFrame, out_xlsx: Path) -> None:
    out_xlsx.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_xlsx, engine="xlsxwriter") as xw:
        df.to_excel(xw, index=False, sheet_name="events")
        (df.groupby("action")
           .size()
           .reset_index(name="count")
           .to_excel(xw, index=False, sheet_name="summary_actions"))

# -------------------- Núcleo de un video --------------------
def process_video(
    video_path: str | Path,
    match_id: Optional[str] = None,
    fps_sample: int = DEFAULT_FPS_SAMPLE,
    hist_jump: float = DEFAULT_HIST_JUMP,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    output_suffix: str = "_jugadas.xlsx"
) -> Path:
    """
    Reproduce un video para etiquetar eventos con el teclado y exporta un Excel.
    Devuelve la ruta del Excel exportado.
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"No existe el video: {video_path}")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"No se pudo abrir el video: {video_path}")

    fps = _safe_fps(cap)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    cuts = _detect_cuts(cap, fps, fps_sample, hist_jump, total)

    # Preparar reproducción
    events = []
    curr_idx = 0
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    # MATCH_ID por defecto: nombre del archivo sin extensión
    if not match_id:
        match_id = video_path.stem

    print(f"\n==> Procesando: {video_path.name}  |  MATCH_ID={match_id}")
    print("Teclas: [g]=gol, [t]=tiro, [p]=pase, [f]=falta, [o]=amarilla, [r]=roja, [q]=salir")
    print("Tramos sugeridos (cortes detectados):", len(cuts) - 1)

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        fno = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        sec = fno / fps
        label: Optional[Tuple[str, Optional[str]]] = None

        # Overlay
        overlay = frame.copy()
        cv2.putText(
            overlay,
            f"{ts_to_clock(sec)}  (frame {fno}/{total})",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (255, 255, 255),
            2
        )
        # barra simple de progreso de tramo
        while curr_idx < len(cuts) - 1 and not (cuts[curr_idx] <= fno < cuts[curr_idx + 1]):
            curr_idx += 1
        cv2.rectangle(
            overlay,
            (10, 10),
            (int(10 + 300 * (curr_idx + 1) / max(1, (len(cuts) - 1))), 20),
            (0, 255, 0),
            -1
        )
        cv2.imshow("Analizador", overlay)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('g'): label = ("shot", "goal")
        elif key == ord('t'): label = ("shot", None)
        elif key == ord('p'): label = ("pass", None)
        elif key == ord('f'): label = ("foul", None)
        elif key == ord('o'): label = ("foul", "yellow_card")
        elif key == ord('r'): label = ("foul", "red_card")
        elif key == ord('q'):
            print("Salida solicitada por usuario.")
            break

        if label:
            minute = int(sec // 60)
            second = int(sec % 60)
            event = {
                "match_id": match_id,
                "period": 1 if minute < 45 else 2,  # aproximación simple
                "minute": minute,
                "second": second,
                "team": None,
                "player": None,
                "action": label[0],
                "outcome": label[1],
                "x": None, "y": None,
                "extra": {"video_time": ts_to_clock(sec), "frame": fno}
            }
            events.append(event)
            print("Marcado:", event)

    cap.release()
    cv2.destroyAllWindows()

    df = pd.DataFrame(events)
    out_dir = Path(output_dir)
    out_xlsx = out_dir / f"{Path(match_id).stem}{output_suffix}"
    _export_excel(df, out_xlsx)
    print("Exportado:", out_xlsx.resolve())
    return out_xlsx

# -------------------- Batch de muchos videos --------------------
def process_many(
    videos: List[str | Path],
    match_ids: Optional[List[str]] = None,
    fps_sample: int = DEFAULT_FPS_SAMPLE,
    hist_jump: float = DEFAULT_HIST_JUMP,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    output_suffix: str = "_jugadas.xlsx"
) -> List[Path]:
    """
    Procesa múltiples videos en orden.
    - Abre una ventana por video para etiquetar con teclado.
    - Cierra con 'q' para pasar al siguiente.
    Devuelve la lista de rutas a los Excel exportados.
    """
    results: List[Path] = []
    if match_ids and len(match_ids) != len(videos):
        raise ValueError("Si entregas match_ids, su longitud debe coincidir con la de videos.")
    for i, v in enumerate(videos):
        mid = match_ids[i] if (match_ids and i < len(match_ids)) else None
        try:
            out = process_video(
                v, match_id=mid, fps_sample=fps_sample, hist_jump=hist_jump,
                output_dir=output_dir, output_suffix=output_suffix
            )
            results.append(out)
        except Exception as e:
            print(f"[ADVERTENCIA] Falló {v}: {e}")
    return results

# -------------------- Carga desde .env y ejecución opcional --------------------
def _parse_list_env(val: Optional[str]) -> List[str]:
    if not val:
        return []
    # admite coma o salto de línea
    items = [x.strip() for x in val.replace("\n", ",").split(",")]
    return [x for x in items if x]

def main_from_env():
    """
    Lee variables desde .env y corre process_many si hay videos definidos.
    Variables soportadas en .env:
      VIDEOS=lista separada por comas o saltos de línea con rutas a mp4/mkv/avi
      MATCH_IDS=lista separada por comas (opcional, alineada con VIDEOS)
      VIDEOS_DIR=si no usas VIDEOS, puedes dar un directorio; se usarán *.mp4 por defecto
      GLOB_PATTERN=patrón para VIDEOS_DIR (default: *.mp4)
      OUTPUT_DIR=directorio de salida (default: .)
      OUTPUT_SUFFIX=sufijo de archivo Excel (default: _jugadas.xlsx)
      FPS_SAMPLE=entero (default: 5)
      HIST_JUMP=float (default: 0.55)
    """
    load_dotenv()

    videos = _parse_list_env(os.getenv("VIDEOS"))
    match_ids = _parse_list_env(os.getenv("MATCH_IDS"))

    videos_dir = os.getenv("VIDEOS_DIR")
    glob_pattern = os.getenv("GLOB_PATTERN", "*.mp4")
    output_dir = os.getenv("OUTPUT_DIR", DEFAULT_OUTPUT_DIR)
    output_suffix = os.getenv("OUTPUT_SUFFIX", "_jugadas.xlsx")

    fps_sample = int(os.getenv("FPS_SAMPLE", DEFAULT_FPS_SAMPLE))
    hist_jump = float(os.getenv("HIST_JUMP", DEFAULT_HIST_JUMP))

    if not videos:
        # si no hay VIDEOS, intenta VIDEOS_DIR
        if videos_dir and Path(videos_dir).exists():
            videos = [str(p) for p in Path(videos_dir).glob(glob_pattern)]
            videos.sort()

    if not videos:
        print("No se encontraron videos. Define VIDEOS o VIDEOS_DIR en .env")
        return

    print(f"Se procesarán {len(videos)} video(s).")
    if match_ids and len(match_ids) != len(videos):
        raise ValueError("MATCH_IDS debe tener la misma cantidad de elementos que VIDEOS.")

    process_many(
        videos=videos,
        match_ids=match_ids if match_ids else None,
        fps_sample=fps_sample,
        hist_jump=hist_jump,
        output_dir=output_dir,
        output_suffix=output_suffix
    )

if __name__ == "__main__":
    # Ejecuta el batch si corres el script directamente
    main_from_env()
