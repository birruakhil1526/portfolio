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
TITLE = "Senior Angular Developer | Full Stack: Java · Spring Boot · PostgreSQL | AI: Claude · RAG · Agents"
CONTACT = "Bengaluru, India | birruakhil1526@gmail.com | linkedin.com/in/akhil-birru | github.com/birruakhil1526"

SUMMARY = (
    "Senior Angular Developer with 5+ years of experience building production-grade web applications, including "
    "3+ years of Angular (up to v21), TypeScript, and RxJS: lazy-loaded feature modules, reusable base-class "
    "architecture, role-based access, and performance tuning. Full stack background in Java / Spring Boot, "
    "PostgreSQL, and YugabyteDB to own features end to end, from API and database to UI. Strong hands-on "
    "experience with Claude, AI / ML, RAG, and agentic AI frameworks, including a company-wide agentic AI "
    "assistant with guardrails. Experienced in Agile / Scrum delivery."
)

HIGHLIGHTS = [
    "Develop complex Angular modules for an enterprise lending admin app with 65+ lazy-loaded features, built on reusable "
    "base classes for CRUD, maker-checker approval workflows, and role-based permissions.",
    "Built core Angular modules from the ground up, including secure Single Sign-On (SSO), and fixed performance "
    "bottlenecks to improve load times; led the frontend team as Lead Engineer.",
    "Full stack ownership of lending epics (LOS, LMS, LCS): Spring Boot on PostgreSQL / YugabyteDB through to Angular UI.",
    "Worked on AiTDP, a company-wide AI assistant: an in-house Claude orchestration platform on an agentic framework, "
    "with guardrails; built its unit test generation and automated bug resolution.",
]

SKILLS = [
    ("Frontend", "Angular (up to v21), TypeScript, JavaScript (ES6+), RxJS, Angular Material, Bootstrap, HTML5, CSS3, SCSS, ReactJS, Redux"),
    ("Frontend Architecture", "Lazy-loaded modules, reusable components and base classes, route guards, RBAC, "
     "SSO / authentication, performance optimisation"),
    ("Frontend Testing", "Karma, Jasmine, unit testing"),
    ("Backend", "Java, Spring Boot, RESTful APIs, Swagger, CRON / scheduled jobs, Node.js"),
    ("Databases", "PostgreSQL, YugabyteDB (distributed SQL), SQL, MongoDB"),
    ("AI / ML", "Claude (Anthropic API), LLM workflows, RAG (retrieval-augmented generation), agentic AI frameworks, "
     "AI agents, prompt engineering, AI developer tools"),
    ("Tools & DevOps", "Git, Jenkins, Docker, Jira, VS Code, IntelliJ"),
    ("Practices", "Agile / Scrum, sprint planning, system design, code reviews, mentoring"),
]

EXPERIENCE = [
    {
        "company": "Trustt",
        "role": "Senior Software Engineer",
        "dates": "Oct 2024 – Present",
        "location": "Bengaluru",
        "bullets": [
            "Build complex Angular UI for an enterprise lending platform (loans, savings, accounting): an admin app with "
            "65+ lazy-loaded feature modules and reusable base classes for CRUD, maker-checker approval workflows, and "
            "role-based permissions.",
            "Deliver features across 3 fintech lending products – Loan Origination (LOS), Loan Management (LMS), "
            "Loan Collections (LCS) – and AiTDP, an in-house Claude platform.",
            "Own epics end to end: Spring Boot services and REST APIs on PostgreSQL and YugabyteDB, plus the Angular UI that uses them.",
            "AiTDP: worked on the in-house Claude orchestration platform – an agentic AI assistant used company-wide "
            "by developers and BAs, with guardrails limiting it to company use.",
            "AiTDP: independently designed and built unit test generation for Angular, Java, and Android applications, "
            "delivered as editor plugins for developers.",
            "AiTDP: architected an agentic Claude workflow that automates bug detection and resolution, reducing manual "
            "debugging effort.",
            "Built and maintained scheduled CRON jobs in Spring Boot for backend batch processing.",
            "Work in Agile / Scrum sprints on Jira: planning, estimation, stand-ups, and retrospectives.",
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
            "Built responsive Angular interfaces from UX/UI wireframes and integrated RESTful APIs and third-party services.",
            "Designed and developed critical modules from the ground up, including secure Single Sign-On (SSO).",
            "Fixed performance bottlenecks and drove architecture decisions, improving load times, scalability, and maintainability.",
            "Led the frontend team for 3 months as Lead Engineer, delivering all planned tasks on schedule.",
            "Conducted code reviews and mentored junior developers on Angular best practices and coding standards.",
        ],
    },
    {
        "company": "Accenture",
        "role": "Associate – Backend Developer",
        "dates": "Apr 2021 – Oct 2022",
        "location": "Hyderabad",
        "project": "Inventory and supply-chain app for an international agricultural company – stock, transit, "
                   "storage, and processing.",
        "bullets": [
            "Developed backend services and RESTful APIs in Java and Spring Boot for inventory, in-transit tracking, "
            "and material processing modules.",
            "Wrote SQL queries and data access logic for product stock, storage, and processing data.",
            "Worked closely with frontend developers and designers to define API contracts and integrate services end to end.",
        ],
    },
]

EDUCATION = [
    ("B.Tech, Electronics and Communication Engineering", "Christu Jyothi Institute of Technology and Science", "2015 – 2019"),
]

CERTIFICATIONS = "PGP Full Stack Software Engineering; Angular; Java; JavaScript; SQL"

ACHIEVEMENTS = [
    "Certificate of Appreciation, Maveric Systems – for leading the frontend team.",
]


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

    heading(doc, "Awards & Certifications")
    for a in ACHIEVEMENTS:
        bullet(doc, a)
    bullet(doc, "Certifications: " + CERTIFICATIONS)

    doc.save(OUT)
    subprocess.run(
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(OUT.parent), str(OUT)],
        check=True, capture_output=True,
    )
    print(f"Wrote {OUT} and {OUT.with_suffix('.pdf')}")


if __name__ == "__main__":
    build()
