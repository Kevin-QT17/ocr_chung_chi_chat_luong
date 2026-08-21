#!/usr/bin/env python3
"""Tao va kiem tra bo duyet logo chung chi chay cuc bo."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import urllib.parse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


EXPECTED_PRODUCT_COUNT = 304
EXPECTED_IMAGE_COUNT = 827
EXPECTED_DOWNLOADED_COUNT = 723
EXPECTED_IMAGE_STATE_COUNTS = {
    "da_tai": 723,
    "trung_sha256": 102,
    "khong_the_tai_cong_khai": 2,
}
EXPECTED_PRODUCT_CSV_SHA256 = (
    "f92566ecda84c78c4acad23a3a74187ae89bb6ac1331bd16fa5a4d29f03273f0"
)
EXPECTED_IMAGE_CSV_SHA256 = (
    "31b620a47ed6bfc303f22e089edd839cfcc599de4be50a672e2e0f8c8fbdf3c8"
)

PRODUCT_HEADER = (
    "ma_san_pham",
    "ten_san_pham",
    "url_san_pham",
    "so_url_anh_phat_hien",
    "so_anh_tai_thanh_cong",
    "so_anh_trung",
    "so_anh_loi",
    "trang_thai_truy_cap",
    "http_status",
    "ghi_chu",
)
IMAGE_HEADER = (
    "ma_anh",
    "ma_san_pham",
    "thu_tu_anh",
    "ten_file",
    "duong_dan_anh",
    "url_san_pham",
    "url_anh",
    "nguon_phat_hien",
    "la_anh_gallery",
    "http_status",
    "mime_type",
    "kich_thuoc_byte",
    "sha256",
    "trang_thai_tai",
    "la_anh_trung",
    "duong_dan_file_goc",
    "ghi_chu",
)
REVIEW_HEADER = (
    "stt_duyet",
    "ma_anh",
    "ma_san_pham",
    "ten_san_pham",
    "duong_dan_anh",
    "sha256",
    "url_san_pham",
    "url_anh",
    "trang_thai_duyet",
    "logo_quan_sat_duoc",
    "so_logo",
    "chat_luong_anh",
    "ghi_chu",
)
REVIEW_STATES = (
    "chua_duyet",
    "co_logo_chung_chi",
    "khong_co_logo_chung_chi",
    "can_kiem_tra_lai",
)
IMAGE_QUALITIES = (
    "tot",
    "chap_nhan_duoc",
    "mo",
    "qua_nho",
    "bi_che",
    "khong_phu_hop",
)
LOGO_CATALOG = (
    "tcvn",
    "haccp",
    "vietgap",
    "globalgap",
    "fda",
    "ce",
    "oeko_tex",
    "brcgs",
    "rainforest_alliance",
    "ocop",
    "usda_organic",
    "eu_organic",
    "halal",
    "fcc",
    "rohs",
    "gmp",
    "iso_22000",
    "khac",
)
ALLOWED_LABEL_FILES = {"duyet_logo.csv", "duyet_logo.html"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
RESIDUE_SUFFIXES = (".tmp", ".part", ".bak", ".pyc", ".pyo")
DATA_START = '<script id="du-lieu-duyet" type="application/json">'
DATA_END = "</script>"


class ToolError(RuntimeError):
    """Loi du kien, duoc bao gon cho nguoi dung."""


class DataIntegrityError(ToolError):
    """Du lieu dau vao hoac dau ra khong dat rang buoc."""


@dataclass(frozen=True)
class Layout:
    script: Path
    root: Path
    image_root: Path
    table_root: Path
    label_root: Path
    scripts_root: Path
    product_csv: Path
    image_csv: Path
    review_csv: Path
    review_html: Path

    @classmethod
    def from_script(cls) -> "Layout":
        script = Path(__file__).resolve()
        root = script.parent.parent
        data_root = root / "data" / "du_lieu_logo"
        label_root = data_root / "nhan"
        table_root = data_root / "bang_du_lieu"
        return cls(
            script=script,
            root=root,
            image_root=data_root / "anh_goc",
            table_root=table_root,
            label_root=label_root,
            scripts_root=root / "scripts",
            product_csv=table_root / "san_pham.csv",
            image_csv=table_root / "anh.csv",
            review_csv=label_root / "duyet_logo.csv",
            review_html=label_root / "duyet_logo.html",
        )


@dataclass(frozen=True)
class InputData:
    review_rows: tuple[dict[str, str], ...]
    html_records: tuple[dict[str, str], ...]
    product_csv_hash: str
    image_csv_hash: str
    physical_inventory: tuple[tuple[str, int, str], ...]
    dataset_id: str

    @property
    def signature(self) -> tuple[object, ...]:
        return (
            self.product_csv_hash,
            self.image_csv_hash,
            self.physical_inventory,
            self.dataset_id,
        )


HTML_TEMPLATE = r"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' file:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
  <title>Duyệt logo chứng chỉ</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #17211b;
      --muted: #5d6a62;
      --paper: #f5f4ed;
      --card: #fffef9;
      --line: #d8dbd3;
      --forest: #1f5a44;
      --forest-dark: #163d30;
      --amber: #b96518;
      --rose: #a13f43;
      --blue: #365f8b;
      --shadow: 0 16px 45px rgba(30, 45, 36, 0.11);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(circle at 12% 4%, rgba(184, 201, 169, 0.38), transparent 28rem),
        linear-gradient(145deg, #f7f4e9 0%, #eef2ec 100%);
      color: var(--ink);
      font-family: "Segoe UI", Arial, sans-serif;
    }
    button, input, select, textarea { font: inherit; }
    button, select, input, textarea { border-radius: 10px; }
    button { cursor: pointer; }
    button:disabled { cursor: not-allowed; opacity: 0.45; }
    .shell { width: min(1480px, calc(100% - 32px)); margin: 0 auto; padding: 24px 0 40px; }
    .masthead {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 24px;
      margin-bottom: 18px;
    }
    .eyebrow {
      margin: 0 0 5px;
      color: var(--forest);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.15em;
      text-transform: uppercase;
    }
    h1 { margin: 0; font-size: clamp(26px, 4vw, 42px); line-height: 1.05; }
    .subtitle { margin: 8px 0 0; color: var(--muted); }
    .toolbar { display: flex; align-items: flex-end; gap: 10px; flex-wrap: wrap; }
    .field-label {
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.03em;
    }
    select, input, textarea {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      padding: 10px 12px;
      outline: none;
    }
    select:focus, input:focus, textarea:focus {
      border-color: var(--forest);
      box-shadow: 0 0 0 3px rgba(31, 90, 68, 0.12);
    }
    .primary {
      border: 1px solid var(--forest);
      background: var(--forest);
      color: #fff;
      padding: 11px 15px;
      font-weight: 750;
    }
    .primary:hover { background: var(--forest-dark); }
    .stats {
      display: grid;
      grid-template-columns: repeat(6, minmax(105px, 1fr));
      gap: 9px;
      margin-bottom: 14px;
    }
    .stat {
      min-width: 0;
      border: 1px solid rgba(216, 219, 211, 0.9);
      border-radius: 13px;
      background: rgba(255, 254, 249, 0.82);
      padding: 11px 13px;
    }
    .stat span { display: block; color: var(--muted); font-size: 11px; font-weight: 700; }
    .stat strong { display: block; margin-top: 3px; font-size: 23px; }
    .workspace {
      display: grid;
      grid-template-columns: minmax(0, 1.38fr) minmax(340px, 0.86fr);
      gap: 15px;
      align-items: start;
    }
    .panel {
      border: 1px solid rgba(216, 219, 211, 0.9);
      border-radius: 18px;
      background: var(--card);
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    .image-panel { position: sticky; top: 14px; }
    .record-head {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      padding: 17px 18px 13px;
      border-bottom: 1px solid var(--line);
    }
    .record-head h2 { margin: 0; font-size: 20px; }
    .record-head p { margin: 5px 0 0; color: var(--muted); font-size: 13px; }
    .position {
      flex: 0 0 auto;
      border-radius: 999px;
      background: #e8eee8;
      color: var(--forest-dark);
      padding: 7px 10px;
      font-size: 12px;
      font-weight: 800;
    }
    .image-stage {
      position: relative;
      display: grid;
      min-height: min(64vh, 720px);
      place-items: center;
      overflow: hidden;
      background:
        linear-gradient(45deg, #ecece7 25%, transparent 25%),
        linear-gradient(-45deg, #ecece7 25%, transparent 25%),
        linear-gradient(45deg, transparent 75%, #ecece7 75%),
        linear-gradient(-45deg, transparent 75%, #ecece7 75%);
      background-position: 0 0, 0 10px, 10px -10px, -10px 0;
      background-size: 20px 20px;
    }
    #anh-hien-tai {
      display: block;
      width: 100%;
      height: min(64vh, 720px);
      object-fit: contain;
      background: rgba(255, 255, 255, 0.72);
    }
    .image-message {
      position: absolute;
      inset: auto 16px 16px;
      display: none;
      border-radius: 10px;
      background: rgba(23, 33, 27, 0.88);
      color: #fff;
      padding: 9px 12px;
      text-align: center;
      font-size: 13px;
    }
    .image-message.visible { display: block; }
    .trace {
      display: grid;
      gap: 8px;
      padding: 13px 18px 16px;
      border-top: 1px solid var(--line);
      font-size: 12px;
    }
    .trace-row { display: grid; grid-template-columns: 92px minmax(0, 1fr); gap: 10px; }
    .trace-row span:first-child { color: var(--muted); font-weight: 700; }
    .trace-row a, .trace-row code {
      min-width: 0;
      overflow-wrap: anywhere;
      color: var(--blue);
    }
    .form-panel { padding: 18px; }
    .section + .section { margin-top: 19px; padding-top: 18px; border-top: 1px solid var(--line); }
    .section-title { margin: 0 0 10px; font-size: 14px; font-weight: 850; }
    .status-grid { display: grid; gap: 8px; }
    .status-button {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      padding: 11px 12px;
      text-align: left;
      font-weight: 750;
    }
    .status-button:hover { border-color: #a8b5aa; background: #f7f8f4; }
    .status-button.active[data-state="co_logo_chung_chi"] {
      border-color: var(--forest); background: #e4f1e8; color: var(--forest-dark);
    }
    .status-button.active[data-state="khong_co_logo_chung_chi"] {
      border-color: var(--blue); background: #e8eff7; color: #274968;
    }
    .status-button.active[data-state="can_kiem_tra_lai"] {
      border-color: var(--amber); background: #fff0df; color: #7d400c;
    }
    .shortcut { float: right; color: var(--muted); font-size: 11px; font-weight: 600; }
    .logo-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; }
    .logo-option {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 9px;
      padding: 8px 9px;
      background: #fff;
      font-size: 12px;
    }
    .logo-option input { margin: 0; accent-color: var(--forest); }
    .logo-option span { overflow-wrap: anywhere; }
    .two-fields { display: grid; grid-template-columns: 0.7fr 1.3fr; gap: 10px; }
    textarea { min-height: 118px; resize: vertical; line-height: 1.45; }
    .wide { width: 100%; }
    .storage-message {
      display: none;
      margin: 0 0 13px;
      border: 1px solid #e4b78c;
      border-radius: 10px;
      background: #fff1e3;
      color: #704019;
      padding: 9px 11px;
      font-size: 12px;
    }
    .storage-message.visible { display: block; }
    .nav {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 9px;
      margin-top: 18px;
    }
    .nav button {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      padding: 11px 12px;
      font-weight: 750;
    }
    .nav button:hover:not(:disabled) { border-color: var(--forest); color: var(--forest); }
    .empty {
      display: none;
      padding: 50px 24px;
      color: var(--muted);
      text-align: center;
    }
    .empty.visible { display: block; }
    @media (max-width: 980px) {
      .masthead { align-items: flex-start; flex-direction: column; }
      .stats { grid-template-columns: repeat(3, 1fr); }
      .workspace { grid-template-columns: 1fr; }
      .image-panel { position: static; }
      .image-stage, #anh-hien-tai { min-height: 48vh; height: 48vh; }
    }
    @media (max-width: 560px) {
      .shell { width: min(100% - 20px, 1480px); padding-top: 15px; }
      .stats { grid-template-columns: repeat(2, 1fr); }
      .toolbar, .toolbar label, .toolbar select, .toolbar button { width: 100%; }
      .record-head { align-items: flex-start; flex-direction: column; }
      .logo-grid, .two-fields { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="masthead">
      <div>
        <p class="eyebrow">Hathyo · Dữ liệu đã khóa</p>
        <h1>Duyệt logo chứng chỉ</h1>
        <p class="subtitle">Xem từng ảnh gốc, ghi nhận thủ công và xuất đủ dữ liệu khi hoàn tất.</p>
      </div>
      <div class="toolbar">
        <label class="field-label" for="bo-loc">
          Bộ lọc trạng thái
          <select id="bo-loc">
            <option value="tat_ca">Tất cả ảnh</option>
            <option value="chua_duyet">Chưa duyệt</option>
            <option value="co_logo_chung_chi">Có logo</option>
            <option value="khong_co_logo_chung_chi">Không có logo</option>
            <option value="can_kiem_tra_lai">Cần kiểm tra lại</option>
          </select>
        </label>
        <button class="primary" id="xuat-csv" type="button">Xuất CSV kết quả</button>
      </div>
    </header>

    <section class="stats" aria-label="Thống kê tiến độ">
      <div class="stat"><span>Tổng số ảnh</span><strong id="tk-tong">0</strong></div>
      <div class="stat"><span>Đã duyệt</span><strong id="tk-da-duyet">0</strong></div>
      <div class="stat"><span>Chưa duyệt</span><strong id="tk-chua-duyet">0</strong></div>
      <div class="stat"><span>Có logo</span><strong id="tk-co-logo">0</strong></div>
      <div class="stat"><span>Không có logo</span><strong id="tk-khong-logo">0</strong></div>
      <div class="stat"><span>Cần kiểm tra lại</span><strong id="tk-kiem-tra-lai">0</strong></div>
    </section>

    <div id="canh-bao-luu" class="storage-message" role="status"></div>
    <div id="khong-co-ket-qua" class="empty">Không có ảnh phù hợp với bộ lọc hiện tại.</div>

    <section id="khong-gian-duyet" class="workspace">
      <article class="panel image-panel">
        <header class="record-head">
          <div>
            <h2 id="ten-san-pham"></h2>
            <p><span id="ma-anh"></span> · <span id="ma-san-pham"></span></p>
          </div>
          <div id="vi-tri" class="position"></div>
        </header>
        <div class="image-stage">
          <img id="anh-hien-tai" alt="" decoding="async">
          <div id="thong-bao-anh" class="image-message" role="status"></div>
        </div>
        <div class="trace">
          <div class="trace-row"><span>STT duyệt</span><code id="stt-duyet"></code></div>
          <div class="trace-row"><span>SHA-256</span><code id="sha256"></code></div>
          <div class="trace-row"><span>Sản phẩm</span><a id="url-san-pham" target="_blank" rel="noopener noreferrer"></a></div>
          <div class="trace-row"><span>Ảnh nguồn</span><a id="url-anh" target="_blank" rel="noopener noreferrer"></a></div>
        </div>
      </article>

      <aside class="panel form-panel">
        <p id="canh-bao-form" class="storage-message" role="status"></p>

        <section class="section">
          <h3 class="section-title">Kết luận quan sát</h3>
          <div class="status-grid">
            <button class="status-button" data-state="co_logo_chung_chi" type="button">
              Có logo chứng chỉ <span class="shortcut">Phím 1</span>
            </button>
            <button class="status-button" data-state="khong_co_logo_chung_chi" type="button">
              Không có logo chứng chỉ <span class="shortcut">Phím 2</span>
            </button>
            <button class="status-button" data-state="can_kiem_tra_lai" type="button">
              Cần kiểm tra lại <span class="shortcut">Phím 3</span>
            </button>
          </div>
        </section>

        <section class="section">
          <h3 class="section-title">Loại logo quan sát được</h3>
          <div id="danh-muc-logo" class="logo-grid"></div>
        </section>

        <section class="section two-fields">
          <label class="field-label" for="so-logo">
            Số logo
            <input id="so-logo" class="wide" type="number" min="0" step="1" inputmode="numeric" placeholder="Để trống nếu chưa rõ">
          </label>
          <label class="field-label" for="chat-luong-anh">
            Chất lượng ảnh
            <select id="chat-luong-anh" class="wide">
              <option value="">Chưa chọn</option>
              <option value="tot">Tốt</option>
              <option value="chap_nhan_duoc">Chấp nhận được</option>
              <option value="mo">Mờ</option>
              <option value="qua_nho">Quá nhỏ</option>
              <option value="bi_che">Bị che</option>
              <option value="khong_phu_hop">Không phù hợp</option>
            </select>
          </label>
        </section>

        <section class="section">
          <label class="field-label" for="ghi-chu">
            Ghi chú
            <textarea id="ghi-chu" class="wide" placeholder="Nhập nhận xét quan sát..."></textarea>
          </label>
        </section>

        <nav class="nav" aria-label="Điều hướng ảnh">
          <button id="anh-truoc" type="button">← Ảnh trước</button>
          <button id="anh-sau" type="button">Ảnh sau →</button>
        </nav>
      </aside>
    </section>
  </main>

  __DATA_BLOCK__
  <script>
    "use strict";

    const DU_LIEU = JSON.parse(document.getElementById("du-lieu-duyet").textContent);
    const DATASET_ID = "__DATASET_ID__";
    const STORAGE_KEY = "duyet_logo_hathyo_" + DATASET_ID;
    const REVIEW_HEADER = [
      "stt_duyet", "ma_anh", "ma_san_pham", "ten_san_pham",
      "duong_dan_anh", "sha256", "url_san_pham", "url_anh",
      "trang_thai_duyet", "logo_quan_sat_duoc", "so_logo",
      "chat_luong_anh", "ghi_chu"
    ];
    const REVIEW_STATES = [
      "chua_duyet", "co_logo_chung_chi",
      "khong_co_logo_chung_chi", "can_kiem_tra_lai"
    ];
    const IMAGE_QUALITIES = [
      "tot", "chap_nhan_duoc", "mo", "qua_nho",
      "bi_che", "khong_phu_hop"
    ];
    const LOGO_CATALOG = [
      "tcvn", "haccp", "vietgap", "globalgap", "fda", "ce",
      "oeko_tex", "brcgs", "rainforest_alliance", "ocop",
      "usda_organic", "eu_organic", "halal", "fcc", "rohs",
      "gmp", "iso_22000", "khac"
    ];

    const byId = new Map(DU_LIEU.map((record) => [record.ma_anh, record]));
    const editable = Object.create(null);
    let currentId = DU_LIEU.length ? DU_LIEU[0].ma_anh : "";
    let storageAvailable = true;
    let saveTimer = null;

    const elements = {
      filter: document.getElementById("bo-loc"),
      workspace: document.getElementById("khong-gian-duyet"),
      empty: document.getElementById("khong-co-ket-qua"),
      storageMessage: document.getElementById("canh-bao-luu"),
      formMessage: document.getElementById("canh-bao-form"),
      image: document.getElementById("anh-hien-tai"),
      imageMessage: document.getElementById("thong-bao-anh"),
      productName: document.getElementById("ten-san-pham"),
      imageId: document.getElementById("ma-anh"),
      productId: document.getElementById("ma-san-pham"),
      position: document.getElementById("vi-tri"),
      sequence: document.getElementById("stt-duyet"),
      sha: document.getElementById("sha256"),
      productUrl: document.getElementById("url-san-pham"),
      imageUrl: document.getElementById("url-anh"),
      logoGrid: document.getElementById("danh-muc-logo"),
      logoCount: document.getElementById("so-logo"),
      quality: document.getElementById("chat-luong-anh"),
      note: document.getElementById("ghi-chu"),
      previous: document.getElementById("anh-truoc"),
      next: document.getElementById("anh-sau"),
      export: document.getElementById("xuat-csv"),
      total: document.getElementById("tk-tong"),
      reviewed: document.getElementById("tk-da-duyet"),
      pending: document.getElementById("tk-chua-duyet"),
      hasLogo: document.getElementById("tk-co-logo"),
      noLogo: document.getElementById("tk-khong-logo"),
      recheck: document.getElementById("tk-kiem-tra-lai")
    };

    function defaultState() {
      return {
        trang_thai_duyet: "chua_duyet",
        logos: [],
        so_logo: "",
        chat_luong_anh: "",
        ghi_chu: ""
      };
    }

    function cleanState(raw) {
      const clean = defaultState();
      if (!raw || typeof raw !== "object") return clean;
      if (REVIEW_STATES.includes(raw.trang_thai_duyet)) {
        clean.trang_thai_duyet = raw.trang_thai_duyet;
      }
      if (Array.isArray(raw.logos)) {
        const selected = new Set(raw.logos.filter((item) => LOGO_CATALOG.includes(item)));
        clean.logos = LOGO_CATALOG.filter((item) => selected.has(item));
      }
      if (typeof raw.so_logo === "string" && (raw.so_logo === "" || /^\d+$/.test(raw.so_logo))) {
        clean.so_logo = raw.so_logo;
      }
      if (IMAGE_QUALITIES.includes(raw.chat_luong_anh)) {
        clean.chat_luong_anh = raw.chat_luong_anh;
      }
      if (typeof raw.ghi_chu === "string") {
        clean.ghi_chu = raw.ghi_chu;
      }
      return clean;
    }

    function showStorageMessage(message) {
      elements.storageMessage.textContent = message;
      elements.storageMessage.classList.toggle("visible", Boolean(message));
    }

    function loadState() {
      for (const record of DU_LIEU) editable[record.ma_anh] = defaultState();
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return;
        const parsed = JSON.parse(raw);
        if (!parsed || parsed.dataset_id !== DATASET_ID || typeof parsed.rows !== "object") return;
        for (const record of DU_LIEU) {
          if (Object.prototype.hasOwnProperty.call(parsed.rows, record.ma_anh)) {
            editable[record.ma_anh] = cleanState(parsed.rows[record.ma_anh]);
          }
        }
      } catch (error) {
        storageAvailable = false;
        showStorageMessage("Trình duyệt không cho dùng bộ nhớ cục bộ. Tiến độ vẫn có thể xuất CSV trong phiên này.");
      }
    }

    function saveState() {
      if (saveTimer !== null) {
        clearTimeout(saveTimer);
        saveTimer = null;
      }
      if (!storageAvailable) return;
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({
          dataset_id: DATASET_ID,
          rows: editable
        }));
      } catch (error) {
        storageAvailable = false;
        showStorageMessage("Không thể lưu thêm vào bộ nhớ cục bộ. Hãy xuất CSV để giữ kết quả hiện tại.");
      }
    }

    function scheduleSave() {
      if (saveTimer !== null) clearTimeout(saveTimer);
      saveTimer = setTimeout(saveState, 300);
    }

    function filteredRecords() {
      const selected = elements.filter.value;
      if (selected === "tat_ca") return DU_LIEU;
      return DU_LIEU.filter((record) => editable[record.ma_anh].trang_thai_duyet === selected);
    }

    function renderStats() {
      const counts = {
        chua_duyet: 0,
        co_logo_chung_chi: 0,
        khong_co_logo_chung_chi: 0,
        can_kiem_tra_lai: 0
      };
      for (const record of DU_LIEU) counts[editable[record.ma_anh].trang_thai_duyet] += 1;
      elements.total.textContent = String(DU_LIEU.length);
      elements.pending.textContent = String(counts.chua_duyet);
      elements.reviewed.textContent = String(DU_LIEU.length - counts.chua_duyet);
      elements.hasLogo.textContent = String(counts.co_logo_chung_chi);
      elements.noLogo.textContent = String(counts.khong_co_logo_chung_chi);
      elements.recheck.textContent = String(counts.can_kiem_tra_lai);
    }

    function renderLogoCatalog() {
      for (const logo of LOGO_CATALOG) {
        const label = document.createElement("label");
        label.className = "logo-option";
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.value = logo;
        checkbox.addEventListener("change", () => {
          if (!currentId) return;
          editable[currentId].logos = Array.from(
            elements.logoGrid.querySelectorAll('input[type="checkbox"]:checked'),
            (item) => item.value
          );
          saveState();
          updateSemanticWarning();
        });
        const text = document.createElement("span");
        text.textContent = logo;
        label.append(checkbox, text);
        elements.logoGrid.appendChild(label);
      }
    }

    function setLink(element, value) {
      element.textContent = value;
      element.href = value;
      element.title = value;
    }

    function updateSemanticWarning() {
      if (!currentId) {
        elements.formMessage.textContent = "";
        elements.formMessage.classList.remove("visible");
        return;
      }
      const state = editable[currentId];
      const contradictory = (
        state.trang_thai_duyet === "khong_co_logo_chung_chi"
        && (state.logos.length > 0 || (state.so_logo !== "" && state.so_logo !== "0"))
      );
      elements.formMessage.textContent = contradictory
        ? "Trạng thái “không có logo” đang đi cùng lựa chọn logo hoặc số logo khác 0. Dữ liệu vẫn được giữ để bạn tự quyết định."
        : "";
      elements.formMessage.classList.toggle("visible", contradictory);
    }

    function updateStatusButtons() {
      const state = currentId ? editable[currentId].trang_thai_duyet : "";
      for (const button of document.querySelectorAll(".status-button")) {
        button.classList.toggle("active", button.dataset.state === state);
        button.setAttribute("aria-pressed", button.dataset.state === state ? "true" : "false");
      }
    }

    function updateNavigation() {
      const visible = filteredRecords();
      const index = visible.findIndex((record) => record.ma_anh === currentId);
      if (!visible.length) {
        elements.position.textContent = "0 / 0";
        elements.previous.disabled = true;
        elements.next.disabled = true;
        return;
      }
      if (index < 0) {
        elements.position.textContent = "Ngoài bộ lọc · " + visible.length + " ảnh";
        elements.previous.disabled = false;
        elements.next.disabled = false;
        return;
      }
      elements.position.textContent = (index + 1) + " / " + visible.length;
      elements.previous.disabled = index === 0;
      elements.next.disabled = index === visible.length - 1;
    }

    function renderCurrent() {
      const record = byId.get(currentId);
      const visible = filteredRecords();
      const hasData = Boolean(record);
      elements.workspace.style.display = hasData ? "grid" : "none";
      elements.empty.classList.toggle("visible", !hasData && visible.length === 0);
      if (!record) {
        updateNavigation();
        return;
      }

      const state = editable[currentId];
      elements.productName.textContent = record.ten_san_pham;
      elements.imageId.textContent = record.ma_anh;
      elements.productId.textContent = record.ma_san_pham;
      elements.sequence.textContent = record.stt_duyet;
      elements.sha.textContent = record.sha256;
      setLink(elements.productUrl, record.url_san_pham);
      setLink(elements.imageUrl, record.url_anh);

      elements.imageMessage.textContent = "Đang mở ảnh cục bộ…";
      elements.imageMessage.classList.add("visible");
      elements.image.alt = "Ảnh " + record.ma_anh + " của " + record.ten_san_pham;
      elements.image.removeAttribute("src");
      elements.image.src = record.duong_dan_cuc_bo;

      elements.logoCount.value = state.so_logo;
      elements.quality.value = state.chat_luong_anh;
      elements.note.value = state.ghi_chu;
      const selected = new Set(state.logos);
      for (const checkbox of elements.logoGrid.querySelectorAll('input[type="checkbox"]')) {
        checkbox.checked = selected.has(checkbox.value);
      }
      updateStatusButtons();
      updateSemanticWarning();
      updateNavigation();
    }

    function commitCurrentForm() {
      if (!currentId) return;
      const state = editable[currentId];
      state.so_logo = elements.logoCount.value;
      state.chat_luong_anh = elements.quality.value;
      state.ghi_chu = elements.note.value;
    }

    function move(delta) {
      commitCurrentForm();
      saveState();
      const visible = filteredRecords();
      if (!visible.length) return;
      const index = visible.findIndex((record) => record.ma_anh === currentId);
      let targetIndex;
      if (index < 0) targetIndex = delta < 0 ? visible.length - 1 : 0;
      else targetIndex = Math.min(visible.length - 1, Math.max(0, index + delta));
      if (targetIndex === index) return;
      currentId = visible[targetIndex].ma_anh;
      renderCurrent();
    }

    function setStatus(status) {
      if (!currentId || !REVIEW_STATES.includes(status) || status === "chua_duyet") return;
      const visibleBefore = filteredRecords();
      const previousIndex = visibleBefore.findIndex((record) => record.ma_anh === currentId);
      commitCurrentForm();
      editable[currentId].trang_thai_duyet = status;
      saveState();
      const visibleAfter = filteredRecords();
      if (
        elements.filter.value !== "tat_ca"
        && !visibleAfter.some((record) => record.ma_anh === currentId)
      ) {
        if (visibleAfter.length) {
          const nextIndex = Math.min(
            visibleAfter.length - 1,
            Math.max(0, previousIndex)
          );
          currentId = visibleAfter[nextIndex].ma_anh;
        } else {
          currentId = "";
        }
        renderStats();
        renderCurrent();
        return;
      }
      updateStatusButtons();
      updateSemanticWarning();
      renderStats();
      updateNavigation();
    }

    function csvCell(value) {
      const text = String(value === undefined || value === null ? "" : value);
      return '"' + text.replace(/"/g, '""') + '"';
    }

    function exportCsv() {
      commitCurrentForm();
      saveState();
      const lines = [REVIEW_HEADER.map(csvCell).join(",")];
      for (const record of DU_LIEU) {
        const state = editable[record.ma_anh];
        const row = {
          stt_duyet: record.stt_duyet,
          ma_anh: record.ma_anh,
          ma_san_pham: record.ma_san_pham,
          ten_san_pham: record.ten_san_pham,
          duong_dan_anh: record.duong_dan_anh,
          sha256: record.sha256,
          url_san_pham: record.url_san_pham,
          url_anh: record.url_anh,
          trang_thai_duyet: state.trang_thai_duyet,
          logo_quan_sat_duoc: state.logos.join("|"),
          so_logo: state.so_logo,
          chat_luong_anh: state.chat_luong_anh,
          ghi_chu: state.ghi_chu
        };
        lines.push(REVIEW_HEADER.map((field) => csvCell(row[field])).join(","));
      }
      const payload = "\uFEFF" + lines.join("\r\n") + "\r\n";
      const blob = new Blob([payload], { type: "text/csv;charset=utf-8" });
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = "duyet_logo_da_gan_nhan.csv";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    }

    elements.image.addEventListener("load", () => {
      elements.imageMessage.textContent = "";
      elements.imageMessage.classList.remove("visible");
    });
    elements.image.addEventListener("error", () => {
      elements.imageMessage.textContent = "Không thể mở file ảnh cục bộ này.";
      elements.imageMessage.classList.add("visible");
    });
    elements.filter.addEventListener("change", () => {
      commitCurrentForm();
      saveState();
      const visible = filteredRecords();
      currentId = visible.length ? visible[0].ma_anh : "";
      renderCurrent();
    });
    elements.previous.addEventListener("click", () => move(-1));
    elements.next.addEventListener("click", () => move(1));
    elements.export.addEventListener("click", exportCsv);
    elements.logoCount.addEventListener("input", () => {
      if (!currentId) return;
      editable[currentId].so_logo = elements.logoCount.value;
      scheduleSave();
      updateSemanticWarning();
    });
    elements.quality.addEventListener("change", () => {
      if (!currentId) return;
      editable[currentId].chat_luong_anh = elements.quality.value;
      saveState();
    });
    elements.note.addEventListener("input", () => {
      if (!currentId) return;
      editable[currentId].ghi_chu = elements.note.value;
      scheduleSave();
    });
    for (const button of document.querySelectorAll(".status-button")) {
      button.addEventListener("click", () => setStatus(button.dataset.state));
    }
    document.addEventListener("keydown", (event) => {
      if (event.defaultPrevented || event.isComposing || event.repeat) return;
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      const target = event.target;
      if (
        target instanceof Element
        && (target.matches("input, textarea, select") || target.isContentEditable)
      ) return;
      if (event.key === "1") setStatus("co_logo_chung_chi");
      else if (event.key === "2") setStatus("khong_co_logo_chung_chi");
      else if (event.key === "3") setStatus("can_kiem_tra_lai");
      else if (event.key === "ArrowLeft") {
        event.preventDefault();
        move(-1);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        move(1);
      }
    });
    window.addEventListener("beforeunload", () => {
      commitCurrentForm();
      saveState();
    });

    renderLogoCatalog();
    loadState();
    renderStats();
    renderCurrent();
  </script>
</body>
</html>
"""


def print_kv(label: str, value: object) -> None:
    print(f"{label}: {value}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_path(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def read_csv_rows(path: Path, expected_header: Sequence[str]) -> list[dict[str, str]]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig", errors="strict")
    except (OSError, UnicodeError) as exc:
        raise DataIntegrityError(f"Khong doc duoc CSV UTF-8: {path}") from exc
    with io.StringIO(text, newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != tuple(expected_header):
            raise DataIntegrityError(f"Header CSV khong dung quy dinh: {path}")
        rows: list[dict[str, str]] = []
        for line_number, row in enumerate(reader, start=2):
            if None in row or any(row.get(field) is None for field in expected_header):
                raise DataIntegrityError(f"CSV sai so cot tai dong {line_number}: {path}")
            rows.append({field: row.get(field, "") for field in expected_header})
    return rows


def detect_image_magic(path: Path) -> bool:
    with path.open("rb") as stream:
        prefix = stream.read(16)
    return (
        prefix.startswith(b"\xff\xd8\xff")
        or prefix.startswith(b"\x89PNG\r\n\x1a\n")
        or (prefix.startswith((b"GIF87a", b"GIF89a")))
        or prefix.startswith(b"BM")
        or prefix.startswith((b"II*\x00", b"MM\x00*"))
        or (
            len(prefix) >= 12
            and prefix[:4] == b"RIFF"
            and prefix[8:12] == b"WEBP"
        )
    )


def safe_downloaded_path(layout: Layout, raw_path: str, image_id: str) -> Path:
    if not raw_path.strip():
        raise DataIntegrityError(f"Anh da_tai thieu duong_dan_anh: {image_id}")
    source = Path(raw_path)
    if source.is_absolute() or source.drive:
        raise DataIntegrityError(f"Duong dan anh khong duoc la tuyet doi: {image_id}")
    candidate = (layout.root / source).resolve()
    try:
        candidate.relative_to(layout.image_root.resolve())
    except ValueError as exc:
        raise DataIntegrityError(f"Duong dan anh thoat khoi anh_goc: {image_id}") from exc
    if not candidate.is_file():
        raise DataIntegrityError(f"Khong tim thay file anh: {image_id}")
    if candidate.is_symlink():
        raise DataIntegrityError(f"Khong chap nhan symbolic link anh: {image_id}")
    if candidate.suffix.casefold() not in IMAGE_SUFFIXES:
        raise DataIntegrityError(f"Duoi file anh khong hop le: {image_id}")
    return candidate


def html_image_path(layout: Layout, physical_path: Path) -> str:
    relative = physical_path.resolve().relative_to(layout.image_root.resolve())
    local_path = "../anh_goc/" + relative.as_posix()
    return urllib.parse.quote(local_path, safe="/._-")


def ensure_layout(layout: Layout) -> None:
    required_directories = (
        layout.root,
        layout.image_root,
        layout.table_root,
        layout.label_root,
        layout.scripts_root,
    )
    missing = [str(path) for path in required_directories if not path.is_dir()]
    if missing:
        raise DataIntegrityError("Thieu thu muc bat buoc: " + ", ".join(missing))
    for path in (layout.product_csv, layout.image_csv):
        if not path.is_file():
            raise DataIntegrityError(f"Thieu CSV dau vao: {path}")


def ensure_label_scope(layout: Layout, *, require_outputs: bool) -> None:
    children = list(layout.label_root.iterdir())
    unexpected = [path for path in children if path.name not in ALLOWED_LABEL_FILES]
    if unexpected:
        raise DataIntegrityError(
            "Thu muc nhan co tep/thu muc ngoai pham vi: "
            + ", ".join(str(path) for path in unexpected)
        )
    for path in children:
        if path.is_symlink() or not path.is_file():
            raise DataIntegrityError(f"Dau ra duyet khong phai file: {path}")
    if require_outputs:
        missing = [
            str(path)
            for path in (layout.review_csv, layout.review_html)
            if not path.is_file()
        ]
        if missing:
            raise DataIntegrityError("Thieu dau ra bo duyet: " + ", ".join(missing))


def find_residue(layout: Layout) -> list[Path]:
    residue: list[Path] = []
    for path in layout.root.rglob("*"):
        name = path.name.casefold()
        if path.is_dir() and name in {"__pycache__", "cache"}:
            residue.append(path)
        elif path.is_file() and name.endswith(RESIDUE_SUFFIXES):
            residue.append(path)
    return residue


def validate_inputs(layout: Layout) -> InputData:
    ensure_layout(layout)
    product_hash = sha256_file(layout.product_csv)
    image_hash = sha256_file(layout.image_csv)
    if product_hash != EXPECTED_PRODUCT_CSV_SHA256:
        raise DataIntegrityError("SHA-256 san_pham.csv da thay doi so voi bo du lieu khoa")
    if image_hash != EXPECTED_IMAGE_CSV_SHA256:
        raise DataIntegrityError("SHA-256 anh.csv da thay doi so voi bo du lieu khoa")

    products = read_csv_rows(layout.product_csv, PRODUCT_HEADER)
    images = read_csv_rows(layout.image_csv, IMAGE_HEADER)
    if len(products) != EXPECTED_PRODUCT_COUNT:
        raise DataIntegrityError(
            f"san_pham.csv co {len(products)} dong, can {EXPECTED_PRODUCT_COUNT}"
        )
    if len(images) != EXPECTED_IMAGE_COUNT:
        raise DataIntegrityError(
            f"anh.csv co {len(images)} dong, can {EXPECTED_IMAGE_COUNT}"
        )

    product_by_id: dict[str, Mapping[str, str]] = {}
    for product in products:
        product_id = product["ma_san_pham"]
        if not product_id or product_id in product_by_id:
            raise DataIntegrityError(f"ma_san_pham rong hoac trung: {product_id!r}")
        if not product["ten_san_pham"].strip():
            raise DataIntegrityError(f"San pham thieu ten: {product_id}")
        if not product["url_san_pham"].strip():
            raise DataIntegrityError(f"San pham thieu URL: {product_id}")
        product_by_id[product_id] = product

    image_ids: set[str] = set()
    for image in images:
        image_id = image["ma_anh"]
        if not image_id or image_id in image_ids:
            raise DataIntegrityError(f"ma_anh rong hoac trung: {image_id!r}")
        image_ids.add(image_id)
    state_counts = Counter(row["trang_thai_tai"] for row in images)
    if dict(state_counts) != EXPECTED_IMAGE_STATE_COUNTS:
        raise DataIntegrityError(
            "Phan bo trang_thai_tai khong khop bo du lieu khoa: "
            + ", ".join(f"{key}={value}" for key, value in sorted(state_counts.items()))
        )

    downloaded = [row for row in images if row["trang_thai_tai"] == "da_tai"]
    if len(downloaded) != EXPECTED_DOWNLOADED_COUNT:
        raise DataIntegrityError(
            f"So dong da_tai={len(downloaded)}, can {EXPECTED_DOWNLOADED_COUNT}"
        )

    review_rows: list[dict[str, str]] = []
    html_records: list[dict[str, str]] = []
    owned_paths: dict[str, Path] = {}
    stored_hashes: set[str] = set()
    physical_inventory: list[tuple[str, int, str]] = []

    for sequence, image in enumerate(downloaded, start=1):
        image_id = image["ma_anh"]
        product_id = image["ma_san_pham"]
        product = product_by_id.get(product_id)
        if product is None:
            raise DataIntegrityError(f"Anh tham chieu san pham khong ton tai: {image_id}")
        if image["url_san_pham"] != product["url_san_pham"]:
            raise DataIntegrityError(f"url_san_pham khong khop: {image_id}")
        if not image["url_anh"].strip():
            raise DataIntegrityError(f"Anh thieu URL nguon: {image_id}")
        stored_hash = image["sha256"]
        if not re.fullmatch(r"[0-9a-f]{64}", stored_hash):
            raise DataIntegrityError(f"SHA-256 CSV khong hop le: {image_id}")
        if stored_hash in stored_hashes:
            raise DataIntegrityError(f"Trung SHA-256 trong nhom da_tai: {image_id}")
        stored_hashes.add(stored_hash)

        physical_path = safe_downloaded_path(layout, image["duong_dan_anh"], image_id)
        path_key = canonical_path(physical_path)
        if path_key in owned_paths:
            raise DataIntegrityError(
                f"Hai dong da_tai cung tro mot file: {owned_paths[path_key]} va {image_id}"
            )
        owned_paths[path_key] = physical_path
        actual_hash = sha256_file(physical_path)
        if actual_hash != stored_hash:
            raise DataIntegrityError(f"SHA-256 file khong khop CSV: {image_id}")
        if not detect_image_magic(physical_path):
            raise DataIntegrityError(f"Magic bytes anh khong hop le: {image_id}")

        review_row = {
            "stt_duyet": str(sequence),
            "ma_anh": image_id,
            "ma_san_pham": product_id,
            "ten_san_pham": product["ten_san_pham"],
            "duong_dan_anh": image["duong_dan_anh"],
            "sha256": stored_hash,
            "url_san_pham": image["url_san_pham"],
            "url_anh": image["url_anh"],
            "trang_thai_duyet": "chua_duyet",
            "logo_quan_sat_duoc": "",
            "so_logo": "",
            "chat_luong_anh": "",
            "ghi_chu": "",
        }
        review_rows.append(review_row)
        html_record = dict(review_row)
        html_record["duong_dan_cuc_bo"] = html_image_path(layout, physical_path)
        html_records.append(html_record)
        relative_physical = physical_path.resolve().relative_to(layout.root.resolve())
        physical_inventory.append(
            (relative_physical.as_posix(), physical_path.stat().st_size, actual_hash)
        )

    if len(stored_hashes) != EXPECTED_DOWNLOADED_COUNT:
        raise DataIntegrityError("So SHA-256 duy nhat trong da_tai khong bang 723")

    physical_files = sorted(
        path for path in layout.image_root.rglob("*") if path.is_file()
    )
    for path in layout.image_root.rglob("*"):
        if path.is_symlink():
            raise DataIntegrityError(f"Khong chap nhan symbolic link trong anh_goc: {path}")
    physical_keys = {canonical_path(path) for path in physical_files}
    owned_keys = set(owned_paths)
    if len(physical_files) != EXPECTED_DOWNLOADED_COUNT:
        raise DataIntegrityError(
            f"So file vat ly={len(physical_files)}, can {EXPECTED_DOWNLOADED_COUNT}"
        )
    missing_keys = owned_keys - physical_keys
    untracked_keys = physical_keys - owned_keys
    if missing_keys:
        raise DataIntegrityError(f"Co {len(missing_keys)} duong dan anh bi thieu")
    if untracked_keys:
        raise DataIntegrityError(f"Co {len(untracked_keys)} file vat ly ngoai CSV")

    physical_inventory.sort()
    dataset_material = "\n".join(
        f"{row['ma_anh']}|{row['sha256']}" for row in review_rows
    ).encode("utf-8")
    dataset_id = hashlib.sha256(dataset_material).hexdigest()[:20]
    return InputData(
        review_rows=tuple(review_rows),
        html_records=tuple(html_records),
        product_csv_hash=product_hash,
        image_csv_hash=image_hash,
        physical_inventory=tuple(physical_inventory),
        dataset_id=dataset_id,
    )


def build_review_csv_bytes(rows: Sequence[Mapping[str, str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=list(REVIEW_HEADER),
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in REVIEW_HEADER})
    return stream.getvalue().encode("utf-8-sig")


def escaped_json(records: Sequence[Mapping[str, str]]) -> str:
    payload = json.dumps(
        list(records),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        payload.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def build_review_html(data: InputData) -> str:
    data_block = DATA_START + escaped_json(data.html_records) + DATA_END
    return (
        HTML_TEMPLATE.replace("__DATASET_ID__", data.dataset_id)
        .replace("__DATA_BLOCK__", data_block)
    )


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f"{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def validate_review_csv_bytes(
    payload: bytes,
    expected_rows: Sequence[Mapping[str, str]],
) -> None:
    if not payload.startswith(b"\xef\xbb\xbf"):
        raise DataIntegrityError("duyet_logo.csv khong co BOM UTF-8-SIG")
    try:
        text = payload.decode("utf-8-sig", errors="strict")
    except UnicodeError as exc:
        raise DataIntegrityError("duyet_logo.csv khong phai UTF-8-SIG hop le") from exc
    with io.StringIO(text, newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != REVIEW_HEADER:
            raise DataIntegrityError("Header duyet_logo.csv khong dung quy dinh")
        rows = list(reader)
    if len(rows) != EXPECTED_DOWNLOADED_COUNT:
        raise DataIntegrityError(f"duyet_logo.csv co {len(rows)} dong, can 723")
    if len(rows) != len(expected_rows):
        raise DataIntegrityError("So dong duyet khong khop du lieu da_tai")
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    for index, (row, expected) in enumerate(zip(rows, expected_rows), start=1):
        if None in row or any(row.get(field) is None for field in REVIEW_HEADER):
            raise DataIntegrityError(f"duyet_logo.csv sai so cot tai dong {index + 1}")
        clean = {field: row.get(field, "") for field in REVIEW_HEADER}
        if clean != {field: expected.get(field, "") for field in REVIEW_HEADER}:
            raise DataIntegrityError(f"Dong duyet khong khop dau vao: stt {index}")
        if clean["stt_duyet"] != str(index):
            raise DataIntegrityError(f"stt_duyet khong lien tuc tai dong {index + 1}")
        if clean["trang_thai_duyet"] != "chua_duyet":
            raise DataIntegrityError(f"Trang thai ban dau khong phai chua_duyet: {index}")
        if any(
            clean[field]
            for field in (
                "logo_quan_sat_duoc",
                "so_logo",
                "chat_luong_anh",
                "ghi_chu",
            )
        ):
            raise DataIntegrityError(f"Nhan ban dau khong rong: stt {index}")
        seen_ids.add(clean["ma_anh"])
        seen_hashes.add(clean["sha256"])
    if len(seen_ids) != EXPECTED_DOWNLOADED_COUNT:
        raise DataIntegrityError("ma_anh trong duyet_logo.csv khong duy nhat")
    if len(seen_hashes) != EXPECTED_DOWNLOADED_COUNT:
        raise DataIntegrityError("SHA-256 trong duyet_logo.csv khong duy nhat")


def extract_html_records(text: str) -> list[dict[str, str]]:
    start = text.find(DATA_START)
    if start < 0:
        raise DataIntegrityError("HTML thieu khoi metadata duyet")
    content_start = start + len(DATA_START)
    end = text.find(DATA_END, content_start)
    if end < 0:
        raise DataIntegrityError("HTML thieu ket thuc khoi metadata")
    if text.find(DATA_START, content_start) >= 0:
        raise DataIntegrityError("HTML co nhieu khoi metadata duyet")
    try:
        records = json.loads(text[content_start:end])
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DataIntegrityError("Metadata nhung trong HTML khong hop le") from exc
    if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
        raise DataIntegrityError("Metadata HTML khong phai danh sach dong")
    return records


def validate_review_html(
    layout: Layout,
    text: str,
    expected_records: Sequence[Mapping[str, str]],
    dataset_id: str,
) -> None:
    lowered = text.casefold()
    forbidden_patterns = (
        r"data:image",
        r";base64",
        r"<script\b[^>]*\bsrc\s*=",
        r"<link\b",
        r"@import",
        r"url\s*\(\s*['\"]?\s*https?://",
        r"<img\b[^>]*\bsrc\s*=\s*['\"]\s*https?://",
        r"\bfetch\s*\(",
        r"\bxmlhttprequest\b",
        r"\bwebsocket\b",
        r"\bnew\s+image\s*\(",
        r"rel\s*=\s*['\"](?:preload|prefetch)",
    )
    for pattern in forbidden_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            raise DataIntegrityError(f"HTML co tai nguyen/ky thuat bi cam: {pattern}")
    if "connect-src 'none'" not in lowered:
        raise DataIntegrityError("HTML thieu khoa ket noi mang tu dong")
    if len(re.findall(r"<img\b", text, flags=re.IGNORECASE)) != 1:
        raise DataIntegrityError("HTML phai chi co mot phan tu img dong")

    required_tokens = (
        'id="bo-loc"',
        'id="xuat-csv"',
        'id="anh-hien-tai"',
        'id="so-logo"',
        'id="chat-luong-anh"',
        'id="ghi-chu"',
        'id="anh-truoc"',
        'id="anh-sau"',
        "localStorage.getItem",
        "localStorage.setItem",
        "duyet_logo_da_gan_nhan.csv",
        '"ArrowLeft"',
        '"ArrowRight"',
        'target.matches("input, textarea, select")',
        dataset_id,
    )
    for token in required_tokens:
        if token not in text:
            raise DataIntegrityError(f"HTML thieu thanh phan bat buoc: {token}")
    for value in REVIEW_STATES + IMAGE_QUALITIES + LOGO_CATALOG:
        if value not in text:
            raise DataIntegrityError(f"HTML thieu gia tri hop le: {value}")

    records = extract_html_records(text)
    if len(records) != EXPECTED_DOWNLOADED_COUNT:
        raise DataIntegrityError(f"HTML tham chieu {len(records)} anh, can 723")
    if len(records) != len(expected_records):
        raise DataIntegrityError("Metadata HTML khong khop so dong duyet")
    local_paths: set[str] = set()
    for index, (record, expected) in enumerate(
        zip(records, expected_records),
        start=1,
    ):
        if record != dict(expected):
            raise DataIntegrityError(f"Metadata HTML khong khop tai stt {index}")
        local_path = record.get("duong_dan_cuc_bo", "")
        if not local_path.startswith("../anh_goc/") or "\\" in local_path:
            raise DataIntegrityError(f"Duong dan anh HTML khong hop le: stt {index}")
        if local_path in local_paths:
            raise DataIntegrityError(f"Trung tham chieu anh HTML: stt {index}")
        local_paths.add(local_path)
        decoded = urllib.parse.unquote(local_path)
        target = (layout.label_root / Path(decoded)).resolve()
        try:
            target.relative_to(layout.image_root.resolve())
        except ValueError as exc:
            raise DataIntegrityError(
                f"Tham chieu HTML thoat khoi anh_goc: stt {index}"
            ) from exc
        if not target.is_file():
            raise DataIntegrityError(f"Tham chieu HTML thieu file: stt {index}")
    if len(local_paths) != EXPECTED_DOWNLOADED_COUNT:
        raise DataIntegrityError("HTML khong co du 723 tham chieu anh duy nhat")


def validate_outputs(layout: Layout, data: InputData) -> None:
    ensure_label_scope(layout, require_outputs=True)
    try:
        csv_payload = layout.review_csv.read_bytes()
        html_text = layout.review_html.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        raise DataIntegrityError("Khong doc duoc dau ra bo duyet") from exc
    validate_review_csv_bytes(csv_payload, data.review_rows)
    validate_review_html(layout, html_text, data.html_records, data.dataset_id)
    residue = find_residue(layout)
    if residue:
        raise DataIntegrityError(
            "Con file tam/cache: " + ", ".join(str(path) for path in residue)
        )


def run_environment_check(layout: Layout) -> int:
    ensure_layout(layout)
    ensure_label_scope(layout, require_outputs=False)
    for path in (
        layout.root,
        layout.image_root,
        layout.table_root,
        layout.label_root,
        layout.scripts_root,
    ):
        print_kv(f"thu_muc[{path}]", path.is_dir())
    for path in (layout.scripts_root, layout.label_root):
        writable = os.access(path, os.W_OK)
        print_kv(f"quyen_ghi[{path}]", writable)
        if not writable:
            raise DataIntegrityError(f"Khong co quyen ghi thu muc: {path}")
    data = validate_inputs(layout)
    residue = find_residue(layout)
    if residue:
        raise DataIntegrityError(
            "Con file tam/cache: " + ", ".join(str(path) for path in residue)
        )
    print_kv("so_san_pham", EXPECTED_PRODUCT_COUNT)
    print_kv("so_dong_anh", EXPECTED_IMAGE_COUNT)
    print_kv("so_anh_dau_vao", len(data.review_rows))
    print_kv("so_sha256_duy_nhat", len({row["sha256"] for row in data.review_rows}))
    print_kv("so_anh_thieu", 0)
    print_kv("so_file_vat_ly", len(data.physical_inventory))
    print_kv("kiem_tra_tao_file_du_lieu", False)
    print_kv("kiem_tra_moi_truong_hop_le", True)
    return 0


def run_create(layout: Layout) -> int:
    ensure_label_scope(layout, require_outputs=False)
    before = validate_inputs(layout)
    if find_residue(layout):
        raise DataIntegrityError("Phat hien file tam/cache truoc khi tao")

    csv_payload = build_review_csv_bytes(before.review_rows)
    html_text = build_review_html(before)
    validate_review_csv_bytes(csv_payload, before.review_rows)
    validate_review_html(layout, html_text, before.html_records, before.dataset_id)

    atomic_write_bytes(layout.review_csv, csv_payload)
    atomic_write_bytes(layout.review_html, html_text.encode("utf-8"))

    after = validate_inputs(layout)
    if after.signature != before.signature:
        raise DataIntegrityError("Du lieu dau vao thay doi trong khi tao bo duyet")
    validate_outputs(layout, after)
    print_kv("so_anh_dau_vao", len(after.review_rows))
    print_kv("so_dong_csv_duyet", len(after.review_rows))
    print_kv("so_sha256_duy_nhat", len({row["sha256"] for row in after.review_rows}))
    print_kv("so_anh_thieu", 0)
    print_kv("duong_dan_csv", layout.review_csv)
    print_kv("duong_dan_html", layout.review_html)
    print_kv("co_sao_chep_anh", False)
    print_kv("co_file_rac", False)
    print_kv("tao_bo_duyet_hop_le", True)
    return 0


def run_result_check(layout: Layout) -> int:
    data = validate_inputs(layout)
    validate_outputs(layout, data)
    label_images = [
        path
        for path in layout.label_root.rglob("*")
        if path.is_file() and path.suffix.casefold() in IMAGE_SUFFIXES
    ]
    if label_images:
        raise DataIntegrityError(
            "Phat hien anh sao chep trong thu muc nhan: "
            + ", ".join(str(path) for path in label_images)
        )
    print_kv("so_anh_dau_vao", len(data.review_rows))
    print_kv("so_dong_csv_duyet", len(data.review_rows))
    print_kv("so_sha256_duy_nhat", len({row["sha256"] for row in data.review_rows}))
    print_kv("so_anh_thieu", 0)
    print_kv("duong_dan_csv", layout.review_csv)
    print_kv("duong_dan_html", layout.review_html)
    print_kv("co_sao_chep_anh", False)
    print_kv("co_file_rac", False)
    print_kv("ket_qua_hop_le", True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Tao bo duyet thu cong logo chung chi cho 723 anh da_tai."
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--kiem-tra-moi-truong",
        action="store_true",
        help="Kiem tra chi doc toan bo du lieu dau vao.",
    )
    modes.add_argument(
        "--tao-bo-duyet",
        action="store_true",
        help="Tao duyet_logo.csv va duyet_logo.html.",
    )
    modes.add_argument(
        "--kiem-tra-ket-qua",
        action="store_true",
        help="Kiem tra dau vao va hai dau ra bo duyet.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    layout = Layout.from_script()
    try:
        if args.kiem_tra_moi_truong:
            return run_environment_check(layout)
        if args.tao_bo_duyet:
            return run_create(layout)
        return run_result_check(layout)
    except DataIntegrityError as exc:
        print(f"LOI_DU_LIEU: {exc}", file=sys.stderr)
        return 4
    except (OSError, ToolError) as exc:
        print(f"LOI_HE_THONG: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("DA_DUNG: Nguoi dung ngat chuong trinh.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
