"""Publish just the requested PX Notes source marker/transcript support."""
import hashlib
import json
from pathlib import Path
import stage_server


def main():
    names=['app/models/mira_desktop.py','app/services/mira_desktop.py',
        'app/api/routers/ga_notes.py','app/api/routers/mira.py']
    # This list is deliberately fixed; no Discord transport/host change.
    staged={name:(stage_server.LOCAL/'backend'/name).read_bytes() for name in names}
    # A parallel main-branch deployment retained the applied migration but not
    # desktop registration. Restore only these lines on top of its new sources.
    name='app/api/routers/__init__.py'
    source=(stage_server.REMOTE/name).read_text(encoding='utf-8-sig')
    if 'from app.api.routers.mira_desktop import router as mira_desktop_router' not in source:
        if source.count('api_router = APIRouter()')!=1:raise RuntimeError('Unexpected router state')
        source=source.replace('api_router = APIRouter()',
            'api_router = APIRouter()\nfrom app.api.routers.mira_desktop import router as mira_desktop_router\n'
            'api_router.include_router(mira_desktop_router, prefix="/mira-desktop", tags=["mira-desktop"])')
    staged[name]=source.encode()
    name='app/models/__init__.py'
    source=(stage_server.REMOTE/name).read_text(encoding='utf-8-sig')
    if 'from app.models.mira_desktop import MiraDesktopSession, MiraDesktopSegment' not in source:
        source=source.rstrip()+'\nfrom app.models.mira_desktop import MiraDesktopSession, MiraDesktopSegment\n'
    staged[name]=source.encode()
    stage_server.publish_staged(staged)


if __name__=='__main__':main()
