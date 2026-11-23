from __future__ import annotations

import enum


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    STAFF = "STAFF"


class SkillRating(str, enum.Enum):
    A_PLUS = "A_PLUS"
    A = "A"
    B = "B"
    C = "C"


class TaskSkillCategory(str, enum.Enum):
    analysis = "analysis"
    research = "research"
    problem_solving = "problem_solving"
    creativity = "creativity"
    standards = "standards"
    qa = "qa"
    management = "management"
    communication = "communication"
    fast_tasks = "fast_tasks"


class TaskPriority(str, enum.Enum):
    NORMAL = "NORMAL"
    HIGH = "HIGH"


class TaskFinishPeriod(str, enum.Enum):
    AM = "AM"
    PM = "PM"


class TaskStatus(str, enum.Enum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    PAUSED = "PAUSED"
    WAITING_CLIENT = "WAITING_CLIENT"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    DONE = "DONE"

    @classmethod
    def _missing_(cls, value: object) -> "TaskStatus | None":
        """Heal legacy/aliased task status values.

        The ``tasks.status`` column is a free-form string, so historical rows
        (or values borrowed from the realization reason codes such as
        ``WAITING_CLIENT``) can hold labels that are no longer part of this
        enum. Without this, a single stale row makes Pydantic raise and 500s
        every endpoint that serializes the task. Map the known aliases to a
        sensible member and fall back to a case-insensitive match; genuinely
        unknown values still raise so real typos are not silently accepted.
        """
        if value is None:
            return cls.TODO
        normalized = str(value).strip().upper()
        aliases = {
            "STOPPED": cls.PAUSED,
            "WFE": cls.WAITING_CLIENT,
            "WAITING_CLIENT": cls.IN_PROGRESS,
            "WAITING": cls.WAITING_CONFIRMATION,
            "PENDING_CONFIRMATION": cls.WAITING_CONFIRMATION,
            "NOT_DONE": cls.TODO,
            "COMPLETED": cls.DONE,
            "COMPLETED_LATE": cls.DONE,
        }
        if normalized in aliases:
            return aliases[normalized]
        for member in cls:
            if member.value == normalized:
                return member
        return None


class TaskType(str, enum.Enum):
    adhoc = "adhoc"
    system = "system"
    reminder = "reminder"


class FrequencyType(str, enum.Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"
    THREE_MONTHS = "3_MONTHS"
    SIX_MONTHS = "6_MONTHS"


class SystemTaskScope(str, enum.Enum):
    ALL = "ALL"
    DEPARTMENT = "DEPARTMENT"
    GA = "GA"


class TemplateRecurrence(str, enum.Enum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    yearly = "yearly"


class AttendanceType(str, enum.Enum):
    VONESE = "VONESE"
    MUNGESE = "MUNGESE"
    PUSHIM_VJETOR = "PUSHIM_VJETOR"


class FeedbackType(str, enum.Enum):
    ANKESA = "ANKESA"
    KERKESA = "KERKESA"
    PROPOZIM = "PROPOZIM"


class PromptType(str, enum.Enum):
    GA_PROMPT = "GA_PROMPT"
    ZHVILLIM_PROMPT = "ZHVILLIM_PROMPT"


class GaNoteType(str, enum.Enum):
    GA = "GA"
    KA = "KA"


class GaNoteStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class GaNotePriority(str, enum.Enum):
    NORMAL = "NORMAL"
    HIGH = "HIGH"


class HolidayType(str, enum.Enum):
    PX_INTERNAL = "PX_INTERNAL"
    CLIENT = "CLIENT"


class ProjectPhaseStatus(str, enum.Enum):
    MEETINGS = "MEETINGS"
    PLANNING = "PLANNING"
    DEVELOPMENT = "DEVELOPMENT"
    TESTING = "TESTING"
    DOCUMENTATION = "DOCUMENTATION"
    PRODUCT = "PRODUCT"
    CONTROL = "CONTROL"
    FINAL = "FINAL"
    AMAZON = "AMAZON"
    CHECK = "CHECK"
    DREAMROBOT = "DREAMROBOT"
    CLOSED = "CLOSED"


class ProjectType(str, enum.Enum):
    GENERAL = "GENERAL"
    MST = "MST"
    GD_DEVELOPMENT = "GD_DEVELOPMENT"


class CommonCategory(str, enum.Enum):
    delays = "Delays"
    absences = "Absences"
    annual_leave = "Annual Leave"
    blocks = "Blocks"
    external_tasks = "External Tasks"
    external_holiday = "External Holiday"
    problems = "Problems"
    complaints = "Complaints"
    requests = "Requests"
    proposals = "Proposals"


class CommonApprovalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class NotificationType(str, enum.Enum):
    assignment = "assignment"
    status_change = "status_change"
    overdue = "overdue"
    mention = "mention"
    reminder = "reminder"


class ChecklistItemType(str, enum.Enum):
    TITLE = "TITLE"
    COMMENT = "COMMENT"
    CHECKBOX = "CHECKBOX"


class RealizationPeriodType(str, enum.Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


class RealizationPeriodSlot(str, enum.Enum):
    AM = "AM"
    PM = "PM"
    ALL = "ALL"


class RealizationPeriodStatus(str, enum.Enum):
    OPEN = "OPEN"
    CALCULATED = "CALCULATED"
    REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"


class RealizationScopeType(str, enum.Enum):
    TASK = "TASK"
    PERSON = "PERSON"
    PROJECT = "PROJECT"
    DEPARTMENT = "DEPARTMENT"
    SYSTEM_TASK = "SYSTEM_TASK"


class RealizationMarker(str, enum.Enum):
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"
    DIAMOND = "DIAMOND"


class RealizationObservationCategory(str, enum.Enum):
    EXTRA_TASK = "EXTRA_TASK"
    HELPED_COLLEAGUE = "HELPED_COLLEAGUE"
    PROPOSAL = "PROPOSAL"
    TIME_SAVED = "TIME_SAVED"
    QUALITY = "QUALITY"
    DELAY = "DELAY"
    ABSENCE = "ABSENCE"
    MISSED_MEETING = "MISSED_MEETING"
    BLOCKER = "BLOCKER"
    REPEATED_PROBLEM = "REPEATED_PROBLEM"
    PRIORITY_CHANGE = "PRIORITY_CHANGE"
    OTHER = "OTHER"


class RealizationObservationVisibility(str, enum.Enum):
    PRIVATE_MANAGER = "PRIVATE_MANAGER"
    PERSON_AND_MANAGER = "PERSON_AND_MANAGER"
    TEAM_AGGREGATE = "TEAM_AGGREGATE"


class RealizationLevel(str, enum.Enum):
    A_PLUS = "A+"
    A = "A"
    B = "B"
    C = "C"
    M = "M"
    D = "D"
    E = "E"


class RealizationSymbol(str, enum.Enum):
    POSITIVE = "+"
    MIXED = "+/-"
    NEGATIVE = "-"


class RealizationPulse(str, enum.Enum):
    """Operational steering state; intentionally separate from final symbols."""

    ON_PLAN = "+"
    ABOVE_PLAN = "++"
    DIAMOND = "DIAMOND"
    ACTION_REQUIRED = "?"
    JUSTIFIED = "OK"


class RealizationOperatingMode(str, enum.Enum):
    AUTO = "AUTO"
    SEMI_MANUAL = "SEMI_MANUAL"
    MANUAL = "MANUAL"


class RealizationDailyCloseAction(str, enum.Enum):
    CLOSE = "CLOSE"
    REOPEN = "REOPEN"
    CORRECT = "CORRECT"
