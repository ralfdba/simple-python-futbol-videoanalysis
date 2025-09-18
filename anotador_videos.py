# -*- coding: utf-8 -*-
# GUI de anotación de jugadas con PyQt5
# Controles:
#   Botones: Gol, Tiro, Pase, Falta, Amarilla, Roja, Pausa/Reanudar, Siguiente, Guardar
#   Atajos:  g,t,p,f,o,r, Espacio (pausa), n (siguiente), s (guardar)
#   Campos:  Equipo, Jugador (se guardan por evento)
#
# .env soportado:
#   VIDEOS=lista separada por comas o saltos de línea
#   MATCH_IDS=lista paralela opcional
#   VIDEOS_DIR=directorio si no usas VIDEOS
#   GLOB_PATTERN=*.mp4 (por defecto)
#   OUTPUT_DIR=./exports
#   OUTPUT_SUFFIX=_jugadas.xlsx

import os
import sys
from pathlib import Path
from datetime import timedelta
from typing import List, Optional, Tuple

import cv2
import pandas as pd
from dotenv import load_dotenv

from PyQt5 import QtCore, QtGui, QtWidgets


# -------------------- Utilidades --------------------
def ts_to_clock(sec: float) -> str:
    return str(timedelta(seconds=int(sec)))

def safe_fps(cap: cv2.VideoCapture) -> float:
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 1e-6:
        return 25.0
    return fps

def ensure_event_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["match_id","period","minute","second","team","player","action","outcome","x","y","extra"]
    for c in cols:
        if c not in df.columns:
            df[c] = pd.Series(dtype="object")
    return df[cols + [c for c in df.columns if c not in cols]]

def export_excel(df: pd.DataFrame, out_xlsx: Path) -> None:
    out_xlsx.parent.mkdir(parents=True, exist_ok=True)
    df = ensure_event_columns(df.copy())
    if not df.empty and "action" in df.columns:
        summary = (df["action"]
                   .value_counts(dropna=False)
                   .rename_axis("action")
                   .reset_index(name="count"))
    else:
        summary = pd.DataFrame({"action": pd.Series(dtype="object"),
                                "count": pd.Series(dtype="int64")})
    with pd.ExcelWriter(out_xlsx, engine="xlsxwriter") as xw:
        df.to_excel(xw, index=False, sheet_name="events")
        summary.to_excel(xw, index=False, sheet_name="summary_actions")

def parse_list_env(val: Optional[str]) -> List[str]:
    if not val:
        return []
    items = [x.strip() for x in val.replace("\n", ",").split(",")]
    return [x for x in items if x]

def load_videos_from_env():
    load_dotenv()
    videos = parse_list_env(os.getenv("VIDEOS"))
    match_ids = parse_list_env(os.getenv("MATCH_IDS"))
    videos_dir = os.getenv("VIDEOS_DIR")
    glob_pattern = os.getenv("GLOB_PATTERN", "*.mp4")
    output_dir = os.getenv("OUTPUT_DIR", "./exports")
    output_suffix = os.getenv("OUTPUT_SUFFIX", "_jugadas.xlsx")

    if not videos and videos_dir and Path(videos_dir).exists():
        videos = [str(p) for p in Path(videos_dir).glob(glob_pattern)]
        videos.sort()

    if match_ids and len(match_ids) != len(videos):
        raise ValueError("MATCH_IDS debe tener la misma cantidad de elementos que VIDEOS.")

    return videos, match_ids, output_dir, output_suffix


# -------------------- Ventana principal --------------------
class AnnotatorWindow(QtWidgets.QMainWindow):
    def __init__(self, videos: List[str], match_ids: Optional[List[str]], output_dir: str, output_suffix: str):
        super().__init__()
        self.setWindowTitle("Anotador de Jugadas - PyQt5")
        self.resize(1100, 720)

        self.videos = [Path(v) for v in videos]
        self.match_ids = match_ids or []
        self.output_dir = Path(output_dir)
        self.output_suffix = output_suffix

        self.cap: Optional[cv2.VideoCapture] = None
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._next_frame)
        self.playing = False
        self.fps = 25.0
        self.total_frames = 0
        self.current_video_idx = -1
        self.current_match_id: Optional[str] = None
        self.events: List[dict] = []

        self._build_ui()
        self._build_shortcuts()

        if not self.videos:
            QtWidgets.QMessageBox.critical(self, "Error", "No hay videos definidos. Configura .env (VIDEOS o VIDEOS_DIR).")
        else:
            self.next_video()

    # ---------- UI ----------
    def _build_ui(self):
        central = QtWidgets.QWidget(self)
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        # Video
        self.video_label = QtWidgets.QLabel()
        self.video_label.setMinimumSize(960, 540)
        self.video_label.setStyleSheet("background-color: black;")
        self.video_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.video_label)

        # Progreso + info
        progress_layout = QtWidgets.QHBoxLayout()
        self.progress = QtWidgets.QProgressBar()
        self.progress.setTextVisible(True)
        self.info_label = QtWidgets.QLabel("Listo")
        self.info_label.setMinimumWidth(300)
        progress_layout.addWidget(self.progress, stretch=1)
        progress_layout.addWidget(self.info_label)
        layout.addLayout(progress_layout)

        # Equipo / Jugador
        form = QtWidgets.QHBoxLayout()
        form.addWidget(QtWidgets.QLabel("Equipo:"))
        self.team_edit = QtWidgets.QLineEdit()
        self.team_edit.setMaximumWidth(200)
        form.addWidget(self.team_edit)
        form.addSpacing(20)
        form.addWidget(QtWidgets.QLabel("Jugador:"))
        self.player_edit = QtWidgets.QLineEdit()
        self.player_edit.setMaximumWidth(200)
        form.addWidget(self.player_edit)
        form.addStretch()
        layout.addLayout(form)

        # Botones de acciones
        btns = QtWidgets.QHBoxLayout()
        self.btn_goal = QtWidgets.QPushButton("Gol (g)")
        self.btn_shot = QtWidgets.QPushButton("Tiro (t)")
        self.btn_pass = QtWidgets.QPushButton("Pase (p)")
        self.btn_foul = QtWidgets.QPushButton("Falta (f)")
        self.btn_yellow = QtWidgets.QPushButton("Amarilla (o)")
        self.btn_red = QtWidgets.QPushButton("Roja (r)")
        for b in [self.btn_goal, self.btn_shot, self.btn_pass, self.btn_foul, self.btn_yellow, self.btn_red]:
            btns.addWidget(b)
        layout.addLayout(btns)

        # Botones de control
        ctrl = QtWidgets.QHBoxLayout()
        self.btn_play = QtWidgets.QPushButton("Pausa (Espacio)")
        self.btn_next = QtWidgets.QPushButton("Siguiente (n)")
        self.btn_save = QtWidgets.QPushButton("Guardar (s)")
        ctrl.addWidget(self.btn_play)
        ctrl.addWidget(self.btn_next)
        ctrl.addWidget(self.btn_save)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        # Conexiones
        self.btn_goal.clicked.connect(lambda: self._mark(("shot", "goal")))
        self.btn_shot.clicked.connect(lambda: self._mark(("shot", None)))
        self.btn_pass.clicked.connect(lambda: self._mark(("pass", None)))
        self.btn_foul.clicked.connect(lambda: self._mark(("foul", None)))
        self.btn_yellow.clicked.connect(lambda: self._mark(("foul", "yellow_card")))
        self.btn_red.clicked.connect(lambda: self._mark(("foul", "red_card")))

        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_next.clicked.connect(self.next_video)
        self.btn_save.clicked.connect(self.save_current)

    def _build_shortcuts(self):
        QtWidgets.QShortcut(QtGui.QKeySequence("G"), self, activated=lambda: self._mark(("shot","goal")))
        QtWidgets.QShortcut(QtGui.QKeySequence("T"), self, activated=lambda: self._mark(("shot",None)))
        QtWidgets.QShortcut(QtGui.QKeySequence("P"), self, activated=lambda: self._mark(("pass",None)))
        QtWidgets.QShortcut(QtGui.QKeySequence("F"), self, activated=lambda: self._mark(("foul",None)))
        QtWidgets.QShortcut(QtGui.QKeySequence("O"), self, activated=lambda: self._mark(("foul","yellow_card")))
        QtWidgets.QShortcut(QtGui.QKeySequence("R"), self, activated=lambda: self._mark(("foul","red_card")))
        QtWidgets.QShortcut(QtGui.QKeySequence("Space"), self, activated=self.toggle_play)
        QtWidgets.QShortcut(QtGui.QKeySequence("N"), self, activated=self.next_video)
        QtWidgets.QShortcut(QtGui.QKeySequence("S"), self, activated=self.save_current)

    # ---------- Video ----------
    def open_video(self, path: Path, match_id: Optional[str]):
        # Cerrar previo
        if self.cap:
            self.cap.release()
            self.cap = None

        self.cap = cv2.VideoCapture(str(path))
        if not self.cap.isOpened():
            QtWidgets.QMessageBox.critical(self, "Error", f"No se pudo abrir el video:\n{path}")
            return False

        self.fps = safe_fps(self.cap)
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.current_match_id = match_id or path.stem
        self.events = []
        self.progress.setMaximum(max(1, self.total_frames))
        self.progress.setValue(0)
        self.info_label.setText(f"Video: {path.name} | MATCH_ID: {self.current_match_id} | FPS: {self.fps:.2f} | Frames: {self.total_frames}")

        # Reproducir
        self.playing = True
        self.btn_play.setText("Pausa (Espacio)")
        self.timer.start(max(1, int(1000 / max(1, int(self.fps)))))  # ~tiempo real
        return True

    def toggle_play(self):
        if not self.cap:
            return
        self.playing = not self.playing
        if self.playing:
            self.btn_play.setText("Pausa (Espacio)")
            self.timer.start(max(1, int(1000 / max(1, int(self.fps)))))
        else:
            self.btn_play.setText("Reanudar (Espacio)")
            self.timer.stop()

    def _next_frame(self):
        if not self.cap:
            return
        ok, frame = self.cap.read()
        if not ok:
            # fin del video
            self.timer.stop()
            self.playing = False
            self.btn_play.setText("Reanudar (Espacio)")
            return

        fno = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
        sec = fno / max(1e-6, self.fps)

        # Overlay simple con tiempo
        disp = frame.copy()
        cv2.putText(disp, f"{ts_to_clock(sec)} (frame {fno}/{self.total_frames})",
                    (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255,255,255), 2)

        # Mostrar en QLabel
        rgb = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        qimg = QtGui.QImage(rgb.data, w, h, bytes_per_line, QtGui.QImage.Format_RGB888)
        pix = QtGui.QPixmap.fromImage(qimg).scaled(960, 540, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        self.video_label.setPixmap(pix)

        # Progreso
        self.progress.setValue(min(self.total_frames, fno))
        self.progress.setFormat(f"{ts_to_clock(sec)}")

    # ---------- Anotación ----------
    def _mark(self, label: Tuple[str, Optional[str]]):
        if not self.cap:
            return
        fno = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
        sec = fno / max(1e-6, self.fps)
        minute = int(sec // 60)
        second = int(sec % 60)
        team = self.team_edit.text().strip() or None
        player = self.player_edit.text().strip() or None
        event = {
            "match_id": self.current_match_id,
            "period": 1 if minute < 45 else 2,
            "minute": minute,
            "second": second,
            "team": team,
            "player": player,
            "action": label[0],
            "outcome": label[1],
            "x": None, "y": None,
            "extra": {"video_time": ts_to_clock(sec), "frame": fno}
        }
        self.events.append(event)
        self.info_label.setText(f"Marcado: {event['action']}{('/'+event['outcome']) if event['outcome'] else ''} | {event['extra']['video_time']} | total={len(self.events)}")

    # ---------- Guardado / Navegación ----------
    def save_current(self):
        if not self.current_match_id:
            return
        df = pd.DataFrame(self.events)
        out_xlsx = self.output_dir / f"{Path(self.current_match_id).stem}{self.output_suffix}"
        export_excel(df, out_xlsx)
        QtWidgets.QMessageBox.information(self, "Exportado", f"Excel guardado:\n{out_xlsx.resolve()}")

    def next_video(self):
        # Guardado automático del actual
        if self.cap:
            try:
                df = pd.DataFrame(self.events)
                out_xlsx = self.output_dir / f"{Path(self.current_match_id or 'partido')}{self.output_suffix}"
                export_excel(df, out_xlsx)
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Aviso", f"No se pudo guardar automáticamente:\n{e}")
            self.cap.release()
            self.cap = None

        self.current_video_idx += 1
        if self.current_video_idx >= len(self.videos):
            QtWidgets.QMessageBox.information(self, "Fin", "No hay más videos.")
            return
        path = self.videos[self.current_video_idx]
        mid = None
        if self.match_ids and self.current_video_idx < len(self.match_ids):
            mid = self.match_ids[self.current_video_idx]
        self.open_video(path, mid)

    # Guardar al cerrar
    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self.cap:
            try:
                df = pd.DataFrame(self.events)
                out_xlsx = self.output_dir / f"{Path(self.current_match_id or 'partido')}{self.output_suffix}"
                export_excel(df, out_xlsx)
            except Exception:
                pass
            self.cap.release()
        super().closeEvent(event)


# -------------------- main --------------------
def main():
    try:
        videos, match_ids, output_dir, output_suffix = load_videos_from_env()
    except Exception as e:
        print("Error al cargar .env:", e)
        sys.exit(1)

    app = QtWidgets.QApplication(sys.argv)
    w = AnnotatorWindow(videos, match_ids, output_dir, output_suffix)
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
