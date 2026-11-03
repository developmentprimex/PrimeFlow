from __future__ import annotations

import asyncio
import uuid

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_dbapi
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.access import ensure_department_access, ensure_manager_or_admin
from app.api.deps import get_current_user
from app.db import get_db
from app.models.department import Department
from app.models.checklist import Checklist
from app.models.checklist_item import ChecklistItem, ChecklistItemAssignee
from app.models.project_phase_checklist_item import ProjectPhaseChecklistItem
from app.models.project import Project
from app.services.project_classification import has_mst_identity
from app.models.project_member import ProjectMember
from app.models.task import Task
from app.models.user import User
from app.models.enums import ChecklistItemType
from app.schemas.checklist_item import (
    ChecklistItemOut,
    ChecklistItemCreate,
    ChecklistItemUpdate,
    ChecklistItemAssigneeOut,
)
from app.schemas.project_phase_checklist_item import (
    ProjectPhaseChecklistItemOut,
)
from app.services.meeting_point_manual_sync import sync_checklist_item_manual_question


router = APIRouter()
MST_PRODUCT_TEMPLATE_GROUP_KEY = "MST_PRODUCT_CHECKLIST_TEMPLATE"
TT_PRODUCT_TEMPLATE_GROUP_KEY = "TT_PRODUCT_CHECKLIST_TEMPLATE"
PRODUCT_TEMPLATE_GROUP_KEYS = {MST_PRODUCT_TEMPLATE_GROUP_KEY, TT_PRODUCT_TEMPLATE_GROUP_KEY}

PROJECT_ACCEPTANCE_PATH = "project acceptance"
GA_DV_MEETING_PATH = "ga/dv meeting"
PROPOZIM_KO1_KO2_PATH = "propozim ko1/ko2"
PUNIMI_PATH = "punimi"
CONTROL_KO1_KO2_PATH = "control ko1/ko2"
FINALIZATION_PATH = "finalization"
GD_MST_GJENERALE_PATH = "gd_mst_gjenerale"
GD_MST_SOFA_NEW_PATH = "gd_mst_sofa_new"
GD_MST_VITRINE_NEW_PATH = "gd_mst_vitrine_new"
GD_MST_SIDEBOARD_NEW_PATH = "gd_mst_sideboard_new"
GD_MST_LOWBOARD_PATH = "gd_mst_lowboard"

# Graphic Design (GD) - "Pranimi i Projektit" checklist items
GD_PROJECT_ACCEPTANCE_TEMPLATE: list[str] = [
    "A Ã«shtÃ« pranuar projekti?",
    "A Ã«shtÃ« krijuar folderi për projektin?",
    "A jaNë ruajtur tÃ« gjitha dokumentet?",
    "A jaNë eksportuar tÃ« gjitha fotot Në dosjen 01_ALL_PHOTO?",
    "A Ã«shtÃ« kryer organizimi i fotove Në foldera?",
    "A Ã«shtÃ« shqyrtuar sa foto jaNë mungesÃ« nese po Ã«shtÃ« dergu email tek klienti?",
    "A jaNë analizuar dokumentet qÃ« i ka dÃ«rguar klienti?",
    "A jane identifikuar karakteristikat e produktit? p.sh (glass, soft close).",
    "A jaNë gjetur variancat? (fusse, farbe)",
    "A eshte pergatitur lista e produkteve e ndare me kategori?",
    "A eshte rast i ri, apo eshte kategori ekzistuese?",
]

# Graphic Design (GD) - "Takim me GA/DV" checklist items
GD_GA_DV_MEETING_TEMPLATE: list[str] = [
    "A Ã«shtÃ« diskutuar me GA për propozimin?",
    "Ã‡farÃ« Ã«shtÃ« vendosur për tÃ« vazhduar?",
    "A ka pasur pika shtesÃ« nga takimi?",
]

# Graphic Design (GD) - "PROPOZIM KO1/KO2" checklist items
GD_PROPOZIM_KO1_KO2_TEMPLATE: list[str] = [
    "Cila Ã«shtÃ« kategoria?",
    "A eshte hulumtuar ne Otto.de, amazon.de dhe portale te tjera per top produkte te kategorise qe e kemi?",
    "Vendos linget ku je bazuar?",
]

# Graphic Design (GD) - "PUNIMI" checklist items
GD_PUNIMI_TEMPLATE: list[str] = [
    "Me dhan mundsi me shtu per kategorit qe vazhdojm psh mujn me 3 kategori ose 4 ose 1 nvaret prej klientit",
    "A jaNë dÃ«rguar tÃ« gjitha fotot për bz 1n1?",
]
# Graphic Design (GD) - "përgatitja për dÃ«rgim KO1/KO2" checklist items
GD_CONTROL_KO1_KO2_TEMPLATE: list[str] = [
    "A jaNë bartur tÃ« gjitha produktet te folderi FINAL?",
    "A jaNë bartur vetÃ«m fotot e nevojshme (3 foto)?",
    "A jaNë riemÃ«rtuar tÃ« gjitha fotot sipas kodit (kodi_1, kodi_2, kodi_3)?",
    "A Ã«shtÃ« kontrolluar Nëse jaNë kryer tÃ« gjitha produktet?",
    "A jaNë riemÃ«rtuar tÃ« gjitha fotot me kodin e artikullit dhe SKU-Në interne?",
    "A jaNë vendosur tÃ« gjitha fotot e njÃ« kategorie Në njÃ« folder?",
    "A Ã«shtÃ« krijuar WeTransfer?",
    "A Ã«shtÃ« dÃ«rguar WeTransfer-i Në grup?",
]
# Graphic Design (GD) - "Finalizimi" checklist items
GD_FINALIZATION_TEMPLATE: list[str] = [
    "A eshte derguar?",
]

# Graphic Design (GD) - MST Planning checklist templates (to be filled later)
GD_MST_SOFA_NEW_TEMPLATE: list[dict[str, str]] = [
    {
        "title": 'PIKAT E SELLING IMAGE 1',
        "keyword": 'PIKAT GJENERALE- SELLING IMAGE_1',
        "description": 'Varesisht prej kategorise dhe funksioneve qe ka produkti, krijohen pikat dhe fotografi te ndryshme.\n\nMAX & MIN per Selling image_ eshte 3 foto dhe 3 pershkrime qe jane ne perputhje me ato foto.\nNe momentin qe produkti ka funksione, permenden te gjitha funksionet. Ne rast se produkti nuk ka funksione, fokusohemi tek materiali dhe dizajni.\nIkonat duhet te jene ne distance jo te ngjitura me tekst.\nTeksti duhet te jete paralel me foto.\nModernes Design â€“ dizajn modern dhe formÃ« elegante qÃ« përshtatet Në Ã§do ambient.\nHochwertige Materialien â€“ materiale cilÃ«sore dhe konstruksion i fortÃ« për jetÃ«gjatÃ«si.\nFunktionale Schlaffunktion â€“ funksion fjetjeje praktik për relaks ose mysafirÃ«\nVerstellbarer Sitzkomfort â€“ mbÃ«shtetje dhe thellÃ«si uljeje e rregullueshme për rehati maksimale.\nPraktischer Stauraum â€“ hapÃ«sirÃ« e integruar për ruajtje (për jastÃ«kÃ«, batanije etj.).',
    },
    {
        "title": 'PIKAT E SELLING IMAGE 1',
        "keyword": 'VENDOSJA E FOTOVE NE KOCKA',
        "description": 'Selling image_1 duhet tÃ« ketÃ« sÃ« paku 3 kocka minimum:\n\nFOTO 1. pamjen e përgjithshme tÃ« divanit, (Kur nuk kemi funksion, per tu verejtur dizajni)\nFOTO 2. Materialin dhe teksturÃ«n e pÃ«lhurÃ«s, (Kur nuk kemi funksion, per tu verejtur materiali)\nFOTO 3. Funksionin e shtrirjes,\n\nKur kockat vrehen mire per shkak te backgroundi ku mund te jep i zi dhe kockat e zeza ateher kockat duhet qe te i vendoset nje STROKE ne photoshop me ngjyre te bardh.',
    },
    {
        "title": 'PIKAT E SELLING IMAGE 1',
        "keyword": 'LOGO',
        "description": '1. Gjithmone logo e klientit e konfirmuar me email (Set One) ose (MST) vendoset larte majtas fotos\n2. Gjithmone logoja e garancise 5 vite vendoset poshte majtas fotos\n\nNe baze te ngjyrave te fotos zgjedhen edhe ngjyrat e logos qe do te perdorim',
    },
    {
        "title": 'PIKAT E SELLING IMAGE 1',
        "keyword": 'BACKGROUND',
        "description": 'Ne Background gjithmon vendoset fotoja e setit\nNese nuk ka foto ne set ateher vendoset foto e type me background.\nFoto e background nuk duhet të preket me kockat â†’ duhet të ketë hapësirë mes kockave dhe setit mbrapa',
    },
    {
        "title": 'PIKAT E SELLING IMAGE 1',
        "keyword": 'EMERTIMI',
        "description": 'MST: Selling image 1 duhet gjithmone te emertohet kodi i produktit SKU (KODI I MST) dhe _7',
    },
    {
        "title": 'PIKAT E SELLING IMAGE 1',
        "keyword": 'EMERTIMI',
        "description": 'OTTO: Selling image 1 duhet gjithmone te emertohet kodi i produktit Article code (KODI I OTTOs) dhe _7\nKur behet emertimi I fotove me kod te OTTOs duhet te kemi shume kujdes dhe patjeter te behen 2 kontrolla',
    },
    {
        "title": 'PIKAT E SELLING IMAGE 2- SKICA',
        "keyword": 'PIKAT GJENERALE',
        "description": "Ne kete foto duhet te jete vetem Skica me dimensione. Nuk vendosim asnje tekst perveq ne Header si titull. Gjithashtu Headeri duket te kombinohet me ngjyrat e Selling Image_1 per t'u perputhur ne dizajn,",
    },
    {
        "title": 'PIKAT E SELLING IMAGE 2- SKICA',
        "keyword": 'LOGO',
        "description": '1. Gjithmone logo e klientit e konfirmuar me email (Set One) ose (MST) vendoset larte majtas fotos\n2. Gjithmone logoja e garancise 5 vite vendoset poshte majtas fotos\n\nNe baze te ngjyrave te fotos zgjedhen edhe ngjyrat e logos qe do te perdorim',
    },
    {
        "title": 'PIKAT E SELLING IMAGE 2- SKICA',
        "keyword": 'FOTO',
        "description": '1. Duhet te vendoset skica e produktit nga assembly instructions me dimensione\nNese nuk kemi skica/AI te produktit merret foto e produktit ne perspektive white background behet bardh e zi dhe vendosen dimensionet manualisht\n2. Duhet te kemi kujdes dhe vijat e dimensioneve mos te prekin produktin',
    },
    {
        "title": 'PIKAT E SELLING IMAGE 2- SKICA',
        "keyword": 'EMERTIMI',
        "description": 'MST: Selling image 1 duhet gjithmone te emertohet kodi i produktit SKU (KODI I MST) dhe _1\nOTTO: Selling image 1 duhet gjithmone te emertohet kodi i produktit Article code (KODI I OTTOs) dhe _1\nKur behet emertimi I fotove me kod te OTTOs duhet te kemi shume kujdes dhe patjeter te behen 2 kontrolla',
    },
    {
        "title": 'PIKAT E SELLING IMAGE 3- NGJYRAT',
        "keyword": 'PIKAT GJENERALE',
        "description": 'Materiali duhet te konfirmohet me MST- dhe te paraqiten te gjitha ngjyrat qe jane te disponueshme per ate produkt.',
    },
    {
        "title": 'PIKAT E SELLING IMAGE 3- NGJYRAT',
        "keyword": 'LOGOT',
        "description": '1. Gjithmone logo e klientit e konfirmuar me email (Set One) ose (MST) vendoset larte majtas fotos\n2. Gjithmone logoja e garancise 5 vite vendoset poshte majtas fotos\n\nNe baze te ngjyrave te fotos zgjedhen edhe ngjyrat e logos qe do te perdorim',
    },
]
GD_MST_VITRINE_NEW_TEMPLATE: list[dict[str, str]] = [
    {
        "title": "PIKAT E SELLING IMAGE 1",
        "keyword": "PIKAT GJENERALE- SELLING IMAGE_1",
        "description": (
            "Foto Gjenerale 1 ka 4 foto vetem foto e Front Glas dhe foto e Griffe ndryshon sipas ngjyres. "
            "Foto e backgroundit ndryshon. Teksti duhet te jete gjithmon I njejte vetem foto mund te ndryshohen: "
            "1. Front und Oberplatte aus glaenzendem Glas. 2. Soft-Close Scharniere. 3. Hochwertige Metallgriffe. "
            "4. ABS-Kanten."
        ),
    },
    {
        "title": "PIKAT E SELLING IMAGE 1",
        "keyword": "PIKAT GJENERALE- SELLING IMAGE_2",
        "description": (
            "Selling image_2 L/R (Mounting Options). Teksti duhet te jete Front links oder rechts montierbar. "
            "Produkti duhet te jete ne vij te njejt e majta dhe e djathta jo njera me lart tjetra me posht."
        ),
    },
    {
        "title": "PIKAT E SELLING IMAGE 1",
        "keyword": "PIKAT GJENERALE- SELLING IMAGE_3",
        "description": (
            "Selling image_3 Varacione. Foto e background duhet te jete gjithmon white background perspektiv. "
            "Duhet te I kete 4 katrora me te dhena: 1. Duhet te jete teksti Farbauswahl dhe ngjyra e varacionit "
            "te ndryshohet varesisht nga produkti. 2. Nuk ndryshon. Teksti: Metallfuese: 3 kembet e vitrinet "
            "dhe 3 ngjyrat e kembve. 3. Teksti Sockel dhe foto duhet te ndryshohet njejt si ngjyra e produktit, "
            "foto duhet te vendoset ne pozicion njejt si ne template jo me lart ose me posht. 4. Teksti Gleiter "
            "dhe foto duhet te jete e produktit pa kembe dhe te vendoset njejt si ne template."
        ),
    },
    {
        "title": "PIKAT E SELLING IMAGE 1",
        "keyword": "LOGO",
        "description": (
            "1. Gjithmone logo e klientit e konfirmuar me email (Set One) ose (MST) vendoset larte majtas fotos. "
            "2. Gjithmone logoja e garancise 5 vite vendoset poshte majtas fotos. Ne baze te ngjyrave te fotos "
            "zgjedhen edhe ngjyrat e logos qe do te perdorim. Ne te 3 Selling Images perdoret e njejta logo e KONF, "
            "ne pozicion fiks dhe te pandryshueshem. E njejta gje vlen edhe per ikonen e garancise."
        ),
    },
    {
        "title": "PIKAT E SELLING IMAGE 1",
        "keyword": "BACKGROUND",
        "description": (
            "Ne Background gjithmon vendoset fotoja e setit. Nese nuk ka foto ne set ateher vendoset foto e type "
            "me background. Foto e background nuk duhet te preket me kockat -> duhet te kete hapesire mes kockave "
            "dhe setit mbrapa."
        ),
    },
    {
        "title": "PIKAT E SELLING IMAGE 1",
        "keyword": "EMERTIMI",
        "description": (
            "MST: Selling image 1 duhet gjithmone te emertohet kodi i produktit SKU (KODI I MST) dhe _1."
        ),
    },
    {
        "title": "PIKAT E SELLING IMAGE 1",
        "keyword": "EMERTIMI",
        "description": (
            "MST: Selling image 2 (Dimensionet / L/R ) duhet gjithmone te emertohet kodi i produktit SKU (KODI I MST) dhe _2."
        ),
    },
    {
        "title": "PIKAT E SELLING IMAGE 1",
        "keyword": "EMERTIMI",
        "description": (
            "OTTO: Selling image 1 duhet gjithmone te emertohet kodi i produktit Article code (KODI I OTTOs) dhe _1. "
            "Kur behet emertimi i fotove me kod te OTTOs duhet te kemi shume kujdes dhe patjeter te behen 2 kontrolla."
        ),
    },
    {
        "title": "PIKAT E SELLING IMAGE 1",
        "keyword": "EMERTIMI",
        "description": (
            "MST: Selling image 3 (Variacioni) duhet gjithmone te emertohet kodi i produktit SKU (KODI I MST) dhe _3."
        ),
    },
]
GD_MST_VITRINE_COMBINED_EMERTIMI_DESCRIPTION = (
    "MST: Selling image 1 duhet gjithmone te emertohet kodi i produktit SKU (KODI I MST) dhe _1. "
    "MST: Selling image 2 (Dimensionet / L/R ) duhet gjithmone te emertohet kodi i produktit SKU "
    "(KODI I MST) dhe _2. MST: Selling image 3 (Variacioni) duhet gjithmone te emertohet kodi i produktit "
    "SKU (KODI I MST) dhe _3."
)
GD_MST_SIDEBOARD_NEW_TEMPLATE: list[dict[str, str]] = [
    {
        "title": "PIKAT E SELLING IMAGE",
        "keyword": "PIKAT GJENERALE- SELLING IMAGE_1",
        "description": (
            "(Teksti nga foto shembull): 1. Front und Oberplatte aus glänzendem Glas. 2. "
            "Soft-Close Scharniere. 3. Hochwertige Metallgriffe. 4. ABS-Kanten."
        ),
    },
    {
        "title": "PIKAT E SELLING IMAGE",
        "keyword": "PIKAT GJENERALE- SELLING IMAGE_2",
        "description": (
            "Selling image_2 L/R (Mounting Options). Teksti duhet te jete Front links oder rechts montierbar ose "
            "Modernes Sideboard mit drei Varianten ( Kategoria + Nese produkti ka me shume variante ). Produkti "
            "duhet te jete ne vij te njejt e majta dhe e djathta jo njera me lart tjetra me posht."
        ),
    },
    {
        "title": "PIKAT E SELLING IMAGE",
        "keyword": "PIKAT GJENERALE- SELLING IMAGE_3",
        "description": (
            "Selling image_3 Varacione. Foto e background duhet te jete gjithmon white background perspektiv. "
            "Duhet te I kete 4 katrora me te dhena: 1. Duhet te jete teksti Farbauswahl dhe ngjyra e varacionit "
            "te ndryshohet varesisht nga produkti. 2. Nuk ndryshon. Teksti: Metallfüsse: 3 kembet e vitrinet dhe "
            "3 ngjyrat e kembve. 3. Teksti Sockel dhe foto duhet te ndryshohet njejt si ngjyra e produktit, foto "
            "duhet te vendoset ne pozicion njejt si ne template jo me lart ose me posht. 4. Teksti Gleiter dhe "
            "foto duhet te jete e produktit pa kembe dhe te vendoset njejt si ne template."
        ),
    },
    {
        "title": "PIKAT E SELLING IMAGE",
        "keyword": "LOGO",
        "description": (
            "1. Gjithmone logo e klientit e konfirmuar me email (Set One) ose (MST) vendoset larte majtas fotos. "
            "2. Gjithmone logoja e garancise 5 vite vendoset poshte majtas fotos. Ne baze te ngjyrave te fotos "
            "zgjedhen edhe ngjyrat e logos qe do te perdorim. BACKGORUNDED QE KANE NGJYRE TE ERRET PERDORET LOGO "
            "E BARDHE. BACKGROUNDET QE KANE NGJYRE TE HAPUR PERDORET LOGO E ZEZE. Në të 3 Selling Images përdoret "
            "e njëjta logo e KONF, në pozicion fiks dhe të pandryshueshëm. E njëjta gjë vlen edhe për ikonën e "
            "garancisë."
        ),
    },
    {
        "title": "PIKAT E SELLING IMAGE",
        "keyword": "BACKGROUND",
        "description": (
            "Ne Background gjithmon vendoset fotoja e setit. Nese nuk ka foto ne set ateher vendoset foto e type "
            "me background. Foto e background nuk duhet të preket me kockat -> duhet të ketë hapësirë mes "
            "kockave dhe setit mbrapa."
        ),
    },
    {
        "title": "PIKAT E SELLING IMAGE",
        "keyword": "EMERTIMI",
        "description": (
            "MST: Selling image 1 duhet gjithmone te emertohet kodi i produktit SKU (KODI I MST) dhe _1. "
            "MST: Selling image 2 (Dimensionet / L/R ) duhet gjithmone te emertohet kodi i produktit SKU (KODI I MST) "
            "dhe _2. MST: Selling image 3 (Variacioni) duhet gjithmone te emertohet kodi i produktit SKU (KODI I MST) "
            "dhe _3."
        ),
    },
    {
        "title": "PIKAT E SELLING IMAGE",
        "keyword": "EMERTIMI",
        "description": (
            "OTTO: Selling image 1 duhet gjithmone te emertohet kodi i produktit Article code (KODI I OTTOs) dhe _1. "
            "Kur behet emertimi i fotove me kod te OTTOs duhet te kemi shume kujdes dhe patjeter te behen 2 kontrolla."
        ),
    },
]
GD_MST_LOWBOARD_TEMPLATE: list[dict[str, str]] = [
    {
        "title": "PIKAT E SELLING IMAGE",
        "keyword": "PIKAT GJENERALE- SELLING IMAGE_1",
        "description": (
            "Foto Gjenerale 1 ka 4 foto vetem foto e Front Glas dhe foto e Griffe ndryshon sipas ngjyres. "
            "Foto e backgroundit ndryshon. Teksti duhet te jete gjithmon I njejte vetem foto mund te ndryshohen: "
            "1. Front und Oberplatte aus glänzendem Glas. 2. Soft-Close Scharniere. 3. Hochwertige Metallgriffe. "
            "4. ABS-Kanten. Orientimi i fotos se produktit ne background (horizontal/vertikal) zgjidhet sipas "
            "produktit, për ta shfaqur atë në mënyrën më optimale."
        ),
    },
    {
        "title": "PIKAT E SELLING IMAGE",
        "keyword": "PIKAT GJENERALE- SELLING IMAGE_2",
        "description": (
            "Selling image_2 L/R (Mounting Options). Teksti duhet te jete Front links oder rechts montierbar ose "
            "Modernes Sideboard mit drei Varianten ( Kategoria + Nese produkti ka me shume variante ). Produkti "
            "duhet te jete ne vij te njejt e majta dhe e djathta jo njera me lart tjetra me posht."
        ),
    },
    {
        "title": "PIKAT E SELLING IMAGE",
        "keyword": "PIKAT GJENERALE- SELLING IMAGE_3",
        "description": (
            "Selling image_3 Varacione. Foto e background duhet te jete gjithmon white background perspektiv. "
            "Duhet te I kete 4 katrora me te dhena: 1. Duhet te jete teksti Farbauswahl dhe ngjyra e varacionit "
            "te ndryshohet varesisht nga produkti. 2. Nuk ndryshon. Teksti: Metallfüsse: 3 kembet e vitrinet dhe "
            "3 ngjyrat e kembve. 3. Teksti Sockel dhe foto duhet te ndryshohet njejt si ngjyra e produktit, foto "
            "duhet te vendoset ne pozicion njejt si ne template jo me lart ose me posht. 4. Teksti Gleiter dhe "
            "foto duhet te jete e produktit pa kembe dhe te vendoset njejt si ne template."
        ),
    },
    {
        "title": "PIKAT E SELLING IMAGE",
        "keyword": "LOGO",
        "description": (
            "1. Gjithmone logo e klientit e konfirmuar me email (Set One) ose (MST) vendoset larte majtas fotos. "
            "2. Gjithmone logoja e garancise 5 vite vendoset poshte majtas fotos. Ne baze te ngjyrave te fotos "
            "zgjedhen edhe ngjyrat e logos qe do te perdorim. Në të 3 Selling Images përdoret e njëjta logo e KONF, "
            "në pozicion fiks dhe të pandryshueshëm. E njëjta gjë vlen edhe për ikonën e garancisë."
        ),
    },
    {
        "title": "PIKAT E SELLING IMAGE",
        "keyword": "BACKGROUND",
        "description": (
            "Ne Background gjithmon vendoset fotoja e setit. Nese nuk ka foto ne set ateher vendoset foto e type "
            "me background. Foto e background nuk duhet të preket me kockat → duhet të ketë hapësirë mes kockave "
            "dhe setit mbrapa."
        ),
    },
    {
        "title": "PIKAT E SELLING IMAGE",
        "keyword": "EMERTIMI",
        "description": (
            "MST: Selling image 1 duhet gjithmone te emertohet kodi i produktit SKU (KODI I MST) dhe _1. "
            "MST: Selling image 2 (Dimensionet / L/R ) duhet gjithmone te emertohet kodi i produktit SKU (KODI I MST) "
            "dhe _2. MST: Selling image 3 (Variacioni) duhet gjithmone te emertohet kodi i produktit SKU (KODI I MST) "
            "dhe _3."
        ),
    },
    {
        "title": "PIKAT E SELLING IMAGE",
        "keyword": "EMERTIMI",
        "description": (
            "OTTO: Selling image 1 duhet gjithmone te emertohet kodi i produktit Article code (KODI I OTTOs) dhe _1. "
            "Kur behet emertimi I fotove me kod te OTTOs duhet te kemi shume kujdes dhe patjeter te behen 2 kontrolla."
        ),
    },
]


async def _ensure_project_member_or_manager(
    db: AsyncSession,
    user,
    project_id: uuid.UUID,
) -> None:
    if user.role in ("ADMIN", "MANAGER"):
        return
    member = (
        await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")




async def _ensure_gd_project_acceptance_items(db: AsyncSession, project: Project) -> None:
    """
    Ensure the GD "Pranimi i Projektit" checklist exists for a project.

    - Does NOT delete anything.
    - Idempotent: only inserts missing items.
    - Stores items with path = "project acceptance" as requested.
    """
    if project.department_id is None:
        return

    dept = (
        await db.execute(select(Department).where(Department.id == project.department_id))
    ).scalar_one_or_none()
    if dept is None or dept.code != "GD":
        return

    # If the project already has any acceptance items with the requested path, only backfill missing titles.
    existing_items = (
        await db.execute(
            select(ChecklistItem)
            .join(Checklist, ChecklistItem.checklist_id == Checklist.id)
            .where(
                Checklist.project_id == project.id,
                ChecklistItem.path == PROJECT_ACCEPTANCE_PATH,
                ChecklistItem.item_type == ChecklistItemType.CHECKBOX,
            )
        )
    ).scalars().all()
    existing_titles = {i.title for i in existing_items if i.title}

    missing = [t for t in GD_PROJECT_ACCEPTANCE_TEMPLATE if t not in existing_titles]
    if not missing:
        return

    # Use the default (group_key is NULL) project checklist so it stays consistent with existing behavior.
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

    for position, title in enumerate(GD_PROJECT_ACCEPTANCE_TEMPLATE):
        if title in existing_titles:
            continue
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

    await db.commit()


async def _ensure_gd_ga_dv_meeting_items(db: AsyncSession, project: Project) -> None:
    """
    Ensure the GD "Takim me GA/DV" checklist exists for a project.

    - Does NOT delete anything.
    - Idempotent: only inserts missing items.
    - Stores items with path = "ga/dv meeting" as requested.
    """
    if project.department_id is None:
        return

    dept = (
        await db.execute(select(Department).where(Department.id == project.department_id))
    ).scalar_one_or_none()
    if dept is None or dept.code != "GD":
        return

    existing_items = (
        await db.execute(
            select(ChecklistItem)
            .join(Checklist, ChecklistItem.checklist_id == Checklist.id)
            .where(
                Checklist.project_id == project.id,
                ChecklistItem.path == GA_DV_MEETING_PATH,
                ChecklistItem.item_type == ChecklistItemType.CHECKBOX,
            )
        )
    ).scalars().all()
    existing_titles = {i.title for i in existing_items if i.title}

    missing = [t for t in GD_GA_DV_MEETING_TEMPLATE if t not in existing_titles]
    if not missing:
        return

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

    for position, title in enumerate(GD_GA_DV_MEETING_TEMPLATE):
        if title in existing_titles:
            continue
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

    await db.commit()


async def _ensure_gd_propozim_ko1_ko2_items(db: AsyncSession, project: Project) -> None:
    """
    Ensure the GD "PROPOZIM KO1/KO2" checklist exists for a project.

    - Does NOT delete anything.
    - Idempotent: only inserts missing items.
    - Stores items with path = "propozim ko1/ko2" as requested.
    """
    if project.department_id is None:
        return

    dept = (
        await db.execute(select(Department).where(Department.id == project.department_id))
    ).scalar_one_or_none()
    if dept is None or dept.code != "GD":
        return

    existing_items = (
        await db.execute(
            select(ChecklistItem)
            .join(Checklist, ChecklistItem.checklist_id == Checklist.id)
            .where(
                Checklist.project_id == project.id,
                ChecklistItem.path == PROPOZIM_KO1_KO2_PATH,
                ChecklistItem.item_type == ChecklistItemType.CHECKBOX,
            )
        )
    ).scalars().all()
    existing_titles = {i.title for i in existing_items if i.title}

    missing = [t for t in GD_PROPOZIM_KO1_KO2_TEMPLATE if t not in existing_titles]
    if not missing:
        return

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

    for position, title in enumerate(GD_PROPOZIM_KO1_KO2_TEMPLATE):
        if title in existing_titles:
            continue
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

    await db.commit()


async def _ensure_gd_punimi_items(db: AsyncSession, project: Project) -> None:
    """
    Ensure the GD "PUNIMI" checklist exists for a project.

    - Does NOT delete anything.
    - Idempotent: only inserts missing items.
    - Stores items with path = "punimi" as requested.
    """
    if project.department_id is None:
        return

    dept = (
        await db.execute(select(Department).where(Department.id == project.department_id))
    ).scalar_one_or_none()
    if dept is None or dept.code != "GD":
        return

    existing_items = (
        await db.execute(
            select(ChecklistItem)
            .join(Checklist, ChecklistItem.checklist_id == Checklist.id)
            .where(
                Checklist.project_id == project.id,
                ChecklistItem.path == PUNIMI_PATH,
                ChecklistItem.item_type == ChecklistItemType.CHECKBOX,
            )
        )
    ).scalars().all()
    existing_titles = {i.title for i in existing_items if i.title}

    missing = [t for t in GD_PUNIMI_TEMPLATE if t not in existing_titles]
    if not missing:
        return

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

    for position, title in enumerate(GD_PUNIMI_TEMPLATE):
        if title in existing_titles:
            continue
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

    await db.commit()


async def _ensure_gd_control_ko1_ko2_items(db: AsyncSession, project: Project) -> None:
    """
    Ensure the GD "përgatitja për dÃ«rgim KO1/KO2" checklist exists for a project.

    - Does NOT delete anything.
    - Idempotent: only inserts missing items.
    - Stores items with path = "control ko1/ko2" as requested.
    """
    if project.department_id is None:
        return

    dept = (
        await db.execute(select(Department).where(Department.id == project.department_id))
    ).scalar_one_or_none()
    if dept is None or dept.code != "GD":
        return

    existing_items = (
        await db.execute(
            select(ChecklistItem)
            .join(Checklist, ChecklistItem.checklist_id == Checklist.id)
            .where(
                Checklist.project_id == project.id,
                ChecklistItem.path == CONTROL_KO1_KO2_PATH,
                ChecklistItem.item_type == ChecklistItemType.CHECKBOX,
            )
        )
    ).scalars().all()
    existing_titles = {i.title for i in existing_items if i.title}

    missing = [t for t in GD_CONTROL_KO1_KO2_TEMPLATE if t not in existing_titles]
    if not missing:
        return

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

    for position, title in enumerate(GD_CONTROL_KO1_KO2_TEMPLATE):
        if title in existing_titles:
            continue
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

    await db.commit()


async def _ensure_gd_finalization_items(db: AsyncSession, project: Project) -> None:
    """
    Ensure the GD "Finalizimi" checklist exists for a project.

    - Does NOT delete anything.
    - Idempotent: only inserts missing items.
    - Stores items with path = "finalization" as requested.
    """
    if project.department_id is None:
        return

    dept = (
        await db.execute(select(Department).where(Department.id == project.department_id))
    ).scalar_one_or_none()
    if dept is None or dept.code != "GD":
        return

    existing_items = (
        await db.execute(
            select(ChecklistItem)
            .join(Checklist, ChecklistItem.checklist_id == Checklist.id)
            .where(
                Checklist.project_id == project.id,
                ChecklistItem.path == FINALIZATION_PATH,
                ChecklistItem.item_type == ChecklistItemType.CHECKBOX,
            )
        )
    ).scalars().all()
    existing_titles = {i.title for i in existing_items if i.title}

    missing = [t for t in GD_FINALIZATION_TEMPLATE if t not in existing_titles]
    if not missing:
        return

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

    for position, title in enumerate(GD_FINALIZATION_TEMPLATE):
        if title in existing_titles:
            continue
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


async def _is_gd_mst_planning(db: AsyncSession, project: Project) -> bool:
    if project.department_id is None:
        return False

    dept = (
        await db.execute(select(Department).where(Department.id == project.department_id))
    ).scalar_one_or_none()
    if dept is None or dept.code != "GD":
        return False

    if not has_mst_identity(project):
        return False

    phase = (project.current_phase or "").upper()
    return phase in ("PLANNING", "PLANIFIKIMI")


async def _ensure_gd_mst_section_items(
    db: AsyncSession,
    project: Project,
    path: str,
    template: list[str],
) -> None:
    """
    Ensure a GD MST Planning checklist section exists for a project.

    - Does NOT delete anything.
    - Idempotent: only inserts missing items.
    - Stores items with the provided path.
    """
    if not template:
        return

    existing_items = (
        await db.execute(
            select(ChecklistItem)
            .join(Checklist, ChecklistItem.checklist_id == Checklist.id)
            .where(
                Checklist.project_id == project.id,
                ChecklistItem.path == path,
                ChecklistItem.item_type == ChecklistItemType.CHECKBOX,
            )
        )
    ).scalars().all()
    existing_titles = {i.title for i in existing_items if i.title}

    missing = [t for t in template if t not in existing_titles]
    if not missing:
        return

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

    for position, title in enumerate(template):
        if title in existing_titles:
            continue
        db.add(
            ChecklistItem(
                checklist_id=checklist.id,
                item_type=ChecklistItemType.CHECKBOX,
                position=position,
                path=path,
                title=title,
                is_checked=False,
            )
        )

    await db.commit()


def _normalize_template_key(title: str | None, keyword: str | None, description: str | None) -> tuple[str, str, str]:
    return (
        (title or "").strip().lower(),
        (keyword or "").strip().lower(),
        (description or "").strip().lower(),
    )


async def _ensure_gd_mst_sofa_new_template(db: AsyncSession) -> None:
    """
    Ensure global template checklist for GD MST SOFA NEW exists.

    - Does NOT delete anything.
    - Idempotent: only inserts missing items.
    """
    if not GD_MST_SOFA_NEW_TEMPLATE:
        return

    checklist = (
        await db.execute(
            select(Checklist)
            .options(selectinload(Checklist.items))
            .where(Checklist.group_key == GD_MST_SOFA_NEW_PATH, Checklist.project_id.is_(None))
        )
    ).scalar_one_or_none()
    if checklist is None:
        checklist = Checklist(title="GD MST SOFA NEW (Template)", group_key=GD_MST_SOFA_NEW_PATH, position=0)
        db.add(checklist)
        await db.flush()
        await db.refresh(checklist)

    existing_items = checklist.items if checklist.items else []
    existing_keys = {
        _normalize_template_key(item.title, item.keyword, item.description)
        for item in existing_items
    }

    for position, row in enumerate(GD_MST_SOFA_NEW_TEMPLATE):
        key = _normalize_template_key(row.get("title"), row.get("keyword"), row.get("description"))
        if key in existing_keys:
            continue
        db.add(
            ChecklistItem(
                checklist_id=checklist.id,
                item_type=ChecklistItemType.CHECKBOX,
                position=position,
                path=GD_MST_SOFA_NEW_PATH,
                title=row.get("title"),
                keyword=row.get("keyword"),
                description=row.get("description"),
                is_checked=False,
            )
        )
        existing_keys.add(key)

    await db.commit()


async def _ensure_gd_mst_vitrine_new_template(db: AsyncSession) -> None:
    """
    Ensure global template checklist for GD MST VITRINE NEW exists.

    - Does NOT delete anything.
    - Idempotent: only inserts missing items.
    """
    if not GD_MST_VITRINE_NEW_TEMPLATE:
        return

    checklist = (
        await db.execute(
            select(Checklist)
            .options(selectinload(Checklist.items))
            .where(Checklist.group_key == GD_MST_VITRINE_NEW_PATH, Checklist.project_id.is_(None))
        )
    ).scalar_one_or_none()
    if checklist is None:
        checklist = Checklist(
            title="GD MST VITRINE NEW (Template)",
            group_key=GD_MST_VITRINE_NEW_PATH,
            position=0,
        )
        db.add(checklist)
        await db.flush()
        checklist = (
            await db.execute(
                select(Checklist)
                .options(selectinload(Checklist.items))
                .where(Checklist.id == checklist.id)
            )
        ).scalar_one()

    await _remove_gd_mst_vitrine_combined_row(db)

    existing_items = checklist.items if checklist.items else []
    existing_keys = {
        _normalize_template_key(item.title, item.keyword, item.description)
        for item in existing_items
    }

    for position, row in enumerate(GD_MST_VITRINE_NEW_TEMPLATE):
        key = _normalize_template_key(row.get("title"), row.get("keyword"), row.get("description"))
        if key in existing_keys:
            continue
        db.add(
            ChecklistItem(
                checklist_id=checklist.id,
                item_type=ChecklistItemType.CHECKBOX,
                position=position,
                path=GD_MST_VITRINE_NEW_PATH,
                title=row.get("title"),
                keyword=row.get("keyword"),
                description=row.get("description"),
                is_checked=False,
            )
        )
        existing_keys.add(key)

    await db.commit()


async def _ensure_gd_mst_sideboard_new_template(db: AsyncSession) -> None:
    """
    Ensure global template checklist for GD MST SIDEBOARD NEW exists.

    - Does NOT delete anything.
    - Idempotent: only inserts missing items.
    """
    if not GD_MST_SIDEBOARD_NEW_TEMPLATE:
        return

    checklist = (
        await db.execute(
            select(Checklist)
            .options(selectinload(Checklist.items))
            .where(Checklist.group_key == GD_MST_SIDEBOARD_NEW_PATH, Checklist.project_id.is_(None))
        )
    ).scalar_one_or_none()
    if checklist is None:
        checklist = Checklist(
            title="GD MST SIDEBOARD NEW (Template)",
            group_key=GD_MST_SIDEBOARD_NEW_PATH,
            position=0,
        )
        db.add(checklist)
        await db.flush()
        checklist = (
            await db.execute(
                select(Checklist)
                .options(selectinload(Checklist.items))
                .where(Checklist.id == checklist.id)
            )
        ).scalar_one()

    existing_items = checklist.items if checklist.items else []
    existing_keys = {
        _normalize_template_key(item.title, item.keyword, item.description)
        for item in existing_items
    }

    for position, row in enumerate(GD_MST_SIDEBOARD_NEW_TEMPLATE):
        key = _normalize_template_key(row.get("title"), row.get("keyword"), row.get("description"))
        if key in existing_keys:
            continue
        db.add(
            ChecklistItem(
                checklist_id=checklist.id,
                item_type=ChecklistItemType.CHECKBOX,
                position=position,
                path=GD_MST_SIDEBOARD_NEW_PATH,
                title=row.get("title"),
                keyword=row.get("keyword"),
                description=row.get("description"),
                is_checked=False,
            )
        )
        existing_keys.add(key)

    await db.commit()


async def _ensure_gd_mst_lowboard_template(db: AsyncSession) -> None:
    """
    Ensure global template checklist for GD MST LOWBOARD exists.

    - Does NOT delete anything.
    - Idempotent: only inserts missing items.
    """
    if not GD_MST_LOWBOARD_TEMPLATE:
        return

    checklist = (
        await db.execute(
            select(Checklist)
            .options(selectinload(Checklist.items))
            .where(Checklist.group_key == GD_MST_LOWBOARD_PATH, Checklist.project_id.is_(None))
        )
    ).scalar_one_or_none()
    if checklist is None:
        checklist = Checklist(
            title="GD MST LOWBOARD (Template)",
            group_key=GD_MST_LOWBOARD_PATH,
            position=0,
        )
        db.add(checklist)
        await db.flush()
        checklist = (
            await db.execute(
                select(Checklist)
                .options(selectinload(Checklist.items))
                .where(Checklist.id == checklist.id)
            )
        ).scalar_one()

    existing_items = checklist.items if checklist.items else []
    existing_keys = {
        _normalize_template_key(item.title, item.keyword, item.description)
        for item in existing_items
    }

    for position, row in enumerate(GD_MST_LOWBOARD_TEMPLATE):
        key = _normalize_template_key(row.get("title"), row.get("keyword"), row.get("description"))
        if key in existing_keys:
            continue
        db.add(
            ChecklistItem(
                checklist_id=checklist.id,
                item_type=ChecklistItemType.CHECKBOX,
                position=position,
                path=GD_MST_LOWBOARD_PATH,
                title=row.get("title"),
                keyword=row.get("keyword"),
                description=row.get("description"),
                is_checked=False,
            )
        )
        existing_keys.add(key)

    await db.commit()


async def _remove_gd_mst_vitrine_combined_row(
    db: AsyncSession,
    project_id: uuid.UUID | None = None,
) -> None:
    filters = [
        ChecklistItem.path == GD_MST_VITRINE_NEW_PATH,
        ChecklistItem.title == "PIKAT E SELLING IMAGE 1",
        ChecklistItem.keyword == "EMERTIMI",
        ChecklistItem.description == GD_MST_VITRINE_COMBINED_EMERTIMI_DESCRIPTION,
    ]

    stmt = select(ChecklistItem).join(Checklist, ChecklistItem.checklist_id == Checklist.id)
    if project_id is None:
        stmt = stmt.where(Checklist.group_key == GD_MST_VITRINE_NEW_PATH, Checklist.project_id.is_(None))
    else:
        stmt = stmt.where(Checklist.project_id == project_id)
    stmt = stmt.where(*filters)

    items = (await db.execute(stmt)).scalars().all()
    if not items:
        return

    for item in items:
        await db.delete(item)
    await db.commit()


async def _ensure_gd_mst_vitrine_otto_last(
    db: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    items = (
        await db.execute(
            select(ChecklistItem)
            .join(Checklist, ChecklistItem.checklist_id == Checklist.id)
            .where(
                Checklist.project_id == project_id,
                ChecklistItem.path == GD_MST_VITRINE_NEW_PATH,
                ChecklistItem.title == "PIKAT E SELLING IMAGE 1",
                ChecklistItem.keyword == "EMERTIMI",
                ChecklistItem.description.like("OTTO: Selling image 1%"),
            )
            .order_by(ChecklistItem.position, ChecklistItem.id)
        )
    ).scalars().all()
    if not items:
        return

    otto_item = items[0]
    max_position = (
        await db.execute(
            select(func.max(ChecklistItem.position))
            .join(Checklist, ChecklistItem.checklist_id == Checklist.id)
            .where(
                Checklist.project_id == project_id,
                ChecklistItem.path == GD_MST_VITRINE_NEW_PATH,
            )
        )
    ).scalar_one_or_none()
    max_position = max_position or 0
    if otto_item.position != max_position:
        otto_item.position = max_position + 1
        await db.commit()

    ordered_items = (
        await db.execute(
            select(ChecklistItem)
            .join(Checklist, ChecklistItem.checklist_id == Checklist.id)
            .where(
                Checklist.project_id == project_id,
                ChecklistItem.path == GD_MST_VITRINE_NEW_PATH,
            )
            .order_by(ChecklistItem.position, ChecklistItem.id)
        )
    ).scalars().all()
    if not ordered_items:
        return

    for index, item in enumerate(ordered_items):
        if item.position != index:
            item.position = index
    await db.commit()


async def _ensure_gd_mst_section_from_template(
    db: AsyncSession,
    project: Project,
    path: str,
    template_group_key: str,
) -> None:
    """
    Ensure a GD MST Planning checklist section exists for a project from a template checklist.

    - Does NOT delete anything.
    - Idempotent: only inserts missing items.
    - Stores items with the provided path.
    """
    template_checklist = (
        await db.execute(
            select(Checklist)
            .options(selectinload(Checklist.items))
            .where(Checklist.group_key == template_group_key, Checklist.project_id.is_(None))
        )
    ).scalar_one_or_none()
    if template_checklist is None or not template_checklist.items:
        return

    existing_items = (
        await db.execute(
            select(ChecklistItem)
            .join(Checklist, ChecklistItem.checklist_id == Checklist.id)
            .where(
                Checklist.project_id == project.id,
                ChecklistItem.path == path,
                ChecklistItem.item_type == ChecklistItemType.CHECKBOX,
            )
        )
    ).scalars().all()
    existing_keys = {
        _normalize_template_key(item.title, item.keyword, item.description)
        for item in existing_items
    }

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

    template_items = sorted(template_checklist.items, key=lambda item: (item.position, item.id))
    for template_item in template_items:
        title = (template_item.title or "").strip()
        if not title:
            continue
        key = _normalize_template_key(title, template_item.keyword, template_item.description)
        if key in existing_keys:
            continue
        db.add(
            ChecklistItem(
                checklist_id=checklist.id,
                item_type=ChecklistItemType.CHECKBOX,
                position=template_item.position,
                path=path,
                keyword=template_item.keyword,
                description=template_item.description,
                category=template_item.category,
                original=template_item.original,
                owner=template_item.owner,
                comment=template_item.comment,
                title=title,
                is_checked=False,
            )
        )
        existing_keys.add(key)

    await db.commit()


def _item_to_out(item: ChecklistItem) -> ChecklistItemOut:
    """Convert ChecklistItem model to ChecklistItemOut schema."""
    assignees = [
        ChecklistItemAssigneeOut(
            user_id=assignee.user_id,
            user_full_name=assignee.user.full_name if assignee.user else None,
            user_username=assignee.user.username if assignee.user else None,
        )
        for assignee in item.assignees
    ]
    
    return ChecklistItemOut(
        id=item.id,
        checklist_id=item.checklist_id,
        item_type=item.item_type,
        position=item.position,
        path=item.path,
        keyword=item.keyword,
        description=item.description,
        category=item.category,
        original=item.original,
        day=item.day,
        owner=item.owner,
        time=item.time,
        title=item.title,
        comment=item.comment,
        is_checked=item.is_checked,
        assignees=assignees,
    )


async def _reorder_checklist_item(
    db: AsyncSession,
    item: ChecklistItem,
    requested_position: int,
) -> None:
    """Move an item to a 1-based display position and normalize sibling positions."""
    if item.checklist_id is None:
        item.position = max(1, requested_position)
        return

    path_filter = ChecklistItem.path.is_(None) if item.path is None else ChecklistItem.path == item.path
    siblings = (
        await db.execute(
            select(ChecklistItem)
            .where(ChecklistItem.checklist_id == item.checklist_id, path_filter)
            .order_by(ChecklistItem.position, ChecklistItem.id)
        )
    ).scalars().all()

    ordered = [sibling for sibling in siblings if sibling.id != item.id]
    insert_index = max(0, min(requested_position - 1, len(ordered)))
    ordered.insert(insert_index, item)

    for index, sibling in enumerate(ordered, start=1):
        sibling.position = index


@router.get("", response_model=list[ChecklistItemOut])
async def list_checklist_items(
    project_id: uuid.UUID | None = None,
    checklist_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[ChecklistItemOut]:
    if project_id is None and checklist_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="project_id or checklist_id required")

    if project_id is not None:
        project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

        # Auto-seed GD "Pranimi i Projektit" checklist (no deletes, only inserts missing items).
        await _ensure_gd_project_acceptance_items(db, project)
        # Auto-seed GD "Takim me GA/DV" checklist (no deletes, only inserts missing items).
        await _ensure_gd_ga_dv_meeting_items(db, project)
        # Auto-seed GD "PROPOZIM KO1/KO2" checklist (no deletes, only inserts missing items).
        await _ensure_gd_propozim_ko1_ko2_items(db, project)
        # Auto-seed GD "PUNIMI" checklist (no deletes, only inserts missing items).
        await _ensure_gd_punimi_items(db, project)
        # Auto-seed GD "përgatitja për dÃ«rgim KO1/KO2" checklist (no deletes, only inserts missing items).
        await _ensure_gd_control_ko1_ko2_items(db, project)
        # Auto-seed GD "Finalizimi" checklist (no deletes, only inserts missing items).
        await _ensure_gd_finalization_items(db, project)
        # Auto-seed GD MST Planning checklist sections (no deletes, only inserts missing items).
        if await _is_gd_mst_planning(db, project):
            await _ensure_gd_mst_section_from_template(
                db, project, GD_MST_GJENERALE_PATH, GD_MST_GJENERALE_PATH
            )
            await _ensure_gd_mst_sofa_new_template(db)
            await _ensure_gd_mst_section_from_template(
                db, project, GD_MST_SOFA_NEW_PATH, GD_MST_SOFA_NEW_PATH
            )
            await _remove_gd_mst_vitrine_combined_row(db, project.id)
            await _ensure_gd_mst_vitrine_new_template(db)
            await _ensure_gd_mst_section_from_template(
                db, project, GD_MST_VITRINE_NEW_PATH, GD_MST_VITRINE_NEW_PATH
            )
            await _ensure_gd_mst_vitrine_otto_last(db, project.id)
            await _ensure_gd_mst_sideboard_new_template(db)
            await _ensure_gd_mst_section_from_template(
                db, project, GD_MST_SIDEBOARD_NEW_PATH, GD_MST_SIDEBOARD_NEW_PATH
            )
            await _ensure_gd_mst_lowboard_template(db)
            await _ensure_gd_mst_section_from_template(
                db, project, GD_MST_LOWBOARD_PATH, GD_MST_LOWBOARD_PATH
            )

        stmt = (
            select(ChecklistItem)
            .options(selectinload(ChecklistItem.assignees).selectinload(ChecklistItemAssignee.user))
            .join(Checklist, ChecklistItem.checklist_id == Checklist.id)
            .where(Checklist.project_id == project_id)
            .order_by(ChecklistItem.position, ChecklistItem.id)
        )
    else:
        stmt = (
            select(ChecklistItem)
            .options(selectinload(ChecklistItem.assignees).selectinload(ChecklistItemAssignee.user))
            .where(ChecklistItem.checklist_id == checklist_id)
            .order_by(ChecklistItem.position, ChecklistItem.id)
        )

    items = (await db.execute(stmt)).scalars().all()
    return [_item_to_out(item) for item in items]


class ChecklistItemCreateWithProject(BaseModel):
    """Wrapper to support project_id in create payload."""
    project_id: uuid.UUID | None = None
    checklist_id: uuid.UUID | None = None
    group_key: str | None = None
    checklist_title: str | None = None
    item_type: ChecklistItemType | None = None
    position: int | None = None
    path: str | None = None
    keyword: str | None = None
    description: str | None = None
    category: str | None = None
    original: str | None = None
    day: str | None = None
    owner: str | None = None
    time: str | None = None
    title: str | None = None
    content: str | None = None
    comment: str | None = None
    is_checked: bool | None = None
    assignee_user_ids: list[uuid.UUID] = []


@router.post("", response_model=ChecklistItemOut, status_code=status.HTTP_201_CREATED)
async def create_checklist_item(
    payload: ChecklistItemCreateWithProject,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> ChecklistItemOut:
    if payload.project_id is None and payload.checklist_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="project_id or checklist_id required")

    # Validate using the schema validator
    resolved_item_type = payload.item_type
    resolved_title = payload.title or payload.content
    if resolved_item_type is None and (resolved_title or payload.comment):
        resolved_item_type = ChecklistItemType.CHECKBOX
    if resolved_item_type is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="item_type is required")

    create_payload = ChecklistItemCreate(
        checklist_id=payload.checklist_id,
        item_type=resolved_item_type,
        position=payload.position,
        path=payload.path,
        keyword=payload.keyword,
        description=payload.description,
        category=payload.category,
        original=payload.original,
        day=payload.day,
        owner=payload.owner,
        time=payload.time,
        title=payload.title,
        comment=payload.comment,
        is_checked=payload.is_checked,
        assignee_user_ids=payload.assignee_user_ids,
    )

    checklist: Checklist | None = None
    if payload.project_id is not None:
        project = (await db.execute(select(Project).where(Project.id == payload.project_id))).scalar_one_or_none()
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        if project.department_id is not None:
            ensure_department_access(user, project.department_id)

        if payload.group_key is not None:
            # Structured/grouped checklist (admin-managed template-style checklists)
            if user.role != "ADMIN":
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
            checklist = (
                await db.execute(
                    select(Checklist).where(
                        Checklist.project_id == payload.project_id,
                        Checklist.group_key == payload.group_key,
                    )
                )
            ).scalar_one_or_none()
            if checklist is None:
                checklist = Checklist(
                    project_id=payload.project_id,
                    title=payload.checklist_title or payload.group_key,
                    group_key=payload.group_key,
                )
                db.add(checklist)
                await db.flush()
        else:
            # Default checklist for ad-hoc items (avoid colliding with structured/grouped checklists)
            checklist = (
                await db.execute(
                    select(Checklist)
                    .where(Checklist.project_id == payload.project_id, Checklist.group_key.is_(None))
                    .order_by(Checklist.created_at)
                )
            ).scalars().first()
            if checklist is None:
                checklist = Checklist(project_id=payload.project_id, title="Checklist")
                db.add(checklist)
                await db.flush()

    if checklist is None and payload.checklist_id is not None:
        checklist = (
            await db.execute(select(Checklist).where(Checklist.id == payload.checklist_id))
        ).scalar_one_or_none()
        if checklist is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Checklist not found")
        # Global template-style checklists (group_key set, no project/task) are admin-only.
        # Exception: Internal meeting checklists allow department members to create items.
        # Board/Staff meeting templates allow admin/manager.
        if checklist.project_id is None and checklist.task_id is None and checklist.group_key is not None:
            if checklist.group_key in ("board", "staff"):
                ensure_manager_or_admin(user)
            elif checklist.group_key in PRODUCT_TEMPLATE_GROUP_KEYS:
                ensure_manager_or_admin(user)
            else:
                is_internal_meeting = checklist.group_key in ("development_internal_meetings", "pcm_internal_meetings")
                if is_internal_meeting:
                    # Determine department from group_key
                    if checklist.group_key == "development_internal_meetings":
                        dept_name = "Development"
                    elif checklist.group_key == "pcm_internal_meetings":
                        dept_name = "Project Content Manager"
                    else:
                        dept_name = None

                    if dept_name:
                        dept = (
                            await db.execute(
                                select(Department).where(Department.name == dept_name)
                            )
                        ).scalar_one_or_none()
                        if dept:
                            ensure_department_access(user, dept.id)
                        else:
                            if user.role != "ADMIN":
                                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
                    else:
                        if user.role != "ADMIN":
                            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
                else:
                    if user.role != "ADMIN":
                        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
        if checklist.project_id is not None:
            project = (
                await db.execute(select(Project).where(Project.id == checklist.project_id))
            ).scalar_one_or_none()
            if project and project.department_id is not None:
                ensure_department_access(user, project.department_id)
        if checklist.task_id is not None:
            task = (
                await db.execute(select(Task).where(Task.id == checklist.task_id))
            ).scalar_one_or_none()
            if task is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
            if task.project_id is None:
                if user.role not in ("ADMIN", "MANAGER"):
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
            else:
                task_project = (
                    await db.execute(select(Project).where(Project.id == task.project_id))
                ).scalar_one_or_none()
                if task_project and task_project.department_id is not None:
                    ensure_department_access(user, task_project.department_id)

    if checklist is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Checklist resolution failed")

    # Idempotency guard: prevent duplicate inserts when multiple clients/tabs seed the same template at the same time.
    # We treat an item as duplicate if it matches (checklist_id, item_type, path, day, title, keyword, description) case-insensitively.
    if create_payload.item_type == ChecklistItemType.CHECKBOX and create_payload.title:
        normalized_title = create_payload.title.strip().lower()
        normalized_keyword = (create_payload.keyword or "").strip().lower()
        normalized_description = (create_payload.description or "").strip().lower()
        if normalized_title:
            existing = (
                await db.execute(
                    select(ChecklistItem)
                    .options(
                        selectinload(ChecklistItem.assignees).selectinload(ChecklistItemAssignee.user)
                    )
                    .where(
                        ChecklistItem.checklist_id == checklist.id,
                        ChecklistItem.item_type == ChecklistItemType.CHECKBOX,
                        ChecklistItem.path == create_payload.path,
                        ChecklistItem.day == create_payload.day,
                        ChecklistItem.title.isnot(None),
                        func.lower(func.trim(ChecklistItem.title)) == normalized_title,
                        func.lower(func.coalesce(func.trim(ChecklistItem.keyword), "")) == normalized_keyword,
                        func.lower(func.coalesce(func.trim(ChecklistItem.description), "")) == normalized_description,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing is not None:
                return _item_to_out(existing)

    position = create_payload.position
    path_filter = (
        ChecklistItem.path.is_(None)
        if create_payload.path is None
        else ChecklistItem.path == create_payload.path
    )
    if position is None:
        max_position = (
            await db.execute(
                select(ChecklistItem.position)
                .where(ChecklistItem.checklist_id == checklist.id, path_filter)
                .order_by(ChecklistItem.position.desc())
            )
        ).scalars().first()
        position = (max_position + 1) if max_position is not None else 1

    item = ChecklistItem(
        checklist_id=checklist.id,
        item_type=create_payload.item_type,
        position=position,
        path=create_payload.path,
        keyword=create_payload.keyword,
        description=create_payload.description,
        category=create_payload.category,
        original=create_payload.original,
        day=create_payload.day,
        owner=create_payload.owner,
        time=create_payload.time,
        title=create_payload.title,
        comment=create_payload.comment,
        is_checked=create_payload.is_checked,
    )
    db.add(item)
    await db.flush()
    if create_payload.position is not None:
        await _reorder_checklist_item(db, item, create_payload.position)

    # Add assignees
    if create_payload.assignee_user_ids:
        users = (
            await db.execute(select(User).where(User.work_staff_filter()).where(User.id.in_(create_payload.assignee_user_ids)))
        ).scalars().all()
        user_ids = {u.id for u in users}
        for user_id in create_payload.assignee_user_ids:
            if user_id in user_ids:
                assignee = ChecklistItemAssignee(checklist_item_id=item.id, user_id=user_id)
                db.add(assignee)

    await sync_checklist_item_manual_question(
        db,
        checklist,
        title=item.title,
        action="upsert",
    )

    await db.commit()
    item = (
        await db.execute(
            select(ChecklistItem)
            .options(selectinload(ChecklistItem.assignees).selectinload(ChecklistItemAssignee.user))
            .where(ChecklistItem.id == item.id)
        )
    ).scalar_one()

    return _item_to_out(item)


@router.patch("/{item_id}", response_model=ChecklistItemOut | ProjectPhaseChecklistItemOut)
async def update_checklist_item(
    item_id: uuid.UUID,
    payload: ChecklistItemUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> ChecklistItemOut:
    phase_item = (
        await db.execute(
            select(ProjectPhaseChecklistItem).where(ProjectPhaseChecklistItem.id == item_id)
        )
    ).scalar_one_or_none()
    if phase_item is not None:
        project = (
            await db.execute(select(Project).where(Project.id == phase_item.project_id))
        ).scalar_one_or_none()
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        if project.department_id is not None:
            ensure_department_access(user, project.department_id)

        if payload.title is not None:
            title = payload.title.strip()
            if not title:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Title is required")
            phase_item.title = title
        if payload.comment is not None:
            phase_item.comment = payload.comment.strip() if payload.comment else None
        if payload.is_checked is not None:
            phase_item.is_checked = payload.is_checked
        if payload.sort_order is not None:
            phase_item.sort_order = payload.sort_order

        await db.commit()
        await db.refresh(phase_item)
        return ProjectPhaseChecklistItemOut(
            id=phase_item.id,
            project_id=phase_item.project_id,
            phase_key=phase_item.phase_key,
            title=phase_item.title,
            comment=phase_item.comment,
            is_checked=phase_item.is_checked,
            sort_order=phase_item.sort_order,
            created_by=phase_item.created_by,
            created_at=phase_item.created_at,
            updated_at=phase_item.updated_at,
        )

    item = (
        await db.execute(
            select(ChecklistItem)
            .options(selectinload(ChecklistItem.assignees).selectinload(ChecklistItemAssignee.user))
            .where(ChecklistItem.id == item_id)
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Checklist item not found")

    previous_title = item.title
    checklist = None

    if item.checklist_id is not None:
        checklist = (
            await db.execute(select(Checklist).where(Checklist.id == item.checklist_id))
        ).scalar_one_or_none()
        # Global template-style checklists (group_key set, no project/task) are admin-only to edit.
        # Exception: Internal meeting checklists allow department members to update is_checked field.
        # Board/Staff meeting templates allow admin/manager.
        if checklist and checklist.project_id is None and checklist.task_id is None and checklist.group_key is not None:
            if checklist.group_key in ("board", "staff"):
                ensure_manager_or_admin(user)
            elif checklist.group_key in PRODUCT_TEMPLATE_GROUP_KEYS:
                ensure_manager_or_admin(user)
            else:
                is_internal_meeting = checklist.group_key in ("development_internal_meetings", "pcm_internal_meetings")
                # For internal meetings, allow department members to update items.
                if is_internal_meeting:
                    # Determine department from group_key
                    if checklist.group_key == "development_internal_meetings":
                        dept_name = "Development"
                    elif checklist.group_key == "pcm_internal_meetings":
                        dept_name = "Project Content Manager"
                    else:
                        dept_name = None

                    if dept_name:
                        dept = (
                            await db.execute(select(Department).where(Department.name == dept_name))
                        ).scalar_one_or_none()
                        if dept:
                            ensure_department_access(user, dept.id)
                        else:
                            ensure_manager_or_admin(user)
                    else:
                        ensure_manager_or_admin(user)
                else:
                    if user.role != "ADMIN":
                        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
        if checklist and checklist.project_id is not None:
            project = (
                await db.execute(select(Project).where(Project.id == checklist.project_id))
            ).scalar_one_or_none()
            if project is not None:
                await _ensure_project_member_or_manager(db, user, project.id)
        if checklist and checklist.task_id is not None:
            task = (
                await db.execute(select(Task).where(Task.id == checklist.task_id))
            ).scalar_one_or_none()
            if task is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
            if task.project_id is None:
                if user.role not in ("ADMIN", "MANAGER"):
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
            else:
                task_project = (
                    await db.execute(select(Project).where(Project.id == task.project_id))
                ).scalar_one_or_none()
                if task_project and task_project.department_id is not None:
                    ensure_department_access(user, task_project.department_id)
                if (
                    payload.is_checked is False
                    and item.is_checked is True
                    and user.role not in ("ADMIN", "MANAGER")
                ):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Only admins and managers can uncheck subtasks",
                    )

    # Update fields
    if payload.item_type is not None:
        item.item_type = payload.item_type
    if payload.position is not None:
        await _reorder_checklist_item(db, item, payload.position)
    if payload.path is not None:
        item.path = payload.path
    if payload.keyword is not None:
        item.keyword = payload.keyword
    if payload.description is not None:
        item.description = payload.description
    if payload.category is not None:
        item.category = payload.category
    if payload.original is not None:
        item.original = payload.original
    if payload.day is not None:
        item.day = payload.day
    if payload.owner is not None:
        item.owner = payload.owner
    if payload.time is not None:
        item.time = payload.time
    if payload.title is not None:
        item.title = payload.title
    if payload.comment is not None:
        item.comment = payload.comment
    if payload.is_checked is not None:
        item.is_checked = payload.is_checked

    # Update assignees if provided
    if payload.assignee_user_ids is not None:
        # Remove existing assignees
        for assignee in item.assignees:
            await db.delete(assignee)
        await db.flush()

        # Add new assignees
        if payload.assignee_user_ids:
            users = (
                await db.execute(select(User).where(User.work_staff_filter()).where(User.id.in_(payload.assignee_user_ids)))
            ).scalars().all()
            user_ids = {u.id for u in users}
            for user_id in payload.assignee_user_ids:
                if user_id in user_ids:
                    assignee = ChecklistItemAssignee(checklist_item_id=item.id, user_id=user_id)
                    db.add(assignee)

    if payload.title is not None and (previous_title or "") != (item.title or ""):
        await sync_checklist_item_manual_question(
            db,
            checklist,
            title=item.title,
            previous_title=previous_title,
            action="upsert",
        )

    await db.commit()
    item = (
        await db.execute(
            select(ChecklistItem)
            .options(selectinload(ChecklistItem.assignees).selectinload(ChecklistItemAssignee.user))
            .where(ChecklistItem.id == item.id)
        )
    ).scalar_one()

    return _item_to_out(item)


@router.delete("/{item_id}", status_code=status.HTTP_200_OK)
async def delete_checklist_item(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    phase_item = (
        await db.execute(
            select(ProjectPhaseChecklistItem).where(ProjectPhaseChecklistItem.id == item_id)
        )
    ).scalar_one_or_none()
    if phase_item is not None:
        project = (
            await db.execute(select(Project).where(Project.id == phase_item.project_id))
        ).scalar_one_or_none()
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        if project.department_id is not None:
            ensure_department_access(user, project.department_id)
        ensure_manager_or_admin(user)
        await db.delete(phase_item)
        await db.commit()
        return {"ok": True}

    item = (await db.execute(select(ChecklistItem).where(ChecklistItem.id == item_id))).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Checklist item not found")
    checklist = None
    if item.checklist_id is not None:
        checklist = (
            await db.execute(select(Checklist).where(Checklist.id == item.checklist_id))
        ).scalar_one_or_none()
        # Global template-style checklists (group_key set, no project/task) are admin/manager-only to delete.
        # Exception: Internal meeting checklists allow department members to delete items.
        if checklist and checklist.project_id is None and checklist.task_id is None and checklist.group_key is not None:
            is_internal_meeting = checklist.group_key in ("development_internal_meetings", "pcm_internal_meetings")
            if is_internal_meeting:
                # Determine department from group_key
                if checklist.group_key == "development_internal_meetings":
                    dept_name = "Development"
                elif checklist.group_key == "pcm_internal_meetings":
                    dept_name = "Project Content Manager"
                else:
                    dept_name = None

                if dept_name:
                    dept = (
                        await db.execute(select(Department).where(Department.name == dept_name))
                    ).scalar_one_or_none()
                    if dept:
                        ensure_department_access(user, dept.id)
                    else:
                        ensure_manager_or_admin(user)
                else:
                    ensure_manager_or_admin(user)
            else:
                ensure_manager_or_admin(user)
        if checklist and checklist.project_id is not None:
            project = (
                await db.execute(select(Project).where(Project.id == checklist.project_id))
            ).scalar_one_or_none()
            if project is not None:
                await _ensure_project_member_or_manager(db, user, project.id)
        if checklist and checklist.task_id is not None:
            task = (
                await db.execute(select(Task).where(Task.id == checklist.task_id))
            ).scalar_one_or_none()
            if task is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
            if task.project_id is None:
                if user.role not in ("ADMIN", "MANAGER"):
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
            else:
                task_project = (
                    await db.execute(select(Project).where(Project.id == task.project_id))
                ).scalar_one_or_none()
                if task_project and task_project.department_id is not None:
                    ensure_department_access(user, task_project.department_id)
    else:
        ensure_manager_or_admin(user)

    deleted_checklist_id = item.checklist_id
    deleted_position = item.position
    deleted_title = item.title
    deleted_checklist = checklist if item.checklist_id is not None else None
    path_filter = (
        ChecklistItem.path.is_(None)
        if item.path is None
        else ChecklistItem.path == item.path
    )
    await sync_checklist_item_manual_question(
        db,
        deleted_checklist,
        title=deleted_title,
        action="delete",
    )
    await db.delete(item)
    # Keep numbering contiguous.
    # Use retry mechanism to handle deadlocks from concurrent deletions
    if deleted_checklist_id is not None:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Lock rows in consistent order (by position) to prevent deadlocks
                # First, select and lock the rows we need to update in order
                items_to_update = (
                    await db.execute(
                        select(ChecklistItem)
                        .where(
                            ChecklistItem.checklist_id == deleted_checklist_id,
                            path_filter,
                            ChecklistItem.position > deleted_position,
                        )
                        .order_by(ChecklistItem.position)
                        .with_for_update()
                    )
                ).scalars().all()
                
                # Update positions
                if items_to_update:
                    await db.execute(
                        update(ChecklistItem)
                        .where(
                            ChecklistItem.checklist_id == deleted_checklist_id,
                            path_filter,
                            ChecklistItem.position > deleted_position,
                        )
                        .values(position=ChecklistItem.position - 1)
                    )
                await db.commit()
                break
            except Exception as e:
                # Check if it's a deadlock error
                # SQLAlchemy wraps asyncpg exceptions, so we need to check both
                is_deadlock = False
                if hasattr(e, 'orig'):
                    # Check the underlying asyncpg exception
                    if isinstance(e.orig, asyncpg.exceptions.DeadlockDetectedError):
                        is_deadlock = True
                elif "deadlock" in str(e).lower():
                    # Fallback: check error message
                    is_deadlock = True
                
                if is_deadlock and attempt < max_retries - 1:
                    await db.rollback()
                    # Exponential backoff: wait longer on each retry
                    await asyncio.sleep(0.1 * (2 ** attempt))
                    continue
                else:
                    await db.rollback()
                    raise
    else:
        await db.commit()
    return {"ok": True}



