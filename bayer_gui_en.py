#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bayer Channel Extractor (GUI) - Italiano / English

Estrae i canali PURI del mosaico Bayer (nessun demosaicing: ogni canale e'
formato solo dai fotositi di quel colore, quindi meta' risoluzione per lato)
e compone un'immagine RGB a 48 bit con gamma e bilanciamento del bianco.

Extracts the PURE Bayer mosaic channels (no demosaicing: each channel only
contains the photosites of that colour, so half resolution per side) and
builds a 48-bit RGB image with gamma and white balance.

Dependencies / Dipendenze: rawpy, numpy, pillow, tkinterdnd2 (optional, drag&drop)
"""

import os
import queue
import struct
import subprocess
import sys
import threading
import zlib
from collections import OrderedDict

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageTk
import rawpy

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except Exception:  # drag&drop non disponibile: resta il pulsante "Apri"
    HAS_DND = False

RAW_EXT = (
    "*.arw *.srf *.sr2 *.cr2 *.cr3 *.crw *.nef *.nrw *.raf *.orf *.rw2 "
    "*.raw *.dng *.pef *.srw *.3fr *.fff *.iiq *.erf *.mrw *.kdc *.dcr "
    "*.mef *.rwl"
)

# ----------------------------------------------------------------------
#  TRADUZIONI / TRANSLATIONS
# ----------------------------------------------------------------------
LANG = "it"

STR = {
    "it": {
        "title": "Bayer Channel Extractor",
        "open": "Apri RAW…",
        "gamma_h": "Gamma",
        "wb_h": "Bilanciamento del bianco (moltiplicatori)",
        "wb_camera": "Come scattata",
        "wb_neutral": "Neutro",
        "wb_auto": "Auto",
        "protect": "Preserva alte luci (no clipping)",
        "hint": "Suggerimento: clicca sull'immagine su un punto\n"
                "neutro (grigio/bianco) per bilanciare il bianco.",
        "out_h": "Cartella di output",
        "choose": "Scegli…",
        "ch_check": "Canali singoli (R, G1, G2, Gmean, B)",
        "rgb_check": "Immagine RGB 48 bit (WB + gamma)",
        "open_after": "Apri la cartella dopo il salvataggio",
        "save": "Salva",
        "drop_hint": "Trascina qui un file RAW",
        "open_hint": "Apri un file RAW",
        "start_dnd": "Trascina qui un file RAW oppure premi «Apri RAW…»",
        "start_nodnd": "Premi «Apri RAW…» (drag&drop non disponibile)",
        "reading": "Lettura di {0}…",
        "no_wb_cam": "WB della fotocamera non disponibile nel file: impostato neutro.",
        "too_dark": "Punto troppo scuro per bilanciare il bianco.",
        "dlg_open": "Apri file RAW",
        "ft_raw": "File RAW",
        "ft_all": "Tutti i file",
        "dlg_out": "Cartella di output",
        "nothing_sel": "Seleziona almeno un tipo di file da salvare.",
        "save_title": "Salva",
        "saving": "Salvataggio…",
        "writing": "Scrivo {0}…",
        "saved": "Salvati {0} file in {1}",
        "err_title": "Errore",
        "err_short": "Errore.",
        "loaded": "{0}  |  RAW {1}×{2}  |  pattern {3}  |  canali {4}×{5}: {6}",
        "no_rgb": "  |  nessuna combinazione RGB (solo canali singoli)",
        "no_wb": "  |  WB fotocamera non disponibile",
        "e_type": "Tipo di RAW non supportato (non è un mosaico singolo).",
        "e_notmosaic": "Il file non contiene un mosaico grezzo (es. DNG già demosaicato).",
        "e_notbayer": "Sensore non Bayer 2x2 (es. Fujifilm X-Trans): non supportato.",
        "e_levels": "Livelli di nero/bianco non validi nel file.",
    },
    "en": {
        "title": "Bayer Channel Extractor",
        "open": "Open RAW…",
        "gamma_h": "Gamma",
        "wb_h": "White balance (multipliers)",
        "wb_camera": "As shot",
        "wb_neutral": "Neutral",
        "wb_auto": "Auto",
        "protect": "Preserve highlights (no clipping)",
        "hint": "Tip: click on a neutral point (grey/white)\n"
                "in the image to set the white balance.",
        "out_h": "Output folder",
        "choose": "Browse…",
        "ch_check": "Single channels (R, G1, G2, Gmean, B)",
        "rgb_check": "48-bit RGB image (WB + gamma)",
        "open_after": "Open the folder after saving",
        "save": "Save",
        "drop_hint": "Drop a RAW file here",
        "open_hint": "Open a RAW file",
        "start_dnd": "Drop a RAW file here or press “Open RAW…”",
        "start_nodnd": "Press “Open RAW…” (drag&drop not available)",
        "reading": "Reading {0}…",
        "no_wb_cam": "Camera white balance not available in the file: set to neutral.",
        "too_dark": "Point too dark to set the white balance.",
        "dlg_open": "Open RAW file",
        "ft_raw": "RAW files",
        "ft_all": "All files",
        "dlg_out": "Output folder",
        "nothing_sel": "Select at least one type of file to save.",
        "save_title": "Save",
        "saving": "Saving…",
        "writing": "Writing {0}…",
        "saved": "Saved {0} files to {1}",
        "err_title": "Error",
        "err_short": "Error.",
        "loaded": "{0}  |  RAW {1}×{2}  |  pattern {3}  |  channels {4}×{5}: {6}",
        "no_rgb": "  |  no RGB combination (single channels only)",
        "no_wb": "  |  camera white balance not available",
        "e_type": "Unsupported RAW type (not a single flat mosaic).",
        "e_notmosaic": "The file does not contain a raw mosaic (e.g. already demosaiced DNG).",
        "e_notbayer": "Not a 2x2 Bayer sensor (e.g. Fujifilm X-Trans): unsupported.",
        "e_levels": "Invalid black/white levels in the file.",
    },
}


def tr(key, *args):
    s = STR[LANG].get(key) or STR["it"][key]
    return s.format(*args) if args else s


# ----------------------------------------------------------------------
#  CORE
# ----------------------------------------------------------------------
class RawData:
    """Canali lineari normalizzati 0..1 + metadati."""


def load_raw(path):
    with rawpy.imread(path) as raw:
        if raw.raw_type != rawpy.RawType.Flat:
            raise ValueError(tr("e_type"))

        img = raw.raw_image_visible
        pattern = raw.raw_pattern

        if img is None or img.ndim != 2:
            raise ValueError(tr("e_notmosaic"))
        if pattern is None or pattern.shape != (2, 2):
            raise ValueError(tr("e_notbayer"))

        # Colori nella finestra VISIBILE (tiene conto di eventuali margini dispari)
        colors = np.array(raw.raw_colors_visible[:2, :2])

        desc = raw.color_desc
        if isinstance(desc, bytes):
            letters = desc.decode("ascii", errors="ignore")
        else:
            letters = "".join(chr(c) for c in desc if c)

        black = np.asarray(raw.black_level_per_channel, dtype=np.float32)
        white = float(raw.white_level)
        cam = np.asarray(raw.camera_whitebalance, dtype=np.float32)

        h2 = img.shape[0] // 2
        w2 = img.shape[1] // 2
        raw_shape = img.shape

        groups = OrderedDict()
        for y in range(2):
            for x in range(2):
                idx = int(colors[y, x])
                groups.setdefault(letters[idx], []).append((y, x, idx))

        order = [l for l in "RGB" if l in groups] + [l for l in groups if l not in "RGB"]

        channels = OrderedDict()
        for letter in order:
            pos = sorted(groups[letter])
            for n, (y, x, idx) in enumerate(pos):
                name = letter if len(pos) == 1 else f"{letter}{n + 1}"
                bl = float(black[idx]) if idx < black.size else 0.0
                span = white - bl
                if span <= 0:
                    raise ValueError(tr("e_levels"))
                ch = img[y:y + 2 * h2:2, x:x + 2 * w2:2].astype(np.float32)
                ch -= bl
                np.maximum(ch, 0, out=ch)
                ch /= span
                np.minimum(ch, 1, out=ch)
                channels[name] = ch

        pattern_str = "/".join(
            "".join(letters[int(colors[y, x])] for x in range(2)) for y in range(2)
        )

    # WB "come scattata", mappata per LETTERA del colore, normalizzata a G=1
    vals = {}
    for i, v in enumerate(cam):
        if i < len(letters) and v > 0:
            vals.setdefault(letters[i], []).append(float(v))
    as_shot = None
    if all(k in vals for k in "RGB"):
        g = float(np.mean(vals["G"]))
        as_shot = (float(np.mean(vals["R"])) / g, 1.0, float(np.mean(vals["B"])) / g)

    d = RawData()
    d.path = path
    d.channels = channels
    d.as_shot = as_shot
    d.pattern = pattern_str
    d.raw_shape = raw_shape
    d.composite_ok = (
        "R" in channels and "B" in channels and any(k[0] == "G" for k in channels)
    )
    return d


def _reduce(a, f):
    if f == 1:
        return a
    h = a.shape[0] // f * f
    w = a.shape[1] // f * f
    return a[:h, :w].reshape(h // f, f, w // f, f).mean(axis=(1, 3), dtype=np.float32)


def build_preview(d, max_side=1400):
    ch = d.channels
    first = next(iter(ch.values()))
    f = max(1, -(-max(first.shape) // max_side))
    if d.composite_ok:
        r = _reduce(ch["R"], f)
        b = _reduce(ch["B"], f)
        gs = [_reduce(v, f) for k, v in ch.items() if k[0] == "G"]
        g = sum(gs) / len(gs)
    else:
        r = g = b = _reduce(first, f)
    return (r.astype(np.float32, copy=False),
            g.astype(np.float32, copy=False),
            b.astype(np.float32, copy=False))


def green_mean(channels):
    gs = [v for k, v in channels.items() if k[0] == "G"]
    if len(gs) == 1:
        return gs[0]
    return sum(gs) / len(gs)


def compose(r, g, b, wb, gamma, protect):
    """RGB float32 0..1 con WB e gamma. protect=True: scala per il moltiplicatore
    massimo (nessun clipping, esposizione deterministica)."""
    m = np.asarray(wb, dtype=np.float32)
    if protect:
        m = m / float(m.max())
    rgb = np.empty(r.shape + (3,), dtype=np.float32)
    np.multiply(r, m[0], out=rgb[..., 0])
    np.multiply(g, m[1], out=rgb[..., 1])
    np.multiply(b, m[2], out=rgb[..., 2])
    np.clip(rgb, 0.0, 1.0, out=rgb)
    np.power(rgb, 1.0 / gamma, out=rgb)
    return rgb


def to_u16(a):
    a = a * np.float32(65535.0)
    np.rint(a, out=a)
    return a.astype(np.uint16)


def encode_gray16(a, gamma):
    out = np.clip(a, 0.0, 1.0)
    np.power(out, 1.0 / gamma, out=out)
    return to_u16(out)


def _chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data +
            struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def write_png16(path, arr):
    """PNG a 16 bit (grigio o RGB) senza dipendenze esterne."""
    arr = np.ascontiguousarray(arr, dtype=np.uint16)
    if arr.ndim == 2:
        h, w = arr.shape
        ch, ctype = 1, 0
    else:
        h, w, ch = arr.shape
        ctype = 2
    be = arr.astype(">u2").reshape(h, w * ch).view(np.uint8)
    raw = np.zeros((h, 1 + w * ch * 2), dtype=np.uint8)  # 1 byte filtro (0) per riga
    raw[:, 1:] = be
    comp = zlib.compress(raw.reshape(-1).data, 4)
    with open(path, "wb") as fp:
        fp.write(b"\x89PNG\r\n\x1a\n")
        fp.write(_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 16, ctype, 0, 0, 0)))
        fp.write(_chunk(b"IDAT", comp))
        fp.write(_chunk(b"IEND", b""))


def open_folder(path):
    """Apre la cartella nel file manager del sistema."""
    try:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


# ----------------------------------------------------------------------
#  GUI
# ----------------------------------------------------------------------
class App:
    def __init__(self, root):
        self.root = root
        root.geometry("1100x720")
        root.minsize(820, 560)

        self.q = queue.Queue()
        self.data = None
        self.prev = None
        self.photo = None
        self.disp = None
        self.out_user = False
        self.busy = False
        self._after = None
        self._i18n = []          # (widget, chiave, opzione) per il cambio lingua
        self._say_last = ("start_dnd" if HAS_DND else "start_nodnd", ())

        self.gamma = tk.DoubleVar(value=2.2)
        self.wr = tk.DoubleVar(value=1.0)
        self.wg = tk.DoubleVar(value=1.0)
        self.wb_ = tk.DoubleVar(value=1.0)
        self.protect = tk.BooleanVar(value=True)
        self.save_ch = tk.BooleanVar(value=True)
        self.save_rgb = tk.BooleanVar(value=True)
        self.open_after = tk.BooleanVar(value=True)
        self.outdir = tk.StringVar()
        self.status = tk.StringVar()
        self.lang_var = tk.StringVar(value="Italiano")

        self._build()
        self._refresh_texts()
        self.root.after(100, self._poll)

    # ---------------- traduzioni ----------------
    def _t(self, widget, key, opt="text"):
        self._i18n.append((widget, key, opt))
        return widget

    def _refresh_texts(self):
        self.root.title(tr("title"))
        for w, key, opt in self._i18n:
            w.configure(**{opt: tr(key)})
        self._refresh_status()
        self._schedule()

    def _on_lang(self, _e=None):
        global LANG
        LANG = "en" if self.lang_var.get() == "English" else "it"
        self._refresh_texts()

    def _say(self, key, *args):
        self._say_last = (key, args)
        self._refresh_status()

    def _refresh_status(self):
        key, args = self._say_last
        if key == "__loaded__" and self.data is not None:
            self.status.set(self._loaded_msg())
        else:
            self.status.set(tr(key, *args) if key != "__loaded__" else "")

    def _loaded_msg(self):
        d = self.data
        h, w = d.raw_shape
        first = next(iter(d.channels.values()))
        msg = tr("loaded", os.path.basename(d.path), w, h, d.pattern,
                 first.shape[1], first.shape[0], ", ".join(d.channels))
        if not d.composite_ok:
            msg += tr("no_rgb")
        elif not d.as_shot:
            msg += tr("no_wb")
        return msg

    # ---------------- UI ----------------
    def _build(self):
        r = self.root
        r.columnconfigure(0, weight=1)
        r.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(r, bg="#202020", highlightthickness=0,
                                cursor="crosshair")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda e: self._schedule())
        self.canvas.bind("<Button-1>", self._on_click)

        p = ttk.Frame(r, padding=10)
        p.grid(row=0, column=1, sticky="ns")

        top = ttk.Frame(p)
        top.pack(fill="x")
        self._t(ttk.Button(top, command=self._open_dialog), "open").pack(
            side="left", expand=True, fill="x")
        cb = ttk.Combobox(top, textvariable=self.lang_var, state="readonly",
                          values=["Italiano", "English"], width=9)
        cb.pack(side="left", padx=(6, 0))
        cb.bind("<<ComboboxSelected>>", self._on_lang)

        ttk.Separator(p).pack(fill="x", pady=8)
        self._t(ttk.Label(p, font=("", 10, "bold")), "gamma_h").pack(anchor="w")
        self._slider(p, "Gamma", self.gamma, 0.5, 3.5)

        ttk.Separator(p).pack(fill="x", pady=8)
        self._t(ttk.Label(p, font=("", 10, "bold")), "wb_h").pack(anchor="w")
        self._slider(p, "R", self.wr, 0.1, 6.0)
        self._slider(p, "G", self.wg, 0.1, 6.0)
        self._slider(p, "B", self.wb_, 0.1, 6.0)

        bf = ttk.Frame(p)
        bf.pack(fill="x", pady=4)
        self._t(ttk.Button(bf, command=self._wb_camera), "wb_camera").pack(
            side="left", expand=True, fill="x")
        self._t(ttk.Button(bf, command=lambda: self._set_wb((1, 1, 1))), "wb_neutral").pack(
            side="left", expand=True, fill="x")
        self._t(ttk.Button(bf, command=self._wb_auto), "wb_auto").pack(
            side="left", expand=True, fill="x")

        self._t(ttk.Checkbutton(p, variable=self.protect, command=self._schedule),
                "protect").pack(anchor="w", pady=2)
        self._t(ttk.Label(p, foreground="#666"), "hint").pack(anchor="w", pady=(2, 0))

        ttk.Separator(p).pack(fill="x", pady=8)
        self._t(ttk.Label(p, font=("", 10, "bold")), "out_h").pack(anchor="w")
        of = ttk.Frame(p)
        of.pack(fill="x", pady=2)
        ttk.Entry(of, textvariable=self.outdir, width=26).pack(side="left", fill="x", expand=True)
        self._t(ttk.Button(of, command=self._choose_out), "choose").pack(
            side="left", padx=(4, 0))

        self._t(ttk.Checkbutton(p, variable=self.save_ch), "ch_check").pack(anchor="w", pady=(6, 0))
        self._t(ttk.Checkbutton(p, variable=self.save_rgb), "rgb_check").pack(anchor="w")
        self._t(ttk.Checkbutton(p, variable=self.open_after), "open_after").pack(anchor="w")

        self.btn_save = ttk.Button(p, command=self._save, state="disabled")
        self._t(self.btn_save, "save").pack(fill="x", pady=(10, 4))
        self.progress = ttk.Progressbar(p, mode="indeterminate")
        self.progress.pack(fill="x")

        sb = ttk.Label(r, textvariable=self.status, anchor="w", padding=(8, 3), relief="sunken")
        sb.grid(row=1, column=0, columnspan=2, sticky="ew")

    def _slider(self, parent, text, var, lo, hi):
        f = ttk.Frame(parent)
        f.pack(fill="x", pady=2)
        ttk.Label(f, text=text, width=6).pack(side="left")
        val = tk.StringVar(value=f"{var.get():.2f}")
        ttk.Label(f, textvariable=val, width=5, anchor="e").pack(side="right")
        ttk.Scale(f, from_=lo, to=hi, variable=var, orient="horizontal",
                  length=170).pack(side="left", fill="x", expand=True, padx=4)

        def upd(*_):
            val.set(f"{var.get():.2f}")
            self._schedule()
        var.trace_add("write", upd)

    def enable_dnd(self):
        def reg(w):
            try:
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass
            for c in w.winfo_children():
                reg(c)
        reg(self.root)

    # ---------------- parametri ----------------
    def _wb(self):
        return (self.wr.get(), self.wg.get(), self.wb_.get())

    def _gamma(self):
        return max(0.1, float(self.gamma.get()))

    def _set_wb(self, wb):
        lo, hi = 0.1, 6.0
        self.wr.set(float(np.clip(wb[0], lo, hi)))
        self.wg.set(float(np.clip(wb[1], lo, hi)))
        self.wb_.set(float(np.clip(wb[2], lo, hi)))

    def _wb_camera(self):
        if self.data is not None and self.data.as_shot:
            self._set_wb(self.data.as_shot)
        else:
            self._set_wb((1, 1, 1))
            self._say("no_wb_cam")

    def _wb_auto(self):
        if self.prev is None or not self.data.composite_ok:
            return
        r, g, b = (float(a.mean()) for a in self.prev)
        if min(r, g, b) > 1e-6:
            self._set_wb((g / r, 1.0, g / b))

    def _on_click(self, ev):
        if self.prev is None or not self.data.composite_ok or self.disp is None:
            return
        x0, y0, dw, dh = self.disp
        if not (x0 <= ev.x < x0 + dw and y0 <= ev.y < y0 + dh):
            return
        r, g, b = self.prev
        h, w = r.shape
        px = min(w - 1, int((ev.x - x0) / dw * w))
        py = min(h - 1, int((ev.y - y0) / dh * h))
        sl = (slice(max(0, py - 2), py + 3), slice(max(0, px - 2), px + 3))
        mr, mg, mb = (float(a[sl].mean()) for a in (r, g, b))
        if min(mr, mg, mb) <= 1e-5:
            self._say("too_dark")
            return
        self._set_wb((mg / mr, 1.0, mg / mb))

    # ---------------- file ----------------
    def _open_dialog(self):
        p = filedialog.askopenfilename(
            title=tr("dlg_open"),
            filetypes=[(tr("ft_raw"), RAW_EXT), (tr("ft_all"), "*.*")])
        if p:
            self.load(p)

    def _on_drop(self, ev):
        files = self.root.tk.splitlist(ev.data)
        if files:
            self.load(files[0])

    def _choose_out(self):
        d = filedialog.askdirectory(title=tr("dlg_out"),
                                    initialdir=self.outdir.get() or None)
        if d:
            self.outdir.set(d)
            self.out_user = True

    def load(self, path):
        if self.busy:
            return
        self._busy(True, "reading", os.path.basename(path))
        threading.Thread(target=self._load_worker, args=(path,), daemon=True).start()

    def _load_worker(self, path):
        try:
            d = load_raw(path)
            d.preview = build_preview(d)
            self.q.put(("loaded", d))
        except Exception as e:
            self.q.put(("error", f"{type(e).__name__}: {e}"))

    def _save(self):
        if self.data is None or self.busy:
            return
        out = self.outdir.get().strip()
        if not out:
            self._choose_out()
            out = self.outdir.get().strip()
            if not out:
                return
        want_rgb = self.save_rgb.get() and self.data.composite_ok
        if not (self.save_ch.get() or want_rgb):
            messagebox.showinfo(tr("save_title"), tr("nothing_sel"))
            return
        params = dict(out=out, gamma=self._gamma(), wb=self._wb(),
                      protect=self.protect.get(), ch=self.save_ch.get(), rgb=want_rgb,
                      open=self.open_after.get())
        self._busy(True, "saving")
        threading.Thread(target=self._save_worker, args=(self.data, params),
                         daemon=True).start()

    def _save_worker(self, d, p):
        try:
            os.makedirs(p["out"], exist_ok=True)
            base = os.path.splitext(os.path.basename(d.path))[0]
            written = []

            def put(name, arr):
                path = os.path.join(p["out"], f"{base}_{name}.png")
                self.q.put(("status", ("writing", os.path.basename(path))))
                write_png16(path, arr)
                written.append(path)

            if p["ch"]:
                for name, a in d.channels.items():
                    put(name, encode_gray16(a, p["gamma"]))
                if sum(1 for k in d.channels if k[0] == "G") > 1:
                    put("Gmean", encode_gray16(green_mean(d.channels), p["gamma"]))

            if p["rgb"]:
                rgb = compose(d.channels["R"], green_mean(d.channels), d.channels["B"],
                              p["wb"], p["gamma"], p["protect"])
                put("RGB48_WB", to_u16(rgb))

            self.q.put(("saved", (p["out"], len(written), p["open"])))
        except Exception as e:
            self.q.put(("error", f"{type(e).__name__}: {e}"))

    # ---------------- coda eventi ----------------
    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "loaded":
                    self._on_loaded(payload)
                elif kind == "status":
                    self._say(payload[0], *payload[1:])
                elif kind == "saved":
                    out, n, do_open = payload
                    self._busy(False, "saved", n, out)
                    if do_open:
                        open_folder(out)
                elif kind == "error":
                    self._busy(False, "err_short")
                    messagebox.showerror(tr("err_title"), payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _on_loaded(self, d):
        self.data = d
        self.prev = d.preview
        if not self.out_user:
            self.outdir.set(os.path.dirname(os.path.abspath(d.path)))
        self._set_wb(d.as_shot if d.as_shot else (1, 1, 1))
        self._busy(False, "__loaded__")
        self._schedule()

    def _busy(self, flag, key, *args):
        self.busy = flag
        self._say(key, *args)
        if flag:
            self.progress.start(12)
            self.btn_save.state(["disabled"])
        else:
            self.progress.stop()
            self.btn_save.state(["!disabled"] if self.data is not None else ["disabled"])

    # ---------------- anteprima ----------------
    def _schedule(self):
        if self._after is None:
            self._after = self.root.after(30, self._redraw)

    def _redraw(self):
        self._after = None
        c = self.canvas
        c.delete("all")
        cw, ch = c.winfo_width(), c.winfo_height()
        if self.prev is None:
            c.create_text(cw // 2, ch // 2, fill="#9a9a9a", font=("", 16), justify="center",
                          text=tr("drop_hint") if HAS_DND else tr("open_hint"))
            return
        r, g, b = self.prev
        rgb = compose(r, g, b, self._wb() if self.data.composite_ok else (1, 1, 1),
                      self._gamma(), self.protect.get())
        im = Image.fromarray((rgb * 255.0 + 0.5).astype(np.uint8))
        s = min(max(cw, 1) / im.width, max(ch, 1) / im.height, 1.0)
        dw, dh = max(1, int(im.width * s)), max(1, int(im.height * s))
        if (dw, dh) != im.size:
            im = im.resize((dw, dh), Image.BILINEAR)
        x0, y0 = (cw - dw) // 2, (ch - dh) // 2
        self.photo = ImageTk.PhotoImage(im)
        c.create_image(x0, y0, anchor="nw", image=self.photo)
        self.disp = (x0, y0, dw, dh)


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
    app = App(root)
    if HAS_DND:
        app.enable_dnd()
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        root.after(200, lambda: app.load(sys.argv[1]))
    root.mainloop()


if __name__ == "__main__":
    main()
