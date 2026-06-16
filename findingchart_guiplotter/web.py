from __future__ import annotations

import json
import mimetypes
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .catalog import query_catalog_sources
from .image_fetchers import fetch_image, mode_and_band_from_filter_choice, preferred_filter_choice
from .models import ChartSettings, ImageRequest, Target
from .renderer import export_chart


WEB_OUTPUT_DIR = Path("web_exports")


class FindingChartWebHandler(BaseHTTPRequestHandler):
    server_version = "FindingChartWeb/0.1"

    def do_GET(self) -> None:
        request_path = urlparse(self.path).path
        if request_path in {"/", "/index.html"}:
            self.send_html(INDEX_HTML)
            return
        if request_path.startswith("/exports/"):
            self.send_export(request_path.removeprefix("/exports/"))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path != "/api/render":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self.read_json()
            image_url = render_from_payload(payload)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        self.send_json({"image_url": image_url})

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        return json.loads(body)

    def send_html(self, html: str) -> None:
        encoded = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_json(self, data: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_export(self, filename: str) -> None:
        safe_name = Path(unquote(filename)).name
        path = WEB_OUTPUT_DIR / safe_name
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        payload = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:
        print(f"{self.address_string()} - {format % args}")


def render_from_payload(payload: dict) -> str:
    target = Target(
        display_name=str(payload.get("name") or "Web target"),
        ra_deg=float(payload["ra_deg"]),
        dec_deg=float(payload["dec_deg"]),
    )
    survey = str(payload.get("survey") or "Pan-STARRS")
    filter_choice = str(payload.get("filter") or payload.get("band") or preferred_filter_choice(survey))
    mode, band = mode_and_band_from_filter_choice(survey, filter_choice)
    request = ImageRequest(
        survey=survey,
        mode=mode,
        band=band,
        size_arcmin=float(payload.get("size_arcmin") or 3.0),
        pixel_scale_arcsec=float(payload.get("pixel_scale_arcsec") or 0.262),
    )
    catalog_sources = []
    catalog = str(payload.get("catalog") or "None")
    if catalog != "None":
        catalog_sources = query_catalog_sources(target, request.size_arcmin / 2.0, catalog)
    image = fetch_image(target, request)
    settings = ChartSettings(
        slit_width_arcsec=float(payload.get("slit_width_arcsec") or 2.0),
        slit_length_arcsec=float(payload.get("slit_length_arcsec") or 20.0),
        slit_pa_deg=float(payload.get("slit_pa_deg") or 0.0),
        psf_magnitude=float(payload.get("psf_magnitude") or 18.0),
        psf_model=str(payload.get("psf_model") or "empirical core"),
        show_slit=payload_bool(payload, "show_slit", False),
        show_injected_source=payload_bool(payload, "show_injected_source", True),
        show_crosshair=payload_bool(payload, "show_crosshair", True),
        show_compass=payload_bool(payload, "show_compass", True),
        contrast_stretch=str(payload.get("contrast_stretch") or "arcsinh"),
        contrast_percentile=float(payload.get("contrast_percentile") or 99.3),
        inset_zoom_factor=float(payload.get("inset_zoom_factor") or 6.0),
        catalog_sources=catalog_sources,
    )
    WEB_OUTPUT_DIR.mkdir(exist_ok=True)
    filename = f"finding_chart_{uuid.uuid4().hex}.png"
    export_chart(WEB_OUTPUT_DIR / filename, image, target, settings)
    return f"/exports/{filename}"


def payload_bool(payload: dict, key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run the finding-chart web app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args()

    WEB_OUTPUT_DIR.mkdir(exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), FindingChartWebHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"Serving finding-chart web app at {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Transient Finding Chart</title>
  <style>
    :root { color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f4f5f7; color: #20242a; }
    main { display: grid; grid-template-columns: 360px minmax(0, 1fr); min-height: 100vh; }
    aside { background: #ffffff; border-right: 1px solid #d9dde3; padding: 18px; overflow: auto; }
    section { padding: 22px; overflow: auto; }
    h1 { font-size: 20px; line-height: 1.2; margin: 0 0 18px; }
    fieldset { border: 1px solid #d9dde3; border-radius: 6px; margin: 0 0 14px; padding: 12px; }
    legend { font-size: 12px; font-weight: 700; color: #555f6d; padding: 0 4px; }
    label { display: grid; gap: 4px; font-size: 12px; font-weight: 650; margin: 0 0 10px; }
    input, select { box-sizing: border-box; width: 100%; border: 1px solid #b8c0cc; border-radius: 4px; padding: 8px; font: inherit; background: #fff; }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .check { display: flex; align-items: center; gap: 8px; font-weight: 650; }
    .check input { width: auto; }
    button { width: 100%; border: 0; border-radius: 4px; padding: 10px 12px; background: #b53b32; color: white; font-weight: 800; cursor: pointer; }
    button:disabled { background: #8a9099; cursor: wait; }
    #status { min-height: 20px; margin-top: 10px; color: #555f6d; font-size: 13px; }
    #chart { max-width: min(100%, 1100px); height: auto; background: #15171a; border: 1px solid #2d3238; }
    .empty { display: grid; min-height: calc(100vh - 44px); place-items: center; color: #66707d; border: 1px dashed #c4cad3; border-radius: 6px; }
    @media (max-width: 820px) { main { grid-template-columns: 1fr; } aside { border-right: 0; border-bottom: 1px solid #d9dde3; } }
  </style>
</head>
<body>
  <main>
    <aside>
      <h1>Transient Finding Chart</h1>
      <form id="form">
        <fieldset>
          <legend>Target</legend>
          <label>Name <input name="name" value="SN 2023ixf"></label>
          <label>RA deg <input name="ra_deg" value="210.910675" required></label>
          <label>Dec deg <input name="dec_deg" value="54.311651" required></label>
        </fieldset>
        <fieldset>
          <legend>Image</legend>
          <label>Survey <select name="survey"><option>Pan-STARRS</option><option>Legacy Survey</option><option>DSS2</option><option>2MASS</option></select></label>
          <label>Filter <select name="filter"><option>Color composite</option><option>g</option><option>r</option><option>i</option><option>z</option><option>y</option><option>red</option><option>blue</option><option>ir</option><option>J</option><option>H</option><option>K</option></select></label>
          <label>Stretch <select name="contrast_stretch"><option>arcsinh</option><option>linear</option><option>sqrt</option><option>log</option></select></label>
          <div class="row">
            <label>Field arcmin <input name="size_arcmin" value="3.0"></label>
            <label>Pixscale <input name="pixel_scale_arcsec" value="0.262"></label>
          </div>
          <label>Contrast <input name="contrast_percentile" type="range" min="95.0" max="99.9" step="0.1" value="99.3"></label>
        </fieldset>
        <fieldset>
          <legend>Overlays</legend>
          <label>Catalog <select name="catalog"><option>None</option><option>Gaia DR3</option><option>Pan-STARRS DR2</option><option>Gaia DR3 + Pan-STARRS DR2</option></select></label>
          <label class="check"><input type="checkbox" name="show_injected_source" checked> Inject SN</label>
          <label>SN mag <input name="psf_magnitude" type="number" min="14" max="20" step="0.1" value="18.0"></label>
          <label>PSF model <select name="psf_model"><option>empirical core</option><option>empirical hybrid</option><option>moffat</option></select></label>
          <label>Zoom-in panel <input name="inset_zoom_factor" type="range" min="3" max="12" step="1" value="6"></label>
          <label class="check"><input type="checkbox" name="show_crosshair" checked> Crosshair</label>
          <label class="check"><input type="checkbox" name="show_compass" checked> Compass</label>
          <label class="check"><input type="checkbox" name="show_slit"> Draw slit</label>
          <div class="row">
            <label>Slit PA <input name="slit_pa_deg" value="0.0"></label>
            <label>Width <input name="slit_width_arcsec" value="2.0"></label>
          </div>
          <label>Length <input name="slit_length_arcsec" value="20.0"></label>
        </fieldset>
        <button id="render" type="submit">Render Chart</button>
        <div id="status"></div>
      </form>
    </aside>
    <section>
      <div id="empty" class="empty">Rendered chart will appear here</div>
      <img id="chart" alt="Rendered finding chart" hidden>
    </section>
  </main>
  <script>
    const form = document.getElementById("form");
    const status = document.getElementById("status");
    const button = document.getElementById("render");
    const chart = document.getElementById("chart");
    const empty = document.getElementById("empty");

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = Object.fromEntries(new FormData(form).entries());
      for (const name of ["show_injected_source", "show_crosshair", "show_compass", "show_slit"]) {
        data[name] = form.elements[name].checked;
      }
      button.disabled = true;
      status.textContent = "Rendering...";
      try {
        const response = await fetch("/api/render", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data)
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Render failed");
        chart.src = result.image_url + "?t=" + Date.now();
        chart.hidden = false;
        empty.hidden = true;
        status.textContent = "Rendered " + result.image_url;
      } catch (error) {
        status.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    });
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
