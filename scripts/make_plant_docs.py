"""Generate Plant X's (fictional) safety documents as PDFs plus a searchable section index.

Sanjaya quotes these documents with page numbers. They are also the input for the
"Teach Sanjaya your plant" onboarding, where Gemini drafts the risk model from them.

Run: python scripts/make_plant_docs.py
"""
import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = Path(__file__).resolve().parent.parent / "data" / "docs"

# Each document: list of pages; each page: list of sections (id, heading, paragraphs, optional table).
DOCS = [
    {
        "id": "HZ-2024",
        "title": "HAZOP Study Report: Plant X (Spray Drying, Reaction and Solvent Areas)",
        "meta": "Deccan Fine Chem Pvt Ltd (fictional) · Revision 2 · March 2024 · Facilitator: R. Iyer",
        "pages": [
            [
                {"id": "1", "heading": "1. Scope and method",
                 "text": ["This study covers spray dryer SD-1 (dryer house), reactor R-201 (reaction bay) with its "
                          "steam utilities from Boiler B-1, and the solvent room with exhaust fan EF-04. Guidewords "
                          "were applied node by node. Safeguards listed are the independent barriers credited "
                          "against each consequence. Risk was ranked on a 5x5 matrix."]},
                {"id": "2", "heading": "2. Summary of high-risk scenarios",
                 "text": ["Three scenarios ranked High: dust explosion in SD-1 (node SD1-2), runaway reaction in "
                          "R-201 (node R201-1) and solvent vapour fire in the solvent room (node SR1-3). Each "
                          "relies on several safeguards being available at the same time; the study team noted "
                          "that simultaneous impairment of two or more safeguards is not covered by the ranking "
                          "and must be managed through management of change."]},
            ],
            [
                {"id": "SD1-2", "heading": "Node SD1-2: Spray dryer SD-1, drying chamber. Deviation: MORE temperature",
                 "text": ["Consequence: ignition of dried powder cloud leading to dust explosion and fire in the "
                          "dryer house; potential multiple fatalities (Severity 5)."],
                 "table": [["#", "Safeguard (independent barrier)", "Tag / reference"],
                           ["1", "Inlet high-temperature alarm and interlock TAH-301 (trips burner at 180 °C)", "TAH-301"],
                           ["2", "Batch size kept within validated limit of 400 kg per charge", "PV-SD1-2024 Table 3"],
                           ["3", "Nitrogen inerting keeps O2 below 8% in chamber", "PAL-302"],
                           ["4", "Explosion vent panel sized for 400 kg charge dust loading", "EV-SD1"],
                           ["5", "Only trained operators (dryer competency card) run SD-1", "SOP-HR-05"]],
                 "after": ["Recommendation SD1-2.1: any bypass of TAH-301 to be treated as a change requiring "
                           "plant-head approval (see SOP-SD1-03)."]},
            ],
            [
                {"id": "R201-1", "heading": "Node R201-1: Reactor R-201. Deviation: LESS temperature during batch hold",
                 "text": ["Cause: loss of jacket steam from Boiler B-1. Consequence: batch cools below 55 °C; "
                          "dosed reagent accumulates unreacted and can react violently when heating resumes "
                          "(runaway, Severity 5)."],
                 "table": [["#", "Safeguard (independent barrier)", "Tag / reference"],
                           ["1", "Jacket temperature control using steam from Boiler B-1", "TIC-201 / B-1"],
                           ["2", "Reactor high-temperature alarm TAH-201", "TAH-201"],
                           ["3", "Batch size within validated limit", "PV-R201-2023"],
                           ["4", "Only trained operators run R-201", "SOP-HR-05"]],
                 "after": ["Recommendation R201-1.2: maximum allowable steam interruption during batch hold to be "
                           "defined in the operating SOP (implemented as SOP-R201-07 §4.2: 20 minutes)."]},
            ],
            [
                {"id": "SR1-3", "heading": "Node SR1-3: Solvent room. Deviation: LESS ventilation",
                 "text": ["Consequence: toluene vapour accumulates towards its lower explosive limit; ignition "
                          "from electrical equipment or sparks leads to fire or explosion (Severity 5)."],
                 "table": [["#", "Safeguard (independent barrier)", "Tag / reference"],
                           ["1", "Exhaust fan EF-04 delivering at least 12,000 m3/h", "EF-04"],
                           ["2", "Gas detector GD-07 alarms at 20% LEL", "GD-07"],
                           ["3", "Ex-rated electrical equipment for Zone 1, IIB, T4", "AC-SR1"],
                           ["4", "Hot-work permit control", "SOP-MNT-02"]],
                 "after": ["Recommendation SR1-3.2: replacement of EF-04 must be like-for-like on airflow, Ex "
                           "certification, temperature class and spark-resistant impeller (see AC-SR1, "
                           "PS-MECH-11)."]},
            ],
        ],
    },
    {
        "id": "SOP-R201-07",
        "title": "SOP-R201-07: Reactor R-201 Batch Hold and Utility Interruptions",
        "meta": "Rev 4 · Approved by Plant Head · Effective 01-Jun-2024",
        "pages": [
            [
                {"id": "3", "heading": "3. Batch hold",
                 "text": ["During batch hold the reactor contents must stay between 55 °C and 65 °C. The jacket is "
                          "heated with steam from Boiler B-1 under TIC-201 control."]},
                {"id": "4.1", "heading": "4.1 Planned utility interruptions",
                 "text": ["No utility serving R-201 may be interrupted during batch hold without plant-head approval."]},
                {"id": "4.2", "heading": "4.2 Boiler B-1 shutdown during batch hold",
                 "text": ["Boiler B-1 may be shut down for a maximum of 20 minutes while an R-201 batch is in hold. "
                          "Beyond 20 minutes the batch cools below 55 °C and unreacted reagent starts to build up, "
                          "which can run away when heating resumes. The operator shall monitor TI-201 every "
                          "5 minutes and restart B-1 before 20 minutes. If B-1 cannot be restarted, stop reagent "
                          "dosing and inform the plant head immediately."]},
            ],
        ],
    },
    {
        "id": "PV-SD1-2024",
        "title": "Process Validation Report PV-SD1-2024: Spray Dryer SD-1",
        "meta": "Validated batch parameters · QA approved · Jan 2024",
        "pages": [
            [
                {"id": "T3", "heading": "Table 3: Validated operating ranges",
                 "text": ["Batch size above the validated maximum increases dust loading beyond the basis used to "
                          "size explosion vent EV-SD1."],
                 "table": [["Parameter", "Validated range"],
                           ["Batch size per charge", "250 to 400 kg"],
                           ["Inlet air temperature", "150 to 170 °C"],
                           ["Chamber oxygen (inerted)", "below 8%"]]},
            ],
        ],
    },
    {
        "id": "AC-SR1",
        "title": "Area Classification AC-SR1: Solvent Room",
        "meta": "Per IS/IEC 60079-10-1 · Rev 1 · 2023",
        "pages": [
            [
                {"id": "2", "heading": "2. Classification",
                 "text": ["The solvent room is classified Zone 1, gas group IIB, temperature class T4 (toluene). "
                          "All electrical equipment installed in the room must carry a valid Ex certificate for "
                          "Zone 1, gas group IIB or IIC, and temperature class T4 or cooler (T5, T6)."]},
                {"id": "3", "heading": "3. Mechanical equipment (plant standard PS-MECH-11)",
                 "text": ["Fans handling the room atmosphere shall have spark-resistant impellers (aluminium, "
                          "bronze or other non-sparking material). Mild-steel impellers are not permitted."]},
            ],
        ],
    },
    {
        "id": "SOP-SD1-03",
        "title": "SOP-SD1-03: Spray Dryer Alarm Management",
        "meta": "Rev 2 · 2024",
        "pages": [
            [
                {"id": "5.1", "heading": "5.1 Alarm bypass",
                 "text": ["Bypassing or muting TAH-301 is a change to a safety function. It requires a written "
                          "bypass permit approved by the plant head, a named person watching inlet temperature "
                          "locally, and must be removed before the next batch is charged."]},
            ],
        ],
    },
    {
        "id": "SOP-HR-05",
        "title": "SOP-HR-05: Operator Competency and Shift Manning",
        "meta": "Rev 3 · 2024",
        "pages": [
            [
                {"id": "4", "heading": "4. New and trainee operators",
                 "text": ["A trainee may not operate SD-1 or R-201 alone for the first 14 days. On night shift a "
                          "competency-carded operator must be present in the dryer house whenever a trainee is "
                          "rostered."]},
            ],
        ],
    },
]


def build_pdf(doc):
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=16, alignment=0, spaceAfter=4)
    meta = ParagraphStyle("meta", parent=styles["Normal"], fontSize=8, textColor=colors.grey, spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=styles["Heading3"], spaceBefore=8)
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=10, leading=14)
    story = [Paragraph(doc["title"], h1), Paragraph(doc["meta"] + " · FICTIONAL DEMO DOCUMENT", meta)]
    for i, page in enumerate(doc["pages"]):
        if i:
            story.append(PageBreak())
        for sec in page:
            story.append(Paragraph(sec["heading"], h2))
            for t in sec["text"]:
                story.append(Paragraph(t, body))
            if sec.get("table"):
                story.append(Spacer(1, 4))
                tbl = Table([[Paragraph(c, body) for c in row] for row in sec["table"]],
                            colWidths=None, hAlign="LEFT")
                tbl.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#14213d")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c0c4cc")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]))
                story.append(tbl)
            for t in sec.get("after", []):
                story.append(Spacer(1, 4))
                story.append(Paragraph(t, body))

    def footer(canvas, d):
        canvas.setFont("Helvetica", 8)
        canvas.drawString(20 * mm, 10 * mm, f"{doc['id']} · page {d.page}")

    SimpleDocTemplate(str(OUT / f"{doc['id']}.pdf"), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                      topMargin=18 * mm, bottomMargin=18 * mm).build(story, onFirstPage=footer, onLaterPages=footer)


def index_entries(doc):
    for page_no, page in enumerate(doc["pages"], start=1):
        for sec in page:
            parts = [sec["heading"]] + sec["text"]
            if sec.get("table"):
                parts += [" | ".join(row) for row in sec["table"][1:]]
            parts += sec.get("after", [])
            yield {"doc": doc["id"], "title": doc["title"], "page": page_no, "section": sec["id"],
                   "heading": sec["heading"], "text": " ".join(parts)}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for doc in DOCS:
        build_pdf(doc)
        index.extend(index_entries(doc))
    (OUT / "index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(DOCS)} documents, {len(index)} sections -> {OUT}")


if __name__ == "__main__":
    main()
