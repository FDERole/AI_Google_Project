"""Generate the fictional demo assets: two fan datasheets (PDF) and demo photos (PNG).

Run once: python scripts/make_demo_assets.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
SHEETS = ROOT / "data" / "datasheets"
MEDIA = ROOT / "data" / "demo_media"

DATASHEETS = {
    "kestrel_kx120.pdf": {
        "maker": "Kestrel Air Systems",
        "model": "Kestrel KX-120",
        "title": "Axial Exhaust Fan - Flameproof Series",
        "rows": [
            ("Model", "KX-120"),
            ("Rated airflow", "12,000 m3/h at 250 Pa"),
            ("Motor", "5.5 kW, 415 V, 3-phase, 1440 rpm"),
            ("Hazardous-area marking", "Ex db IIB T4 Gb (Zone 1)"),
            ("Certificate", "PESO/CCOE P-458812"),
            ("Temperature class", "T4"),
            ("Impeller material", "Spark-resistant cast aluminium"),
            ("Casing", "Mild steel, epoxy coated"),
            ("Price (ex-works)", "INR 1,80,000"),
        ],
    },
    "brightline_bf105.pdf": {
        "maker": "Brightline Fans Pvt Ltd",
        "model": "Brightline BF-105",
        "title": "Industrial Axial Fan - Value Series",
        "rows": [
            ("Model", "BF-105"),
            ("Rated airflow", "10,500 m3/h at 250 Pa"),
            ("Motor", "4.0 kW, 415 V, 3-phase, TEFC, 1440 rpm"),
            ("Temperature class", "T3"),
            ("Impeller material", "Mild steel, powder coated"),
            ("Casing", "Mild steel"),
            ("Warranty", "12 months"),
            ("Price (ex-works)", "INR 1,20,000"),
        ],
    },
}


def make_pdf(name, spec):
    c = canvas.Canvas(str(SHEETS / name), pagesize=A4)
    w, h = A4
    c.setFillColorRGB(0.1, 0.2, 0.4)
    c.rect(0, h - 40 * mm, w, 40 * mm, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(20 * mm, h - 20 * mm, spec["maker"])
    c.setFont("Helvetica", 12)
    c.drawString(20 * mm, h - 30 * mm, f'{spec["title"]} - Technical Datasheet')
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, h - 55 * mm, spec["model"])
    y = h - 70 * mm
    for key, val in spec["rows"]:
        c.setFont("Helvetica-Bold", 11)
        c.drawString(20 * mm, y, key)
        c.setFont("Helvetica", 11)
        c.drawString(80 * mm, y, val)
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.line(20 * mm, y - 3 * mm, 190 * mm, y - 3 * mm)
        y -= 10 * mm
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(20 * mm, 15 * mm, "Fictional datasheet generated for the Sanjaya demo. Not a real product.")
    c.save()


def font(size):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def make_alarm_panel():
    img = Image.new("RGB", (900, 600), (60, 64, 70))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((40, 40, 860, 560), 20, fill=(200, 200, 195))
    d.text((70, 60), "DRYER SD-1  ANNUNCIATOR PANEL", fill=(20, 20, 20), font=font(32))
    tiles = [("TAH-301\nINLET TEMP HIGH", (230, 230, 230), "MUTED"),
             ("PAL-302\nN2 PRESSURE LOW", (120, 200, 120), ""),
             ("PDAH-303\nFILTER DP HIGH", (120, 200, 120), ""),
             ("LSH-304\nCYCLONE LEVEL", (120, 200, 120), "")]
    for i, (label, color, tag) in enumerate(tiles):
        x = 70 + (i % 2) * 390
        y = 130 + (i // 2) * 200
        d.rectangle((x, y, x + 360, y + 170), fill=color, outline=(30, 30, 30), width=4)
        d.multiline_text((x + 20, y + 30), label, fill=(20, 20, 20), font=font(28))
        if tag:
            d.rectangle((x + 200, y + 115, x + 350, y + 160), fill=(220, 40, 40))
            d.text((x + 215, y + 120), tag, fill=(255, 255, 255), font=font(28))
    d.text((70, 520), "BYPASS KEY: ON", fill=(200, 30, 30), font=font(26))
    img.save(MEDIA / "alarm_panel_muted.png")


def make_nameplate():
    img = Image.new("RGB", (900, 500), (90, 90, 90))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((60, 60, 840, 440), 16, fill=(205, 205, 210), outline=(40, 40, 40), width=6)
    lines = ["BRIGHTLINE FANS PVT LTD", "MODEL: BF-105", "AIRFLOW: 10500 m3/h",
             "MOTOR: 4.0 kW  415V  TEFC", "TEMP CLASS: T3", "SR NO: BL-24-0917"]
    for i, line in enumerate(lines):
        d.text((100, 90 + i * 55), line, fill=(20, 20, 20), font=font(34))
    img.save(MEDIA / "fan_nameplate_bf105.png")


def main():
    SHEETS.mkdir(parents=True, exist_ok=True)
    MEDIA.mkdir(parents=True, exist_ok=True)
    for name, spec in DATASHEETS.items():
        make_pdf(name, spec)
    make_alarm_panel()
    make_nameplate()
    print("Demo assets written to", SHEETS, "and", MEDIA)


if __name__ == "__main__":
    main()
