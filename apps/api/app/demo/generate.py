"""Generates synthetic sample documents for every persona into apps/api/samples/<persona>/.

    uv run python -m app.demo.generate

Each file is clearly watermarked "SPECIMEN - SYNTHETIC" and contains no government emblems. The ground truth is
embedded (PNG text chunk / PDF Subject) so the platform can run offline without an LLM key."""

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from PIL.PngImagePlugin import PngInfo

from app.demo.personas import PERSONAS, sample_filename

OUT = Path(__file__).resolve().parents[2] / "samples"
INK = (30, 41, 59)
MUTED = (100, 116, 139)
ACCENT = (217, 72, 15)


def font(size: int, bold: bool = False):
    names = (["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else []) + ["arial.ttf", "DejaVuSans.ttf"]
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def watermark(img: Image.Image) -> Image.Image:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = font(int(img.width / 14), bold=True)
    text = "SPECIMEN - SYNTHETIC"
    for y in range(-img.height, img.height * 2, int(img.width / 4)):
        tile = Image.new("RGBA", (img.width * 2, int(img.width / 10)), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((0, 0), text + "      " + text, font=f, fill=(217, 72, 15, 38))
        tile = tile.rotate(25, expand=True)
        layer.alpha_composite(tile, (-img.width // 3, y))
    d.rectangle([0, 0, img.width - 1, img.height - 1], outline=(203, 213, 225, 255), width=3)
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def field(d, x, y, label, value, size=28):
    d.text((x, y), label.upper(), font=font(int(size * 0.6)), fill=MUTED)
    d.text((x, y + int(size * 0.8)), value, font=font(size, bold=True), fill=INK)


def pan_card(form: dict, spec: dict) -> Image.Image:
    img = Image.new("RGB", (1012, 638), (236, 244, 250))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1012, 92], fill=(30, 64, 120))
    d.text((32, 22), "PERMANENT ACCOUNT NUMBER CARD", font=font(34, True), fill="white")
    d.text((32, 100), "Synthetic specimen for MapleLaunch demos. Not a government document.", font=font(18), fill=MUTED)
    d.rectangle([780, 150, 960, 370], outline=MUTED, width=3)
    d.text((818, 250), "PHOTO", font=font(28), fill=MUTED)
    field(d, 40, 160, "Name", spec["name"])
    field(d, 40, 260, "Date of birth / incorporation", spec["dob"].split("-")[2] + "/" + spec["dob"].split("-")[1]
          + "/" + spec["dob"].split("-")[0])
    field(d, 40, 380, "Permanent Account Number", form["pan"], size=46)
    d.text((40, 560), "Signature: ___________________", font=font(22), fill=MUTED)
    return img


def gst_certificate(form: dict, spec: dict) -> Image.Image:
    img = Image.new("RGB", (1240, 1650), "white")
    d = ImageDraw.Draw(img)
    d.text((80, 70), "Registration Certificate", font=font(52, True), fill=INK)
    d.text((80, 140), "Goods and Services Tax, Form REG-06 (synthetic specimen)", font=font(26), fill=MUTED)
    d.line([80, 200, 1160, 200], fill=ACCENT, width=4)
    gstin = spec.get("gstin") or form["gstin"]
    rows = [("Registration Number (GSTIN)", gstin), ("1. Legal Name", spec["legal_name"]),
            ("2. Trade Name, if any", spec["trade_name"]), ("3. Constitution of Business", spec["constitution"]),
            ("4. Address of Principal Place of Business", spec["address"]),
            ("5. Date of Liability", spec["date"]), ("6. Type of Registration", "Regular"),
            ("7. Registration Status", "Active")]
    y = 250
    for label, value in rows:
        d.text((80, y), label, font=font(24), fill=MUTED)
        d.text((80, y + 36), value, font=font(32, True), fill=INK)
        y += 130
    d.text((80, 1500), "This is a system-generated specimen for testing. Not valid for any purpose.",
           font=font(22), fill=MUTED)
    return img


def cheque(form: dict, spec: dict) -> Image.Image:
    img = Image.new("RGB", (1400, 640), (248, 250, 252))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1400, 110], fill=(241, 245, 249))
    d.text((40, 30), form["bank_name"].upper(), font=font(44, True), fill=(30, 64, 120))
    d.text((900, 40), f"IFSC: {form['ifsc']}", font=font(32, True), fill=INK)
    d.text((40, 160), "Pay ____________________________________________   or Bearer", font=font(30), fill=MUTED)
    d.text((40, 240), "Rupees __________________________________________", font=font(30), fill=MUTED)
    d.rectangle([1050, 220, 1340, 290], outline=MUTED, width=2)
    d.text((40, 340), f"A/c No.  {form['account_number']}", font=font(40, True), fill=INK)
    d.text((40, 420), form["account_holder_name"].upper(), font=font(32, True), fill=INK)
    d.text((40, 560), f"C{random.randint(100000, 999999)}C  560002057A  000123C  29", font=font(30), fill=MUTED)
    d.line([300, 120, 900, 600], fill=(220, 38, 38), width=8)
    d.line([360, 120, 960, 600], fill=(220, 38, 38), width=8)
    d.text((520, 300), "CANCELLED", font=font(70, True), fill=(220, 38, 38))
    return img


def coi(form: dict, spec: dict) -> Image.Image:
    img = Image.new("RGB", (1240, 1650), "white")
    d = ImageDraw.Draw(img)
    d.text((80, 80), "Certificate of Incorporation", font=font(52, True), fill=INK)
    d.text((80, 150), "Registrar of Companies (synthetic specimen)", font=font(26), fill=MUTED)
    d.line([80, 210, 1160, 210], fill=ACCENT, width=4)
    body = [f"I hereby certify that {spec['company_name']} is incorporated on",
            f"{spec['date']} under the Companies Act, 2013 (18 of 2013) and that",
            "the company is limited by shares.", ""]
    y = 270
    for line in body:
        d.text((80, y), line, font=font(30), fill=INK)
        y += 52
    field(d, 80, 520, "Corporate Identity Number (CIN)", spec["cin"], size=40)
    field(d, 80, 660, "Permanent Account Number (PAN) of the company", form["pan"], size=40)
    d.text((80, 1500), "Specimen for testing only. Not valid for any purpose.", font=font(22), fill=MUTED)
    return img


def deed(form: dict, spec: dict) -> Image.Image:
    img = Image.new("RGB", (1240, 1650), (255, 253, 245))
    d = ImageDraw.Draw(img)
    d.text((80, 80), "Deed of Partnership", font=font(52, True), fill=INK)
    d.text((80, 150), "Synthetic specimen", font=font(26), fill=MUTED)
    d.line([80, 210, 1160, 210], fill=ACCENT, width=4)
    lines = [f"This deed of partnership is executed on 20-02-2015 at {form['city']} between:", "",
             "1. Kiran Mehta, residing at Mumbai (First Partner)", "2. Suresh Mehta, residing at Mumbai (Second Partner)",
             "", "The partners agree to carry on business under the name and style of",
             f"{form['legal_name'].upper()}", f"at {form['address']}, {form['city']}.", "",
             "Profit sharing ratio: 50 : 50.", "Bank operations: jointly by both partners."]
    y = 270
    for line in lines:
        d.text((80, y), line, font=font(30, bold=line.isupper()), fill=INK)
        y += 52
    d.text((80, 1300), "Partner 1: __________        Partner 2: __________", font=font(28), fill=MUTED)
    return img


DRAWERS = {"pan": pan_card, "gst": gst_certificate, "cheque": cheque, "coi": coi, "deed": deed}


def ground_truth(slot: str, form: dict, spec: dict) -> dict:
    blur = spec.get("blur", False)
    conf = 0.42 if blur else 0.97
    kind = spec["kind"]
    if kind == "pan":
        fields = {"pan_number": form["pan"], "name": spec["name"], "date_of_birth": spec["dob"]}
    elif kind == "gst":
        fields = {"gstin": spec.get("gstin") or form["gstin"], "legal_name": spec["legal_name"],
                  "trade_name": spec["trade_name"], "constitution": spec["constitution"],
                  "registration_date": spec["date"], "address": spec["address"], "state": form["state"]}
    elif kind == "cheque":
        fields = {"account_number": form["account_number"], "ifsc": form["ifsc"],
                  "account_holder_name": form["account_holder_name"].upper(), "bank_name": form["bank_name"]}
    elif kind == "coi":
        fields = {"cin": spec["cin"], "company_name": spec["company_name"], "incorporation_date": spec["date"]}
    else:
        fields = {"firm_name": form["legal_name"].upper(), "partners": "Kiran Mehta, Suresh Mehta",
                  "execution_date": "2015-02-20"}
    return {
        "detected_type": slot,
        "quality": {"score": 0.32 if blur else 0.95, "legible": not blur, "blur": "severe" if blur else "none",
                    "cropped": False, "notes": "Heavy motion blur; text unreadable" if blur else "Clear scan"},
        "fields": {k: {"value": v, "confidence": conf} for k, v in fields.items()},
        "suspicious": False, "suspicion_notes": "",
    }


def write(path: Path, img: Image.Image, truth: dict, pdf: bool) -> None:
    payload = json.dumps(truth)
    if pdf:
        img.save(path, "PDF", resolution=150, subject=payload, title="MapleLaunch synthetic specimen")
    else:
        info = PngInfo()
        info.add_text("maplelaunch", payload)
        img.save(path, "PNG", pnginfo=info, optimize=True)


def main() -> None:
    random.seed(7)
    for key, persona in PERSONAS.items():
        folder = OUT / key
        folder.mkdir(parents=True, exist_ok=True)
        form = persona["form"]
        variants = [(persona["documents"], form, False)]
        if persona.get("fix"):
            variants.append((persona["fix"]["documents"], {**form, **persona["fix"]["form"]}, True))
        for docs, f, fixed in variants:
            for slot, spec in docs.items():
                img = watermark(DRAWERS[spec["kind"]](f, spec))
                if spec.get("blur"):
                    img = img.filter(ImageFilter.GaussianBlur(radius=9))
                write(folder / sample_filename(slot, spec, fixed), img, ground_truth(slot, f, spec), spec.get("pdf", False))
        print(f"ok {key}: {sorted(p.name for p in folder.iterdir())}")


if __name__ == "__main__":
    main()
