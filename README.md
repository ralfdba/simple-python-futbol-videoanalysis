# 🎥⚽ Anotador de Jugadas desde Video de Fútbol  

Este proyecto permite **analizar videos de partidos de fútbol** y **etiquetar jugadas manualmente** en tiempo real usando el teclado.  
El sistema detecta cortes de cámara automáticamente (por histograma) y te facilita marcar eventos relevantes (gol, tiro, pase, falta, tarjetas).  
Cada partido se exporta en un archivo **Excel** con las jugadas y un resumen por acción.  

Ideal para **analistas deportivos**, **scouts**, **estudiantes de análisis de datos deportivos** o proyectos de **machine learning** que necesiten datasets de eventos etiquetados.

---

## ✨ Características

- Lectura de rutas de videos desde un archivo **`.env`** (flexible y portable).  
- Procesamiento **interactivo** de múltiples videos en batch.  
- Detección automática de cambios de escena (sugerencias de cortes).  
- Teclado para anotar jugadas:  
  - `g` → Gol  
  - `t` → Tiro  
  - `p` → Pase  
  - `f` → Falta  
  - `o` → Tarjeta Amarilla  
  - `r` → Tarjeta Roja  
  - `q` → Salir / pasar al siguiente video  
- Exporta un Excel con:
  - Hoja `events`: todas las jugadas anotadas  
  - Hoja `summary_actions`: conteo por tipo de acción  

---

## 📦 Instalación

Clona este repositorio y luego instala dependencias:

```bash
git clone https://github.com/ralfdba/simple-python-futbol-videoanalysis.git
cd simple-python-futbol-videoanalysis

pip install -r requirements.txt
```

Dependencias principales:
- `opencv-python`
- `pandas`
- `xlsxwriter`
- `python-dotenv`
- `pillow`
- `PyQt5`

---

## ⚙️ Configuración con `.env`

Crea un archivo `.env` en la raíz del proyecto. Tienes dos opciones:

### Carpeta
```env
VIDEOS_DIR=/ruta/videos
GLOB_PATTERN=*.mp4
OUTPUT_DIR=./exports
FPS_SAMPLE=5
HIST_JUMP=0.6
```

---

## ▶️ Uso

Ejecuta el script principal:

```bash
python anotador_videos.py
```

- Se abrirá una ventana por video.  
- Usa las teclas para marcar jugadas.  
- Presiona **q** para terminar y pasar al siguiente.  
- Los Excel aparecerán en `OUTPUT_DIR`.

---

## 📊 Ejemplo de salida (Excel)

**events**:
| match_id  | period | minute | second | action | outcome     | extra.video_time |
|-----------|--------|--------|--------|--------|-------------|------------------|
| U18_FECHA1| 1      | 12     | 34     | pass   | None        | 00:12:34         |
| U18_FECHA1| 1      | 17     | 05     | shot   | goal        | 00:17:05         |

**summary_actions**:
| action | count |
|--------|-------|
| pass   | 10    |
| shot   | 4     |
| foul   | 2     |

---

## 🔮 Roadmap / Ideas futuras

- Guardar equipo/jugador con input rápido.  
- Modo no interactivo (solo detección de cortes + timestamps).  
- Exportar a formatos estándar (JSON StatsBomb-like).  
- Integrar modelos de visión para sugerir jugadas automáticamente.  

---

## 📜 Licencia

MIT License – libre para usar y modificar.  
