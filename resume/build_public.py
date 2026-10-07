"""Builds an ATS-friendly resume (DOCX + PDF). Edit the content below and re-run."""

import subprocess
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

OUT = Path(__file__).resolve().parent.parent / "site" / "Akhil_Birru_Resume.docx"  # public copy, no phone

NAME = "Akhil Birru"
TITLE = "Full Stack Developer | Angular · Spring Boot · PostgreSQL · AI / LLM (Claude)"
CONTACT = "Bengaluru, India | birruakhil1526@gmail.com | linkedin.com/in/akhil-birru | github.com/birruakhil1526"

SUMMARY = (
    "Full Stack Developer with 5+ years of experience building scalable, production-grade web applications "
    "across frontend, backend, and AI-driven workflows. Strong in Angular (up to v21), TypeScript, and RxJS, with "
    "hands-on Java, Spring Boot, PostgreSQL, and YugabyteDB experience. Built AI-powered developer tools using LLMs (Claude) for automated "
    "test generation and bug resolution. Led a development team, implemented secure Single Sign-On (SSO), and drove "
    "architecture decisions that improved performance, scalability, and maintainability."
)

HIGHLIGHTS = [
    "Built AiTDP features – an in-house Claude (LLM) orchestration platform for AI test generation and automated bug fixing.",
    "Full stack ownership of epics on fintech lending products (LOS, LMS, Collections): Spring Boot, PostgreSQL/YugabyteDB, Angular.",
    "Implemented secure Single Sign-On (SSO) and led a development team; recognised with a Certificate of Appreciation.",
]

SKILLS = [
    ("Frontend", "Angular (up to v21), TypeScript, JavaScript, RxJS, ReactJS, Redux, HTML5, CSS3, SCSS, Angular Material, Bootstrap"),
    ("Backend", "Java, Spring Boot, CRON / scheduled jobs, Node.js, RESTful APIs, Swagger"),
    ("AI / LLM", "LLM workflow orchestration, Claude API, prompt engineering, AI-powered developer tools, editor plugins"),
    ("Databases", "PostgreSQL, YugabyteDB (distributed SQL), SQL, MongoDB"),
    ("Testing", "Karma, Jasmine, unit testing"),
    ("Tools & DevOps", "Git, Jenkins, Docker, Jira, VS Code, IntelliJ"),
    ("Practices", "System design, SSO / authentication, role-based access control, lazy loading, Agile / Scrum, code reviews"),
]

EXPERIENCE = [
    {
        "company": "Trustt",
        "role": "Senior Software Engineer",
        "dates": "Oct 2024 – Present",
        "location": "Bengaluru",
        "bullets": [
            "Delivered features across 3 fintech lending products – Loan Origination (LOS), Loan Management (LMS), and "
            "Loan Collection System (LCS) – plus AiTDP, an in-house AI (Claude) orchestration platform.",
            "AiTDP: independently designed and built an AI system that generates unit test cases for Java, Angular, and "
            "Android applications, delivered as editor plugins for developers.",
            "AiTDP: architected an LLM-based (Claude) workflow that automates bug detection and resolution, reducing manual "
            "debugging effort for the engineering team.",
            "Own epics end to end – Spring Boot backend services with PostgreSQL and YugabyteDB, plus the supporting Angular UI.",
            "Built and maintained scheduled CRON jobs in Spring Boot for automated backend batch processing.",
            "Developed complex Angular modules (65+ lazy-loaded features) with reusable base classes for CRUD, "
            "maker-checker approval workflows, and role-based permissions.",
        ],
    },
    {
        "company": "Maveric Systems",
        "role": "Software Developer",
        "dates": "Mar 2023 – Sep 2024",
        "location": "Bengaluru",
        "project": "Delivery Excellence Dashboard – platform for employees to report project status and feedback, "
                   "with scoring and stakeholder tracking.",
        "bullets": [
            "Designed and developed critical modules from the ground up, including secure Single Sign-On (SSO).",
            "Led a development team for 3 months as Lead Engineer, delivering all planned tasks on schedule.",
            "Drove architecture decisions and fixed performance bottlenecks, improving load times, scalability, and maintainability.",
            "Built responsive Angular interfaces from UX/UI wireframes and integrated RESTful APIs and third-party services.",
            "Conducted code reviews and mentored junior developers on Angular best practices and coding standards.",
            "Received a Certificate of Appreciation for outstanding contribution and leadership on the project.",
        ],
    },
    {
        "company": "Accenture",
        "role": "Associate – Backend Developer",
        "dates": "Apr 2021 – Oct 2022",
        "location": "Hyderabad",
        "project": "Inventory and supply-chain web application for an international agricultural company – tracking "
                   "product stock, items in transit, material storage, and processing stages.",
        "bullets": [
            "Developed backend services and RESTful APIs in Java and Spring Boot for inventory, in-transit tracking, "
            "and material processing modules.",
            "Wrote SQL queries and data access logic for product stock, storage, and processing data.",
            "Worked closely with frontend developers and designers to define API contracts and integrate services end to end.",
            "Documented APIs (Swagger) and technical specifications to support knowledge sharing and project continuity.",
        ],
    },
]

EDUCATION = [
    ("B.Tech, Electronics and Communication Engineering", "Christu Jyothi Institute of Technology and Science", "2015 – 2019"),
]

CERTIFICATIONS = "PGP Full Stack Software Engineering; Angular; Java; JavaScript; SQL"


# ---------- layout ----------

FONT = "Calibri"


def set_font(run, size, bold=False):
    run.font.name = FONT
    run.font.size = Pt(size)
    run.bold = bold


def spacing(p, before=0, after=2):
    p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.space_after = Pt(after)


def bottom_border(p):
    pPr = p._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    line = OxmlElement("w:bottom")
    for k, v in {"val": "single", "sz": "6", "space": "1", "color": "444444"}.items():
        line.set(qn(f"w:{k}"), v)
    bdr.append(line)
    pPr.append(bdr)


def heading(doc, text):
    p = doc.add_paragraph()
    spacing(p, before=8, after=3)
    set_font(p.add_run(text.upper()), 11.5, bold=True)
    bottom_border(p)


def text_line(doc, text, size=10.5, bold=False, after=2):
    p = doc.add_paragraph()
    spacing(p, after=after)
    set_font(p.add_run(text), size, bold)
    return p


def bullet(doc, text):
    # Plain "•" in the body font; Word's list bullets use a symbol font that ATS reads as junk.
    p = doc.add_paragraph()
    spacing(p, after=1)
    p.paragraph_format.left_indent = Inches(0.25)
    p.paragraph_format.first_line_indent = Inches(-0.15)
    set_font(p.add_run("• " + text), 10.5)


def job_header(doc, left, right):
    # Right-aligned dates via a tab stop (no tables, ATS-safe).
    p = doc.add_paragraph()
    spacing(p, before=4, after=1)
    p.paragraph_format.tab_stops.add_tab_stop(Inches(7.0), alignment=2)
    set_font(p.add_run(left), 11, bold=True)
    set_font(p.add_run("\t" + right), 10.5, bold=True)


def build():
    doc = Document()
    for s in doc.sections:
        s.top_margin = s.bottom_margin = Inches(0.6)
        s.left_margin = s.right_margin = Inches(0.75)
    doc.styles["Normal"].font.name = FONT

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    spacing(p, after=0)
    set_font(p.add_run(NAME), 20, bold=True)
    p = text_line(doc, TITLE, 11, after=0)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = text_line(doc, CONTACT, 10, after=4)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    heading(doc, "Professional Summary")
    text_line(doc, SUMMARY, after=2)

    heading(doc, "Key Highlights")
    for h in HIGHLIGHTS:
        bullet(doc, h)

    heading(doc, "Professional Experience")
    for job in EXPERIENCE:
        job_header(doc, f"{job['role']} | {job['company']}, {job['location']}", job["dates"])
        if job.get("project"):
            p = doc.add_paragraph()
            spacing(p, after=1)
            set_font(p.add_run("Project: "), 10.5, bold=True)
            set_font(p.add_run(job["project"]), 10.5)
        for b in job["bullets"]:
            bullet(doc, b)

    heading(doc, "Technical Skills")
    for label, items in SKILLS:
        p = doc.add_paragraph()
        spacing(p, after=1)
        set_font(p.add_run(f"{label}: "), 10.5, bold=True)
        set_font(p.add_run(items), 10.5)

    heading(doc, "Education")
    for degree, school, years in EDUCATION:
        job_header(doc, degree, years)
        text_line(doc, school)

    heading(doc, "Certifications")
    text_line(doc, CERTIFICATIONS)

    doc.save(OUT)
    subprocess.run(
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(OUT.parent), str(OUT)],
        check=True, capture_output=True,
    )
    print(f"Wrote {OUT} and {OUT.with_suffix('.pdf')}")


if __name__ == "__main__":
    build()
