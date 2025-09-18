# -*- coding: utf-8 -*-
# GUI de anotación de jugadas con PyQt5
# Novedades:
#  - Botones: «–5s» y «+5s»
#  - Control de velocidad: 0.5x / 1x / 2x
#  - Timeline clicable (slider)
#  - Marcas de eventos (ticks) dibujadas con QPainter sobre el timeline
#
# Atajos:
#   g,t,p,f,o,r: marcar eventos
#   Espacio: Pausa/Reanudar
#   ← / → : –5s / +5s
#   n: Siguiente video
#   s: Guardar Excel

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


# -------------------- Slider clicable con marcas --------------------
class MarkerSlider(QtWidgets.QSlider):
    """
    QSlider horizontal que:
      - Permite click directo para hacer seek
      - Dibuja marcas (ticks) de eventos con QPainter
    """
    clickedValue = QtCore.pyqtSignal(int)

    def __init__(self, orientation=QtCore.Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setMouseTracking(True)
        self.markers: List[int] = []  # frames de eventos
        self._tick_height = 10
        self._tick_pen = QtGui.QPen(QtGui.QColor(255, 70, 70), 2)  # rojo suave
        self._tick_hover_pen = QtGui.QPen(QtGui.QColor(255, 170, 0), 2)  # hover (opcional)
        self._hover = False

    def setMarkers(self, frames: List[int]):
        """Actualiza la lista de frames con marcas y repinta."""
        self.markers = sorted(set(frames))
        self.update()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        self._hover = True
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hover = False
        super().leaveEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            # mapear posición x --> valor (frame)
            groove_left, groove_width = self._groove_geom()
            # evitar división por cero
            if groove_width <= 0 or self.maximum() == self.minimum():
                super().mousePressEvent(event)
                return
            x = event.pos().x()
            # clamp dentro del groove
            x = max(groove_left, min(x, groove_left + groove_width))
            ratio = (x - groove_left) / float(groove_width)
            val = self.minimum() + int(round(ratio * (self.maximum() - self.minimum())))
            self.setValue(val)
            self.clickedValue.emit(val)
            event.accept()
        super().mousePressEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        # Dibujo base del slider
        super().paintEvent(event)

        # Dibuja las marcas encima
        if not self.markers:
            return

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        groove_left, groove_width = self._groove_geom()
        if groove_width <= 0 or self.maximum() == self.minimum():
            return

        # Línea superior discreta (opcional): comentar si no la quieres
        # base_pen = QtGui.QPen(QtGui.QColor(220, 220, 220), 1)
        # painter.setPen(base_pen)
        # painter.drawLine(groove_left, 0, groove_left + groove_width, 0)

        # Selecciona el color según hover
        pen = self._tick_hover_pen if self._hover else self._tick_pen
        painter.setPen(pen)

        # Calcular y dibujar cada tick
        for frame in self.markers:
            frame = max(self.minimum(), min(frame, self.maximum()))
            ratio = (frame - self.minimum()) / float(self.maximum() - self.minimum())
            x = groove_left + int(round(ratio * groove_width))
            # tick vertical de altura _tick_height en la parte superior del widget
            painter.drawLine(x, 0, x, self._tick_height)

        painter.end()

    def _groove_geom(self) -> tuple:
        """
        Devuelve (left_x, width) del groove (canal) del slider,
        para mapear valores -> posiciones en píxeles de forma robusta.
        """
        opt = QtWidgets.QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(QtWidgets.QStyle.CC_Slider, opt,
                                             QtWidgets.QStyle.SC_SliderGroove, self)
        return groove.left(), groove.width()


# -------------------- Ventana principal --------------------
class AnnotatorWindow(QtWidgets.QMainWindow):
    def __init__(self, videos: List[str], match_ids: Optional[List[str]], output_dir: str, output_suffix: str):
        super().__init__()
        self.setWindowTitle("Anotador de Jugadas - PyQt5")
        self.resize(1120, 780)

        self.videos = [Path(v) for v in videos]
        self.match_ids = match_ids or []
        self.output_dir = Path(output_dir)
        self.output_suffix = output_suffix

        self.cap: Optional[cv2.VideoCapture] = None
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._next_frame)
        self.playing = False
        self.playback_speed = 1.0  # 0.5x, 1x, 2x
        self.fps = 25.0
        self.total_frames = 0
        self.current_video_idx = -1
        self.current_match_id: Optional[str] = None
        self.events: List[dict] = []   # cada evento guarda 'extra.frame' con el frame

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

        # Timeline clicable con marcas
        self.timeline = MarkerSlider(QtCore.Qt.Horizontal)
        self.timeline.setMinimum(0)
        self.timeline.setMaximum(1)  # se ajusta al cargar video
        self.timeline.setSingleStep(1)
        self.timeline.clickedValue.connect(self._seek_to_value)
        self.timeline.valueChanged.connect(self._timeline_drag_seek)
        layout.addWidget(self.timeline)

        # Progreso + info
        progress_layout = QtWidgets.QHBoxLayout()
        self.progress = QtWidgets.QProgressBar()
        self.progress.setTextVisible(True)
        self.info_label = QtWidgets.QLabel("Listo")
        self.info_label.setMinimumWidth(320)
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

        # Controles: pausa, salto ±5s, velocidad, siguiente, guardar
        ctrl = QtWidgets.QHBoxLayout()
        self.btn_play = QtWidgets.QPushButton("Pausa (Espacio)")
        self.btn_rew5 = QtWidgets.QPushButton("« –5s")
        self.btn_fwd5 = QtWidgets.QPushButton("+5s »")
        self.speed_label = QtWidgets.QLabel("Velocidad:")
        self.speed_combo = QtWidgets.QComboBox()
        self.speed_combo.addItems(["0.5x", "1x", "2x"])
        self.speed_combo.setCurrentText("1x")
        self.btn_next = QtWidgets.QPushButton("Siguiente (n)")
        self.btn_save = QtWidgets.QPushButton("Guardar (s)")

        for w in [self.btn_play, self.btn_rew5, self.btn_fwd5, self.speed_label, self.speed_combo, self.btn_next, self.btn_save]:
            ctrl.addWidget(w)
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
        self.btn_rew5.clicked.connect(lambda: self._seek_seconds(-5))
        self.btn_fwd5.clicked.connect(lambda: self._seek_seconds(+5))
        self.speed_combo.currentTextChanged.connect(self._change_speed)
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
        QtWidgets.QShortcut(QtGui.QKeySequence("Left"), self, activated=lambda: self._seek_seconds(-5))
        QtWidgets.QShortcut(QtGui.QKeySequence("Right"), self, activated=lambda: self._seek_seconds(+5))

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
        self.timeline.setMaximum(max(1, self.total_frames))
        self.timeline.setValue(0)
        self.timeline.setMarkers([])  # limpiar marcas

        self.info_label.setText(
            f"Video: {path.name} | MATCH_ID: {self.current_match_id} | FPS: {self.fps:.2f} | Frames: {self.total_frames}"
        )

        # Reproducir
        self.playing = True
        self.btn_play.setText("Pausa (Espacio)")
        self._update_timer_interval()
        self.timer.start()
        return True

    def toggle_play(self):
        if not self.cap:
            return
        self.playing = not self.playing
        if self.playing:
            self.btn_play.setText("Pausa (Espacio)")
            self._update_timer_interval()
            self.timer.start()
        else:
            self.btn_play.setText("Reanudar (Espacio)")
            self.timer.stop()

    def _update_timer_interval(self):
        # Intervalo ≈ 1000 / (fps * speed)
        interval = max(1, int(1000 / max(1e-6, self.fps * self.playback_speed)))
        self.timer.setInterval(interval)

    def _change_speed(self, text: str):
        try:
            self.playback_speed = float(text.replace("x", ""))
        except Exception:
            self.playback_speed = 1.0
        self._update_timer_interval()

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

        # Progreso + timeline
        self.progress.setValue(min(self.total_frames, fno))
        self.progress.setFormat(f"{ts_to_clock(sec)}")
        self.timeline.blockSignals(True)
        self.timeline.setValue(min(self.total_frames, fno))
        self.timeline.blockSignals(False)

    # ---------- Seeking ----------
    def _seek_seconds(self, delta_s: int):
        if not self.cap:
            return
        # frame actual
        current_f = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
        # destino
        target_f = int(current_f + delta_s * self.fps)
        self._seek_to_frame(target_f)


    def _seek_to_value(self, frame_val: int):
        # click en timeline
        self._seek_to_frame(frame_val)

    def _timeline_drag_seek(self, frame_val: int):
        # al arrastrar el slider, muestra el frame correspondiente en pausa (scrubbing)
        if not self.cap:
            return
        if not self.playing:
            self._seek_to_frame(frame_val, keep_playing=False)

    def _seek_to_frame(self, frame_idx: int, keep_playing: Optional[bool] = None):
        if not self.cap:
            return
        frame_idx = max(0, min(frame_idx, self.total_frames - 1))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        # fuerza render inmediato
        ok, frame = self.cap.read()
        if ok:
            # retrocede un frame para que el próximo _next_frame no se lo salte
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            sec = frame_idx / max(1e-6, self.fps)
            disp = frame.copy()
            cv2.putText(disp, f"{ts_to_clock(sec)} (frame {frame_idx}/{self.total_frames})",
                        (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255,255,255), 2)
            rgb = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            bytes_per_line = ch * w
            qimg = QtGui.QImage(rgb.data, w, h, bytes_per_line, QtGui.QImage.Format_RGB888)
            pix = QtGui.QPixmap.fromImage(qimg).scaled(960, 540, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            self.video_label.setPixmap(pix)
            self.progress.setValue(frame_idx)
            self.progress.setFormat(f"{ts_to_clock(sec)}")
            self.timeline.blockSignals(True)
            self.timeline.setValue(frame_idx)
            self.timeline.blockSignals(False)

        if keep_playing is not None:
            if keep_playing and not self.playing:
                self.toggle_play()
            elif not keep_playing and self.playing:
                self.toggle_play()

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
        # Actualiza marcas en timeline
        marker_frames = [e["extra"]["frame"] for e in self.events if "extra" in e and "frame" in e["extra"]]
        self.timeline.setMarkers(marker_frames)

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
