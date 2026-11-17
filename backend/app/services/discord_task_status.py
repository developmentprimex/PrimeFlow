"""Question eligibility only; never changes a task's stored status."""


def is_wfe(status) -> bool:
    return str(getattr(status, 'value', status) or '').upper() in {
        'WAITING_CLIENT', 'WAITINGCLIENT', 'WAITING_FOR_CLIENT', 'WFE',
    }


def settled_for_questions(status) -> bool:
    return str(getattr(status, 'value', status) or '').upper() in {'DONE', 'COMPLETED'} or is_wfe(status)
