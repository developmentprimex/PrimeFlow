from __future__ import annotations

import asyncio
import json
import os

# 1. Import load_dotenv to read the .env file
from dotenv import load_dotenv
from sqlalchemy import select

from app.auth.security import get_password_hash
from app.db import SessionLocal
from app.models.department import Department
from app.models.enums import ProjectPhaseStatus, ProjectType, TaskStatus, UserRole
from app.models.checklist import Checklist
from app.models.checklist_item import ChecklistItem
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.models.task_assignee import TaskAssignee
from app.models.enums import ChecklistItemType

# 2. Load environment variables immediately
load_dotenv()

def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _vs_vl_meta(phase: str, unlock_after_days: int | None = None) -> str:
    meta = {"vs_vl_phase": phase}
    if unlock_after_days is not None:
        meta["unlock_after_days"] = unlock_after_days
    return f"{VS_VL_META_PREFIX}{json.dumps(meta)}"


DEPARTMENTS = [
    ("Development", "DEV"),
    ("Project Content Manager", "PCM"),
    ("Graphic Design", "GD"),
    ("Human Resource", "HR"),
    ("Finance", "FIN"),
    ("GA", "GA"),
    ("GA PERSONAL", "GAP"),
]

PCM_PROJECTS = [
    {
        "title": "MST",
        "description": "Menaxhimi i programit dhe checklistes se produkteve.",
        "status": TaskStatus.IN_PROGRESS,
        "current_phase": ProjectPhaseStatus.PLANNING,
        "progress_percentage": 48,
        "project_type": ProjectType.MST.value,
        "is_template": True,
    },
    {
        "title": "TT",
        "description": "Menaxhimi i programit dhe checklistes se produkteve.",
        "status": TaskStatus.IN_PROGRESS,
        "current_phase": ProjectPhaseStatus.PLANNING,
        "progress_percentage": 48,
        "is_template": True,
    },
]

GD_PROJECTS = [
    {
        "title": "MST",
        "description": "MST (Graphic Design) with phases: Planning, Product, Control, Final.",
        "status": TaskStatus.IN_PROGRESS,
        "current_phase": ProjectPhaseStatus.PLANNING,
        "progress_percentage": 0,
        "project_type": ProjectType.MST.value,
        "is_template": True,
    },
    {
        "title": "DEV TEMPLATE",
        "description": "Graphic Design development-style template with phases: Meetings, Planning, Development, Testing, Documentation.",
        "status": TaskStatus.IN_PROGRESS,
        "current_phase": ProjectPhaseStatus.MEETINGS,
        "progress_percentage": 0,
        "project_type": ProjectType.GD_DEVELOPMENT.value,
        "is_template": True,
    },
]

VS_VL_LARGE_TEMPLATE_TITLE = "VS/VL PROJEKT I MADH"
VS_VL_LARGE_TEMPLATE_LEGACY_TITLES = ["VS/VL PROJEKT I MADH TEMPLATE"]
VS_VL_TEMPLATE_DESCRIPTION = "VS/VL project phases: Project Acceptance, Amazon, Check, Dreamrobot."
VS_VL_SMALL_TEMPLATE_TITLE = "VS/VL PROJEKT I VOGEL TEMPLATE 2"
VS_VL_SMALL_TEMPLATE_OFFSETS = {
    "ANALIZIMI DHE IDENTIFIKIMI I KOLONAVE": 0,
    "PLOTESIMI I TEMPLATE-IT TE AMAZONIT": 1,
    "KALKULIMI I CMIMEVE": 3,
    "GJENERIMI I FOTOVE": 3,
    "KONTROLLIMI I PROD. EGZSISTUESE DHE POSTIMI NE AMAZON": 4,
    "KO1 E PROJEKTIT VS": 4,
    "KO2 E PROJEKTIT VS": 4,
    "DREAM ROBOT VS": 4,
    "DREAM ROBOT VL": 4,
    "KALKULIMI I PESHAVE": 4,
}
VS_VL_LARGE_TEMPLATE_OFFSETS = VS_VL_SMALL_TEMPLATE_OFFSETS
VS_VL_META_PREFIX = "VS_VL_META:"
VS_VL_ACCEPTANCE_QUESTIONS = [
    "IS TEAMS GROUP OPENED?",
    "ARE TRELLO POINTS ADDED?",
    "IS CHATGPT PROJECT OPENED?",
]
VS_VL_TEMPLATE_TASKS = [
    {
        "key": "base",
        "title": "ANALIZIMI DHE IDENTIFIKIMI I KOLONAVE",
        "phase": "AMAZON",
        "description": (
            "Pas pranimit të projektit të ri nga furnitori, analizohen të gjitha informatat e pranuara, "
            "duke identifikuar të dhënat që mungojnë si dhe rastet e reja. Pas kësaj faze, përcaktohen "
            "kolonat (informatat) që mungojnë dhe plotësohen përmes burimeve të ndryshme në web ose "
            "I ipen zhvillimit per ti gjetur te dhenat me agjent. Në rast se informatat gjenerohen nga "
            "agjentët, ato kontrollohen dhe manualisht.\n"
            "1. REGJ: VS/VL\n"
            "2.PATH: V:\\20_VS\n"
            "3.CHECK: V:\\20_VS\\01_CHECKLISTA\\AMAZON\\FINAL \n"
            "4.TRAJNIM: 0\n"
            "5. BZ GROUP: VS_EMRI I FURNITORIT\n"
        ),
    },
    {
        "key": "template",
        "title": "PLOTESIMI I TEMPLATE-IT TE AMAZONIT",
        "phase": "AMAZON",
        "dependency_key": "base",
        "description": (
            "Pas sigurimit të informatave të nevojshme, bëhet plotësimi i kolonave në template-in e "
            "Amazon-it. Në to vendosen informatat që kanë munguar dhe janë siguruar përmes web-it ose "
            "agjentit, si dhe të dhënat që gjenden në produktdaten (dokumentet) e dërguara nga klienti, "
            "të përshtatura sipas rregullave dhe standardeve të Amazon-it.1. \n"
            "1. REGJ: VS/VL\n"
            "2.PATH: V:\\20_VS\\00_TEMPLATE\\BLANK\\AMAZON\\FINAL\n"
            "3.CHECK: V:\\20_VS\\01_CHECKLISTA\\AMAZON\\FINAL \n"
            "4.TRAJNIM: 0\n"
            "5.BZ GROUP: VS_EMRI I FURNITORIT"
        ),
    },
    {
        "key": "prices",
        "title": "KALKULIMI I CMIMEVE",
        "phase": "AMAZON",
        "description": (
            "Fillimisht cmimet e dërguara nga VS kontrollohen për të parë nëse ka ndonjë mungesë; në rast "
            "se ka mungesa, ato i dërgohen VS-se për sigurimin e cmimeve. Më pas produktet ndahen në dy "
            "Excel-a të veçantë: pijet dhe feinkost. Në secilin Excel vendosen numrat e artikujve dhe "
            "çmimet përkatëse, të cilët më pas ngarkohen në Platforme. Excel-i i pijeve llogaritet me "
            "normal price, ndërsa ai i feinkost-it (ushqime) me feinkost prices. Pas këtij procesi, "
            "gjenerohet automatikisht Excel-i me çmime për sasi 01, 03, 06 dhe 12, dhe këto çmime "
            "vendosen në template-in e Amazon-it.\n"
            "1. REGJ: VS/VL\n"
            "2.PATH: V:\\20_VS\\00_TEMPLATE\\FILLED\\AMAZON\\FINAL\\PRICES\n"
            "3.CHECK: V:\\20_VS\\01_CHECKLISTA\\AMAZON\\FINAL \n"
            "4.TRAJNIM: 0\n"
            "5.BZ GROUP: VS_EMRI I FURNITORIT"
        ),
    },
    {
        "key": "photos",
        "title": "GJENERIMI I FOTOVE",
        "phase": "AMAZON",
        "description": (
            "Fillimisht Fotot e dërguara nga VS kontrollohen për të parë nëse ka ndonjë mungesë; në rast "
            "se ka mungesa, ato i dërgohen VS-se për sigurimin e fotove. Më pas bëhet kontrollimi i "
            "fotove nëse përmbajnë kuti druri, vite(ne shishe) apo kanaqe dhe ato modifikohen/editohen. "
            "Fotot pranohen përmes listës në Excel ose në formatet PNG/JPG. Këto foto kthehen në linka "
            "URL (përmes Python-it, sipas checklistës se fotove) dhe këta linka vendosen në template-in "
            "për Amazon.\n"
            "1. REGJ: VS/VL\n"
            "2.PATH: V:\\20_VS\\00_TEMPLATE\\FILLED\\AMAZON\\FINAL\\PICTURE\n"
            "3.CHECK: V:\\20_VS\\01_CHECKLISTA\\AMAZON\\FINAL\n"
            "4.TRAJNIM: 0\n"
            "5.BZ GROUP: VS_EMRI I FURNITORIT\n"
        ),
    },
    {
        "key": "kontrol",
        "title": "KONTROLLIMI I PROD. EGZSISTUESE DHE POSTIMI NE AMAZON",
        "phase": "AMAZON",
        "dependency_key": "ko2",
        "description": (
            "Behet kontrolla e produkteve  ekzistuese në Amazon. Në përputhje me rregullat dhe kërkesat "
            "e klientit, fshihen produktet që janë të njëjta ose duplikatë me ato që planifikohen për "
            "postim. Më pas realizohet postimi i produkteve në Amazon. Pas postimit, identifikohen "
            "error-at, bëhet rregullimi i tyre dhe produktet ripostohen derisa procesi të përfundojë "
            "pa asnjë error.\n"
        ),
    },
    {
        "key": "ko1",
        "title": "KO1 E PROJEKTIT VS",
        "phase": "CHECK",
        "dependency_key": "base",
        "description": (
            "Pas perfundimit te projektit behet kontrolla e te gjitha kolonave nese ka blanks. Dhe "
            "vazhdohet me kontrollen e projektit permes checklistes per Amazon VS\n"
            "1. REGJ: VS/VL\n"
            "2.PATH: V:\\20_VS\n"
            "3.CHECK: V:\\20_VS\\01_CHECKLISTA\\AMAZON\\FINAL \n"
            "4.TRAJNIM: 0\n"
        ),
    },
    {
        "key": "ko2",
        "title": "KO2 E PROJEKTIT VS",
        "phase": "CHECK",
        "dependency_key": "ko1",
        "description": (
            "Pas kontrolles se pare te projektit VS behet kontrolla e dyte finale sipas checklistes "
            "per Amazon VS\n"
            "1. REGJ: VS/VL\n"
            "2.PATH: V:\\20_VS\n"
            "3.CHECK: V:\\20_VS\\01_CHECKLISTA\\AMAZON\\FINAL \n"
            "4.TRAJNIM: 0\n"
            "5.BZ GROUP: VS_EMRI I FURNITORIT"
        ),
    },
    {
        "key": "dreamVs",
        "title": "DREAM ROBOT VS",
        "phase": "DREAMROBOT",
        "dependency_key": "kontrol",
        "description": (
            "Plotësohet template-i për Dream Robot për VS. Kontrollohen produktet ekzistuese dhe bëhet "
            "fshirja e tyre. Pas përfundimit të kontrollit, produktet postohen dhe realizohet lidhja "
            "e tyre me variacione. Më pas, produktet e vjetra (me prefix-e në fund) lidhen me produktet "
            "e reja që janë postuar. \n"
            "1. REGJ: VS/VL\n"
            "2.PATH: V:\\20_VS\\00_TEMPLATE\\BLANK\\DREAM ROBOT\\FINAL\n"
            "3.CHECK: V:\\20_VS\\01_CHECKLISTA\\DREAMROBOT\\FINAL\n"
            "4.TRAJNIM: 0\n"
            "5.BZ GROUP: VS_EMRI I FURNITORIT"
        ),
    },
    {
        "key": "dreamVl",
        "title": "DREAM ROBOT VL",
        "phase": "DREAMROBOT",
        "dependency_key": "kontrol",
        "description": (
            "Plotësohet template-i për Dream Robot për VL. Kontrollohen produktet ekzistuese dhe bëhet "
            "fshirja e tyre. Pas përfundimit të kontrollit, produktet postohen dhe realizohet lidhja "
            "e tyre me variacione. Më pas, produktet e vjetra (me prefix-e në fund) lidhen me produktet "
            "e reja që janë postuar. \n"
            "1. REGJ: VS/VL\n"
            "2.PATH: V:\\26_VL\\00_TEMPLATES\\BLANK TEMPLATE\\DREAM ROBOT\\FINAL\n"
            "3.CHECK: V:\\26_VL\\01_CHECKLISTA\\FINAL\\DREAMROBOT\n"
            "4.TRAJNIM: 0\n"
            "5.BZ GROUP: VS_EMRI I FURNITORIT"
        ),
    },
    {
        "key": "dreamWeights",
        "title": "KALKULIMI I PESHAVE",
        "phase": "DREAMROBOT",
        "description": (
            "Fillimisht peshat e dërguara nga VS kontrollohen për të parë nëse ka ndonjë mungesë; në rast "
            "se ka mungesa, ato i dërgohen VS-se për sigurimin e peshave. Më pas, peshat vendosen në "
            "template-in përkatës dhe bëhet kalkulimi i peshës totale të produkteve për sasi 01, 03, 06 "
            "dhe 12. Në fund, këto të dhëna vendosen në template-in e Dream Robot\n"
            "1. REGJ: VS/VL\n"
            "2.PATH: V:\\20_VS\\00_TEMPLATE\\FILLED\\DREAM ROBOT\\FINAL\\WEIGHT\n"
            "3.CHECK: V:\\20_VS\\01_CHECKLISTA\\DREAMROBOT\\FINAL\n"
            "4.TRAJNIM: 0\n"
            "5.BZ GROUP: VS_EMRI I FURNITORIT"
        ),
    },
]

MST_PLANNING_ACCEPTANCE_GROUP_KEY = "MST_PLANNING_ACCEPTANCE"
MST_PLANNING_GA_MEETING_GROUP_KEY = "MST_PLANNING_GA_MEETING"

# Graphic Design (GD) - "Pranimi i Projektit" checklist items
GD_PROJECT_ACCEPTANCE_TEMPLATE: list[str] = [
    "A është pranuar projekti?",
    "A është krijuar folderi për projektin?",
    "A janë ruajtur të gjitha dokumentet?",
    "A janë eksportuar të gjitha fotot në dosjen 01_ALL_PHOTO?",
    "A është kryer organizimi i fotove në foldera?",
    "A është shqyrtuar sa foto janë mungesë nese po është dergu email tek klienti?",
    "A janë analizuar dokumentet që i ka dërguar klienti?",
    "A jane identifikuar karakteristikat e produktit? p.sh (glass, soft close).",
    "A janë gjetur variancat? (fusse, farbe)",
    "A eshte pergatitur lista e produkteve e ndare me kategori?",
    "A eshte rast i ri, apo eshte kategori ekzistuese?",
]

# Graphic Design (GD) - "Takim me GA/DV" checklist items
GD_GA_DV_MEETING_TEMPLATE: list[str] = [
    "A është diskutuar me GA për propozimin?",
    "Çfarë është vendosur për të vazhduar?",
    "A ka pasur pika shtesë nga takimi?",
]

# Graphic Design (GD) - "PROPOZIM KO1/KO2" checklist items
GD_PROPOZIM_KO1_KO2_TEMPLATE: list[str] = [
    "Cila është kategoria?",
    "A eshte hulumtuar ne Otto.de, amazon.de dhe portale te tjera per top produkte te kategorise qe e kemi?",
    "Vendos linget ku je bazuar?",
]

# Graphic Design (GD) - "PUNIMI" checklist items
GD_PUNIMI_TEMPLATE: list[str] = [
    "Me dhan mundsi me shtu per kategorit qe vazhdojm psh mujn me 3 kategori ose 4 ose 1 nvaret prej klientit",
    "A janë dërguar të gjitha fotot për bz 1n1?",
]
# Graphic Design (GD) - "Përgatitja për dërgim KO1/KO2" checklist items
GD_CONTROL_KO1_KO2_TEMPLATE: list[str] = [
    "A janë bartur të gjitha produktet te folderi FINAL?",
    "A janë bartur vetëm fotot e nevojshme (3 foto)?",
    "A janë riemërtuar të gjitha fotot sipas kodit (kodi_1, kodi_2, kodi_3)?",
    "A është kontrolluar nëse janë kryer të gjitha produktet?",
    "A janë riemërtuar të gjitha fotot me kodin e artikullit dhe SKU-në interne?",
    "A janë vendosur të gjitha fotot e një kategorie në një folder?",
    "A është krijuar WeTransfer?",
    "A është dërguar WeTransfer-i në grup?",
]
# Graphic Design (GD) - "Finalizimi" checklist items
GD_FINALIZATION_TEMPLATE: list[str] = [
    "A eshte derguar?",
]



PROJECT_ACCEPTANCE_PATH = "project acceptance"
GA_DV_MEETING_PATH = "ga/dv meeting"
PROPOZIM_KO1_KO2_PATH = "propozim ko1/ko2"
PUNIMI_PATH = "punimi"
CONTROL_KO1_KO2_PATH = "control ko1/ko2"
FINALIZATION_PATH = "finalization"

## Internal meetings seeding removed per request.

# Common meetings (board/staff) used by Common view (STAFF/GA + BORD/GA dropdowns)
COMMON_MEETING_TEMPLATES: list[dict] = [
    {
        "title": "TAK BORD/GA",
        "note": None,
        "default_owner": "DV",
        "default_time": "8:00",
        "group_key": "board",
        "columns": [
            {"key": "nr", "label": "NR", "width": "52px"},
            {"key": "topic", "label": "M1 PIKAT"},
            {"key": "check", "label": "", "width": "48px"},
            {"key": "owner", "label": "WHO", "width": "90px"},
            {"key": "time", "label": "WHEN", "width": "90px"},
        ],
        "rows": [
            {"nr": 1, "topic": "MUNGESA/VONESA? A KEMI NDONJE MUNGESE QE E PRISH PLANIN?"},
            {"nr": 2, "topic": "A KA NDRYSHIME TE PLANIT/PRIORITETEVE?"},
            {"nr": 3, "topic": "KUSH ME CKA VAZHDON?"},
            {"nr": 4, "topic": "EMAIL PX? primex.eu@gmail.com (KONTROLLO EDHE SPAM)"},
            {"nr": 5, "topic": "EMAIL INFO PX? (KONTROLLO EDHE SPAM)"},
            {"nr": 6, "topic": "EMAIL HF? (KONTROLLO EDHE SPAM)"},
            {"nr": 7, "topic": "KOMENTET SHENIME GA"},
            {"nr": 8, "topic": "KOMENTET BORD"},
        ],
    },
    {
        "title": "ORDERS 08:05",
        "note": "!!! MOS HARRO, SEND/RECEIVE MENJEHERE PAS HAPJES SE OUTLOOK! poczta.zenbox.pl",
        "default_owner": "DM",
        "default_time": "8:05",
        "group_key": "staff",
        "columns": [
            {"key": "nr", "label": "NR", "width": "52px"},
            {"key": "topic", "label": "M1 PIKAT"},
            {"key": "check", "label": "", "width": "48px"},
            {"key": "owner", "label": "WHO", "width": "90px"},
            {"key": "time", "label": "WHEN", "width": "90px"},
        ],
        "rows": [
            {"nr": 1, "topic": "PIKAT NGA TEAMS DJE DHE SOT (!08:05-08:45 ORDERS HC)"},
            {
                "nr": 2,
                "topic": "A KA DET TE REJA DHE TAKIM TE RI NGA TAKIMI DHE A JANE SHPERNDARE DETYRAT? NESE PO, KERKO DATE???",
            },
            {"nr": 3, "topic": "CKA KEMI ME PERGADIT NGA PREZANTIMET SOT DHE NESER?"},
            {"nr": 4, "topic": "A ESHTE PRANUAR TAKIMI NGA TE GJITHE PARTICIPANTET?"},
            {"nr": 5, "topic": "A JANE VENDOSUR NE VEND PREZANTIMET NE CANVA/FILES?"},
            {
                "nr": 6,
                "topic": "A KEMI POROSI TE RE PER INTERLINE, CILI PRODUKT ESHTE, A ESHTE KRIJUAR ZO DHE TE PERCILLET PRODHIMI?",
            },
            {"nr": 7, "topic": "DISKUTOHEN EMAILAT E REJA"},
        ],
    },
    {
        "title": "PERMBLEDHJA M1",
        "note": None,
        "default_owner": "LM/DM",
        "default_time": "8:15",
        "group_key": "staff",
        "columns": [
            {"key": "nr", "label": "NR", "width": "52px"},
            {"key": "day", "label": "DITA", "width": "90px"},
            {"key": "topic", "label": "M1 PIKAT"},
            {"key": "check", "label": "", "width": "48px"},
            {"key": "owner", "label": "WHO", "width": "90px"},
            {"key": "time", "label": "WHEN", "width": "90px"},
        ],
        "rows": [
            {
                "nr": 1,
                "day": "E HENE",
                "topic": "A ESHTE BERE KONTROLLI I TRANSFERIT TE THIRRJEVE NGA DE NE PRIMEX SIPAS TEMPLATE-IT NE MURE?",
            },
            {"nr": 2, "day": "E HENE", "topic": "A ESHTE BILANCI I GJENDJES X2 NE RREGULL?"},
            {"nr": 3, "day": "CDO DITE", "topic": "MUNGESA/VONESA SOT: PX-NESE PO?"},
            {"nr": 4, "day": "CDO DITE", "topic": "PUSHIM SOT: PX/HC/FD/HF"},
            {
                "nr": 5,
                "day": "CDO DITE",
                "topic": "FESTA: PASNESER/NESER/SOT: PX/HC/FD/HF/USA - NESE PO? / NESE KA DUHET TE. LAJMROHEN KLIENTAT 1 JAVE ME HERET",
            },
            {"nr": 6, "day": "CDO DITE", "topic": "FESTA JAVA E ARDHSHME PX/PL/DE/USA"},
            {"nr": 7, "day": "CDO DITE", "topic": "TAKIME NGA KALENDARI SOT / NESER (A KA TAKIME TE JASHTME?)"},
            {"nr": 8, "day": "E HENE", "topic": "PRINTERI COLOR B&W"},
            {"nr": 9, "day": "CDO DITE", "topic": "ANKESA"},
            {"nr": 10, "day": "CDO DITE", "topic": "KERKESA"},
            {"nr": 11, "day": "CDO DITE", "topic": "PROPOZIME"},
            {"nr": 12, "day": "CDO DITE", "topic": "PIKA TE PERBASHKETA"},
        ],
    },
    {
        "title": "TAKIMI ME STAF PER SQARIMIN E DET & NE FUND ME GA",
        "note": None,
        "default_owner": "DV",
        "default_time": "8:30",
        "group_key": "staff",
        "columns": [
            {"key": "nr", "label": "NR", "width": "52px"},
            {"key": "topic", "label": "M1 PIKAT"},
            {"key": "check", "label": "", "width": "48px"},
            {"key": "owner", "label": "WHO", "width": "90px"},
            {"key": "time", "label": "WHEN", "width": "90px"},
        ],
        "rows": [
            {"nr": 1, "topic": "BZ PROJEKTET/SECILI INDIVIDUALISHT (BLIC DETYRAT)"},
            {"nr": 2, "topic": "TT/VS/MST PRJK/MST FOTO/SMM"},
            {"nr": 3, "topic": "KUSH NUK ESHTE BRENDA PLANIT & A KA PASUR PROBLEME?"},
            {
                "nr": 4,
                "topic": "BZ PERMBLEDHJA ME GA (FIZIKISHT)- A KA DICKA TE RE QE KA SHTU GA NE PERMBLEDHJE? SOT/R1/1H, BLOK?",
            },
            {"nr": 5, "topic": "SQARO DETYRA TE REJA TE SHPEJTA QE KRYHEN BRENDA DITES?"},
            {"nr": 6, "topic": "A PRITET DICKA NE PAUZE PER KONTROLLE GA NGA ZHVILLIMI/PROJEKTET?"},
        ],
    },
    {
        "title": "PERMBLEDHJA M2",
        "note": None,
        "default_owner": "DV",
        "default_time": "11:50",
        "group_key": "staff",
        "columns": [
            {"key": "nr", "label": "NR", "width": "52px"},
            {"key": "topic", "label": "M2 PIKAT"},
            {"key": "check", "label": "", "width": "48px"},
            {"key": "owner", "label": "WHO", "width": "90px"},
            {"key": "time", "label": "WHEN", "width": "90px"},
        ],
        "rows": [
            {"nr": 1, "topic": "PERSONALISHT SHENIMET GA?"},
            {"nr": 2, "topic": "DETYRAT PERSONALISHT 1H/R1/SOT TE KRYERA DHE TE BZ"},
            {"nr": 3, "topic": "URGJENCA/PROBLEME/1H!!!"},
            {"nr": 4, "topic": "A JEMI BRENDA PLANIT ME PROJEKTE/DIZAJN?"},
            {"nr": 5, "topic": "A KA DETYRA TE SHPEJTA QE KRYHEN BRENDA DITES, PER BARAZIM AM?"},
            {
                "nr": 6,
                "topic": "A KA DETYRA TE REJA NGA TAKIMET EKSTERNE DHE A JANE SHPERNDARE DETYRA DHE A JANE VENDOSUR NE VEND PREZANTIMET NE CANVA/FILES?",
            },
            {"nr": 7, "topic": "A KA TAKIME TE REJA, KERKO DATEN E TAKIMIT TE RI?"},
            {"nr": 8, "topic": "EMAIL/TAKIME A KA KERKESA TE REJA DICKA JASHTE STANDARDEVE"},
            {"nr": 9, "topic": "PIKAT E BORDIT"},
        ],
    },
    {
        "title": "PERMBLEDHJA PAS PAUZES",
        "note": None,
        "default_owner": "DV",
        "default_time": "13:15",
        "group_key": "board",
        "columns": [
            {"key": "nr", "label": "NR", "width": "52px"},
            {"key": "topic", "label": "PIKAT"},
            {"key": "check", "label": "", "width": "48px"},
            {"key": "owner", "label": "WHO", "width": "90px"},
            {"key": "time", "label": "WHEN", "width": "90px"},
        ],
        "rows": [
            {"nr": 1, "topic": "(GA) DET NGA EMAIL/ PX INFO"},
            {"nr": 2, "topic": "PROJEKTET: ATO QE KEMI PUNU DHE SKEMI PUNU"},
            {"nr": 3, "topic": "A JEMI BRENDA PLANIT ME PROJEKTE/DIZAJN?"},
            {"nr": 4, "topic": "(GA)SHENIME GA- PIKAT PAS PAUZE"},
            {"nr": 5, "topic": "(GA) A KA REPLY NGA GA TEK DETYRAT NGA STAFI PER GA?"},
            {"nr": 6, "topic": "(GA) PIKAT E BORDIT"},
            {"nr": 7, "topic": "(GA) E HENE- ORDER/TIKETA HT/H"},
        ],
    },
    {
        "title": "PERMBLEDHJA 15:30",
        "note": None,
        "default_owner": "DV ME GA",
        "default_time": "15:45",
        "group_key": "staff",
        "columns": [
            {"key": "nr", "label": "NR", "width": "52px"},
            {"key": "topic", "label": "M3 PIKAT"},
            {"key": "check", "label": "", "width": "48px"},
            {"key": "owner", "label": "WHO", "width": "90px"},
            {"key": "time", "label": "WHEN", "width": "90px"},
        ],
        "rows": [
            {
                "nr": 1,
                "topic": "BZ INDIVIDUALISHT ME SECILIN: 1. A JEMI BRENDA PLANIT? 2. SA PRODUKTE KOLONA JANE KRYER? 3. A KA PASUR NDRYSHIM TE PLANIT? 4. ME CKA VAZHDOHET NESER? 5. A JANE BERE DONE DETYRAT SE BASHKU ME PERGJEGJES?",
                "owner": "DV ME STAF",
                "time": "3:30 PM",
            },
            {"nr": 2, "topic": "PARREGULLSITE DHE DETYRAT SOT PER SOT (DISKUTOHEN EDHE KUR ESHTE GA E NXENE)"},
            {"nr": 3, "topic": "URGJENCAT"},
            {"nr": 4, "topic": "MUST SOT"},
            {"nr": 5, "topic": "BZ SHENIME \\ DETYRAT PERSONALISHT"},
            {"nr": 6, "topic": "BZ PROGRESI TEK PROJEKTET? SA PRODUKTE/KOLONA JANE PERFUNDUAR?"},
            {"nr": 7, "topic": "A KA DETYRA TE SHPEJTA QE KRYHEN BRENDA DITES, PER BARAZIM PM?"},
            {
                "nr": 8,
                "topic": "A KA DETYRA TE REJA NGA TAKIMET EKSTERNE DHE A JANE SHPERNDARE DETYRA DHE A JANE VENDOSUR NE VEND PREZANTIMET NE CANVA/FILES?",
            },
            {"nr": 9, "topic": "NESE NUK MBAHET TAKIMI 16:20, DISKUTOHEN EDHE DET CKA JANE ME RENDESI PER NESER?"},
            {"nr": 10, "topic": "EMAIL/TAKIME A KA KERKESA TE REJA DICKA JASHTE STANDARDEVE"},
        ],
    },
    {
        "title": "MBYLLJA E DITES",
        "note": None,
        "default_owner": "DV",
        "default_time": "16:20",
        "group_key": "board",
        "columns": [
            {"key": "nr", "label": "NR", "width": "52px"},
            {"key": "topic", "label": "PIKAT"},
            {"key": "check", "label": "", "width": "48px"},
            {"key": "owner", "label": "WHO", "width": "90px"},
            {"key": "time", "label": "WHEN", "width": "90px"},
        ],
        "rows": [
            {"nr": 1, "topic": "MBINGARKESE NESER (NESE PO PROPOZIM PER RIORGANIZIM)"},
            {"nr": 2, "topic": "NENGARKESE NESER"},
            {"nr": 3, "topic": "MUST NESER + DET. PERSONALSHT(TRELLO)"},
            {"nr": 4, "topic": "DET PER NESER ME PRIORITET: PSH JAVORET, TAKIMET EXT"},
            {"nr": 5, "topic": "DET NE PROCES SISTEMIT (RD/93)"},
            {"nr": 6, "topic": "DET. PA PROGRES (TRELLO NOT DONE?)"},
            {"nr": 7, "topic": "TAKIMET PA KRY (KONTROLLO TRELLO)"},
            {"nr": 8, "topic": "NESER ME GA (KOF/takime/ankesa/kerkesa/propozime):"},
        ],
    },
]


async def seed() -> None:
    print("Starting seed process...")
    async with SessionLocal() as db:
        # Internal meetings seeding removed per request.
        seed_common_meeting_templates = _env_bool("SEED_COMMON_MEETING_TEMPLATES", default=True)
        seed_mst_checklists = _env_bool("SEED_MST_CHECKLISTS", default=False)
        seed_gd_checklists = _env_bool("SEED_GD_CHECKLISTS", default=False)

        # --- Seed Departments ---
        existing = (await db.execute(select(Department))).scalars().all()
        by_name = {d.name: d for d in existing}
        for name, code in DEPARTMENTS:
            if name not in by_name:
                dept = Department(name=name, code=code, realization_mode="MANUAL" if code == "GAP" else "AUTO")
                db.add(dept)
        await db.commit()

        # --- Seed Projects ---
        departments = (await db.execute(select(Department))).scalars().all()
        for dept in departments:
            # Household tasks live in the private module, not a work project.
            if dept.code == "GAP":
                continue
            # Create General Project
            project = (
                (await db.execute(select(Project).where(Project.department_id == dept.id))).scalars().first()
            )
            if project is None:
                db.add(Project(title="General", department_id=dept.id))

        await db.commit()
        print("Departments and metadata seeded.")

        # --- Seed Common meeting templates (board/staff) ---
        if seed_common_meeting_templates:
            for index, template in enumerate(COMMON_MEETING_TEMPLATES):
                checklist = (
                    await db.execute(
                        select(Checklist).where(
                            Checklist.title == template["title"],
                            Checklist.group_key == template["group_key"],
                            Checklist.task_id.is_(None),
                            Checklist.project_id.is_(None),
                        )
                    )
                ).scalar_one_or_none()

                if checklist is None:
                    checklist = Checklist(
                        title=template["title"],
                        note=template["note"],
                        default_owner=template["default_owner"],
                        default_time=template["default_time"],
                        group_key=template["group_key"],
                        columns=template["columns"],
                        position=index,
                    )
                    db.add(checklist)
                    await db.flush()

                # If checklist already has any items, assume it is populated and skip
                has_item = (
                    await db.execute(
                        select(ChecklistItem.id).where(ChecklistItem.checklist_id == checklist.id).limit(1)
                    )
                ).scalar_one_or_none()
                if has_item is not None:
                    continue

                for row in template["rows"]:
                    db.add(
                        ChecklistItem(
                            checklist_id=checklist.id,
                            item_type=ChecklistItemType.CHECKBOX,
                            position=row["nr"],
                            title=row["topic"],
                            day=row.get("day"),
                            owner=row.get("owner"),
                            time=row.get("time"),
                            is_checked=False,
                        )
                    )

            await db.commit()
            print("Common meeting templates seeded.")

        # --- Internal Meetings seeding removed per request. ---

        pcm_department = next((dept for dept in departments if dept.name == "Project Content Manager"), None)
        if pcm_department:
            existing_pcm = (
                await db.execute(select(Project).where(Project.department_id == pcm_department.id))
            ).scalars().all()
            existing_titles = {p.title for p in existing_pcm}
            for project in PCM_PROJECTS:
                if project["title"] in existing_titles:
                    existing_project = next((p for p in existing_pcm if p.title == project["title"]), None)
                    if existing_project and project.get("is_template", False) and not existing_project.is_template:
                        existing_project.is_template = True
                    continue
                db.add(
                    Project(
                        title=project["title"],
                        description=project["description"],
                        department_id=pcm_department.id,
                        project_type=project.get("project_type"),
                        status=project["status"],
                        current_phase=project["current_phase"],
                        progress_percentage=project["progress_percentage"],
                        is_template=project.get("is_template", False),
                    )
                )
            await db.commit()
            print("PCM projects seeded.")

            async def ensure_vs_vl_template(
                title: str,
                offsets: dict[str, int] | None,
                legacy_titles: list[str] | None = None,
            ) -> None:
                titles = [title, *(legacy_titles or [])]
                template_projects = (
                    await db.execute(
                        select(Project).where(
                            Project.department_id == pcm_department.id,
                            Project.title.in_(titles),
                        )
                    )
                ).scalars().all()
                template_project = next(
                    (project for project in template_projects if project.title == title),
                    template_projects[0] if template_projects else None,
                )
                if template_project is None:
                    template_project = Project(
                        title=title,
                        description=VS_VL_TEMPLATE_DESCRIPTION,
                        department_id=pcm_department.id,
                        status=TaskStatus.IN_PROGRESS,
                        current_phase=ProjectPhaseStatus.PLANNING,
                        progress_percentage=0,
                        is_template=True,
                    )
                    db.add(template_project)
                    await db.flush()
                else:
                    if template_project.title != title:
                        template_project.title = title
                    if not template_project.is_template:
                        template_project.is_template = True
                    if not template_project.description:
                        template_project.description = VS_VL_TEMPLATE_DESCRIPTION
                    if not template_project.current_phase:
                        template_project.current_phase = ProjectPhaseStatus.PLANNING

                existing_tasks = (
                    await db.execute(select(Task).where(Task.project_id == template_project.id))
                ).scalars().all()
                task_by_title = {t.title: t for t in existing_tasks}
                task_by_key: dict[str, Task] = {}

                for task_def in VS_VL_TEMPLATE_TASKS:
                    task_title = task_def["title"]
                    phase = task_def["phase"]
                    description = task_def.get("description")
                    unlock_after_days = offsets.get(task_title) if offsets else None
                    task = task_by_title.get(task_title)
                    if task is None:
                        # Create new task with all fields from template definition
                        task = Task(
                            title=task_title,
                            description=description,  # Include description from template
                            internal_notes=_vs_vl_meta(phase, unlock_after_days),
                            priority="NORMAL",
                            status=TaskStatus.TODO,
                            phase=phase,
                            project_id=template_project.id,
                            department_id=template_project.department_id,
                        )
                        db.add(task)
                        await db.flush()
                        task_by_title[task_title] = task
                    else:
                        # Task already exists - update description if provided and not already set
                        if description and not task.description:
                            task.description = description
                        # Update internal_notes structure and phase if needed
                        if not task.internal_notes or not task.internal_notes.startswith(VS_VL_META_PREFIX):
                            task.internal_notes = _vs_vl_meta(phase, unlock_after_days)
                        else:
                            try:
                                meta = json.loads(task.internal_notes[len(VS_VL_META_PREFIX):])
                            except Exception:
                                meta = {}
                            if meta.get("vs_vl_phase") != phase:
                                meta["vs_vl_phase"] = phase
                            # Always update unlock_after_days from offsets dictionary if provided
                            if unlock_after_days is not None:
                                meta["unlock_after_days"] = unlock_after_days
                            task.internal_notes = f"{VS_VL_META_PREFIX}{json.dumps(meta)}"
                        if not task.phase:
                            task.phase = phase
                        # NOTE: All other existing fields (due_date, assigned_to, dependencies, etc.) 
                        # are PRESERVED and NOT overwritten
                    task_by_key[task_def["key"]] = task

                for task_def in VS_VL_TEMPLATE_TASKS:
                    dependency_key = task_def.get("dependency_key")
                    if not dependency_key:
                        continue
                    task = task_by_key.get(task_def["key"])
                    dependency_task = task_by_key.get(dependency_key)
                    if task and dependency_task and task.dependency_task_id is None:
                        task.dependency_task_id = dependency_task.id

                checklist = (
                    await db.execute(
                        select(Checklist)
                        .where(
                            Checklist.project_id == template_project.id,
                            Checklist.group_key.is_(None),
                        )
                        .order_by(Checklist.created_at)
                    )
                ).scalars().first()
                if checklist is None:
                    checklist = Checklist(project_id=template_project.id, title="Checklist")
                    db.add(checklist)
                    await db.flush()

                existing_vs_vl_items = (
                    await db.execute(
                        select(ChecklistItem).where(
                            ChecklistItem.checklist_id == checklist.id,
                            ChecklistItem.path == "VS_VL_PLANNING",
                            ChecklistItem.item_type == ChecklistItemType.CHECKBOX,
                        )
                    )
                ).scalars().all()
                existing_vs_vl_titles = {item.title for item in existing_vs_vl_items if item.title}

                for position, q_title in enumerate(VS_VL_ACCEPTANCE_QUESTIONS, start=1):
                    if q_title in existing_vs_vl_titles:
                        continue
                    db.add(
                        ChecklistItem(
                            checklist_id=checklist.id,
                            item_type=ChecklistItemType.CHECKBOX,
                            position=position,
                            path="VS_VL_PLANNING",
                            keyword="VS_VL_PLANNING",
                            description=q_title,
                            category="VS_VL_PLANNING",
                            title=q_title,
                            is_checked=False,
                        )
                    )

                await db.commit()
                print(f"VS/VL template project seeded: {title}")

            await ensure_vs_vl_template(
                VS_VL_LARGE_TEMPLATE_TITLE,
                VS_VL_LARGE_TEMPLATE_OFFSETS,
                legacy_titles=VS_VL_LARGE_TEMPLATE_LEGACY_TITLES,
            )
            await ensure_vs_vl_template(VS_VL_SMALL_TEMPLATE_TITLE, VS_VL_SMALL_TEMPLATE_OFFSETS)

        gd_department = next((dept for dept in departments if dept.name == "Graphic Design"), None)
        if gd_department:
            existing_gd = (
                await db.execute(select(Project).where(Project.department_id == gd_department.id))
            ).scalars().all()
            existing_titles = {p.title for p in existing_gd}
            for project in GD_PROJECTS:
                if project["title"] in existing_titles:
                    existing_project = next((p for p in existing_gd if p.title == project["title"]), None)
                    if existing_project and project.get("is_template", False) and not existing_project.is_template:
                        existing_project.is_template = True
                    continue
                db.add(
                    Project(
                        title=project["title"],
                        description=project["description"],
                        department_id=gd_department.id,
                        project_type=project.get("project_type"),
                        status=project["status"],
                        current_phase=project["current_phase"],
                        progress_percentage=project["progress_percentage"],
                        is_template=project.get("is_template", False),
                    )
                )
            await db.commit()
            print("Graphic Design projects seeded.")

        if seed_mst_checklists:
            # --- Seed MST checklist templates (global) ---
            templates = (await db.execute(select(Checklist).where(Checklist.project_id.is_(None)))).scalars().all()
            template_by_key = {c.group_key: c for c in templates if c.group_key}

            async def ensure_template(group_key: str, title: str) -> Checklist:
                checklist = template_by_key.get(group_key)
                if checklist is None:
                    checklist = Checklist(title=title, group_key=group_key, position=0)
                    db.add(checklist)
                    await db.flush()
                    template_by_key[group_key] = checklist
                return checklist

            await ensure_template(
                MST_PLANNING_ACCEPTANCE_GROUP_KEY,
                "MST Planning - Project Acceptance (Template)",
            )
            await ensure_template(
                MST_PLANNING_GA_MEETING_GROUP_KEY,
                "MST Planning - GA Meeting (Template)",
            )
            await db.commit()
            print("MST checklist templates seeded.")

            # --- Ensure MST checklist instances exist for MST projects (EMPTY by default) ---
            mst_projects = (
                await db.execute(select(Project).where(Project.project_type == ProjectType.MST.value))
            ).scalars().all()

            for proj in mst_projects:
                if proj.department_id is None:
                    continue

                # Fetch or create project checklists by group_key
                existing_proj_checklists = (
                    await db.execute(select(Checklist).where(Checklist.project_id == proj.id))
                ).scalars().all()
                by_key = {c.group_key: c for c in existing_proj_checklists if c.group_key}

                for group_key, title in [
                    (MST_PLANNING_ACCEPTANCE_GROUP_KEY, "Project Acceptance"),
                    (MST_PLANNING_GA_MEETING_GROUP_KEY, "GA Meeting"),
                ]:
                    proj_checklist = by_key.get(group_key)
                    if proj_checklist is None:
                        proj_checklist = Checklist(project_id=proj.id, title=title, group_key=group_key)
                        db.add(proj_checklist)
                        await db.flush()
                        by_key[group_key] = proj_checklist

            await db.commit()
            print("MST project checklist instances ensured.")

        if seed_gd_checklists:
            # --- Seed GD checklist items for Graphic Design projects ---
            gd_department = next((dept for dept in departments if dept.name == "Graphic Design"), None)
            if gd_department:
                gd_projects = (
                    await db.execute(select(Project).where(Project.department_id == gd_department.id))
                ).scalars().all()

                for project in gd_projects:
                    is_mst_project = project.project_type == ProjectType.MST.value
                    if not is_mst_project:
                        title_upper = (project.title or "").upper()
                        is_mst_project = "MST" in title_upper
                    if not is_mst_project:
                        continue

                    # Get or create default checklist for the project
                    checklist = (
                        await db.execute(
                            select(Checklist)
                            .where(Checklist.project_id == project.id, Checklist.group_key.is_(None))
                            .order_by(Checklist.created_at)
                        )
                    ).scalars().first()
                    if checklist is None:
                        checklist = Checklist(project_id=project.id, title="Checklist")
                        db.add(checklist)
                        await db.flush()

                    # Check existing items to avoid duplicates
                    existing_acceptance = (
                        await db.execute(
                            select(ChecklistItem)
                            .where(
                                ChecklistItem.checklist_id == checklist.id,
                                ChecklistItem.path == PROJECT_ACCEPTANCE_PATH,
                            )
                        )
                    ).scalars().all()
                    existing_acceptance_titles = {item.title for item in existing_acceptance if item.title}

                    existing_ga_meeting = (
                        await db.execute(
                            select(ChecklistItem)
                            .where(
                                ChecklistItem.checklist_id == checklist.id,
                                ChecklistItem.path == GA_DV_MEETING_PATH,
                            )
                        )
                    ).scalars().all()
                    existing_ga_meeting_titles = {item.title for item in existing_ga_meeting if item.title}

                    # Add Project Acceptance items
                    for position, title in enumerate(GD_PROJECT_ACCEPTANCE_TEMPLATE):
                        if title not in existing_acceptance_titles:
                            db.add(
                                ChecklistItem(
                                    checklist_id=checklist.id,
                                    item_type=ChecklistItemType.CHECKBOX,
                                    position=position,
                                    path=PROJECT_ACCEPTANCE_PATH,
                                    title=title,
                                    is_checked=False,
                                )
                            )

                    # Add GA/DV Meeting items
                    for position, title in enumerate(GD_GA_DV_MEETING_TEMPLATE):
                        if title not in existing_ga_meeting_titles:
                            db.add(
                                ChecklistItem(
                                    checklist_id=checklist.id,
                                    item_type=ChecklistItemType.CHECKBOX,
                                    position=position,
                                    path=GA_DV_MEETING_PATH,
                                    title=title,
                                    is_checked=False,
                                )
                            )

                    # Check existing PROPOZIM KO1/KO2 items
                    existing_propozim = (
                        await db.execute(
                            select(ChecklistItem)
                            .where(
                                ChecklistItem.checklist_id == checklist.id,
                                ChecklistItem.path == PROPOZIM_KO1_KO2_PATH,
                            )
                        )
                    ).scalars().all()
                    existing_propozim_titles = {item.title for item in existing_propozim if item.title}

                    # Add PROPOZIM KO1/KO2 items
                    for position, title in enumerate(GD_PROPOZIM_KO1_KO2_TEMPLATE):
                        if title not in existing_propozim_titles:
                            db.add(
                                ChecklistItem(
                                    checklist_id=checklist.id,
                                    item_type=ChecklistItemType.CHECKBOX,
                                    position=position,
                                    path=PROPOZIM_KO1_KO2_PATH,
                                    title=title,
                                    is_checked=False,
                                )
                            )

                    # Check existing PUNIMI items
                    existing_punimi = (
                        await db.execute(
                            select(ChecklistItem)
                            .where(
                                ChecklistItem.checklist_id == checklist.id,
                                ChecklistItem.path == PUNIMI_PATH,
                            )
                        )
                    ).scalars().all()
                    existing_punimi_titles = {item.title for item in existing_punimi if item.title}

                    # Add PUNIMI items
                    for position, title in enumerate(GD_PUNIMI_TEMPLATE):
                        if title not in existing_punimi_titles:
                            db.add(
                                ChecklistItem(
                                    checklist_id=checklist.id,
                                    item_type=ChecklistItemType.CHECKBOX,
                                    position=position,
                                    path=PUNIMI_PATH,
                                    title=title,
                                    is_checked=False,
                                )
                            )

                    # Check existing CONTROL KO1/KO2 items
                    existing_control = (
                        await db.execute(
                            select(ChecklistItem)
                            .where(
                                ChecklistItem.checklist_id == checklist.id,
                                ChecklistItem.path == CONTROL_KO1_KO2_PATH,
                            )
                        )
                    ).scalars().all()
                    existing_control_titles = {item.title for item in existing_control if item.title}

                    # Add CONTROL KO1/KO2 items
                    for position, title in enumerate(GD_CONTROL_KO1_KO2_TEMPLATE):
                        if title not in existing_control_titles:
                            db.add(
                                ChecklistItem(
                                    checklist_id=checklist.id,
                                    item_type=ChecklistItemType.CHECKBOX,
                                    position=position,
                                    path=CONTROL_KO1_KO2_PATH,
                                    title=title,
                                    is_checked=False,
                                )
                            )

                    # Check existing FINALIZATION items
                    existing_finalization = (
                        await db.execute(
                            select(ChecklistItem)
                            .where(
                                ChecklistItem.checklist_id == checklist.id,
                                ChecklistItem.path == FINALIZATION_PATH,
                            )
                        )
                    ).scalars().all()
                    existing_finalization_titles = {
                        item.title for item in existing_finalization if item.title
                    }

                    # Add FINALIZATION items
                    for position, title in enumerate(GD_FINALIZATION_TEMPLATE):
                        if title not in existing_finalization_titles:
                            db.add(
                                ChecklistItem(
                                    checklist_id=checklist.id,
                                    item_type=ChecklistItemType.CHECKBOX,
                                    position=position,
                                    path=FINALIZATION_PATH,
                                    title=title,
                                    is_checked=False,
                                )
                            )

                await db.commit()
                print("GD checklist items seeded for Graphic Design projects.")

        # --- Seed Admin User ---
        admin_email = os.getenv("ADMIN_EMAIL")
        admin_username = os.getenv("ADMIN_USERNAME")
        admin_password = os.getenv("ADMIN_PASSWORD")

        if admin_email and admin_username and admin_password:
            existing_admin = (
                await db.execute(select(User).where(User.email == admin_email))
            ).scalar_one_or_none()
            
            if existing_admin is None:
                print(f"Creating admin user: {admin_email}")
                db.add(
                    User(
                        email=admin_email,
                        username=admin_username,
                        full_name="Admin",
                        role=UserRole.ADMIN,
                        password_hash=get_password_hash(admin_password),
                        is_active=True,
                    )
                )
                await db.commit()
                print("Admin user created successfully.")
            else:
                print("Admin user already exists. Skipping creation.")
        else:
            print("WARNING: Admin credentials not found in .env file. Skipping admin creation.")
            # Debugging aid: print what was found (masked)
            print(f"DEBUG: Found Email: {bool(admin_email)}, User: {bool(admin_username)}, Pass: {bool(admin_password)}")


if __name__ == "__main__":
    asyncio.run(seed())
