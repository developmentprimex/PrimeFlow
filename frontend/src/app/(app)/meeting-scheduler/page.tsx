"use client";

import * as React from "react";
import { calendarMeetingTimeRange } from "@/lib/calendar-meeting-time";
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Users,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuth } from "@/lib/auth";
import { MeetingClientPicker, type MeetingClientSelection } from "@/components/meeting-notes/client-picker";

type Department = { id: string; name: string };
type UserLookup = {
  id: string;
  full_name?: string | null;
  username?: string | null;
  email: string;
  department_id?: string | null;
};
type Standard = {
  id: string;
  name: string;
  meeting_type: "internal" | "external";
  default_duration_minutes: number;
  buffer_minutes: number;
  workday_start: string;
  workday_end: string;
};
type Validation = {
  can_create: boolean;
  errors: string[];
  warnings: string[];
  conflicts: Array<{
    source: string;
    title: string;
    starts_at: string;
    ends_at: string;
    participant_ids?: string[];
  }>;
  suggested_slot?: { starts_at: string; ends_at: string } | null;
};
type CalendarItem = {
  id: string;
  source: string;
  title: string;
  meeting_type: string;
  starts_at: string;
  ends_at: string;
  status: string;
  teams_url?: string | null;
  microsoft_event_id?: string | null;
  calendar_categories?: string[];
};
type MicrosoftEvent = {
  id: string;
  subject?: string | null;
  starts_at?: string | null;
  ends_at?: string | null;
  location?: string | null;
  categories?: string[];
};

const HOURS = Array.from({ length: 19 }, (_, index) => {
  const minutes = 8 * 60 + index * 30;
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
});

const isoDate = (date: Date) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
};
const mondayFor = (value: Date) => {
  const result = new Date(value);
  const day = (result.getDay() + 6) % 7;
  result.setDate(result.getDate() - day);
  result.setHours(0, 0, 0, 0);
  return result;
};
const addDays = (value: Date, days: number) => {
  const result = new Date(value);
  result.setDate(result.getDate() + days);
  return result;
};
const localDateTime = (date: string, time: string) =>
  new Date(`${date}T${time}:00`);
const localDateTimeParts = (value: string) => {
  const date = new Date(value);
  return {
    date: isoDate(date),
    time: `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`,
  };
};
const calendarWindow = (item: CalendarItem) => calendarMeetingTimeRange({
  ...item,
  meeting_type: item.meeting_type === "microsoft" ? "external" : item.meeting_type,
  calendar_imported: item.source === "microsoft",
});
const userLabel = (user: UserLookup) =>
  user.full_name || user.username || user.email;
const validationFailure = (message: string): Validation => ({
  can_create: false,
  errors: [message],
  warnings: [],
  conflicts: [],
});

const uniqueConflicts = (conflicts: Validation["conflicts"]) =>
  Array.from(
    new Map(
      conflicts.map((conflict) => [
        `${conflict.source}|${conflict.title}|${conflict.starts_at}|${conflict.ends_at}`,
        conflict,
      ]),
    ).values(),
  );

const warningSignature = (result: Validation | null) => result
  ? JSON.stringify([
      [...result.warnings].sort(),
      uniqueConflicts(result.conflicts).map((conflict) =>
        `${conflict.source}|${conflict.title}|${conflict.starts_at}|${conflict.ends_at}`,
      ).sort(),
    ])
  : "";

const meetingSchedulerError = async (
  response: Response,
  fallback: string,
) => {
  const raw = await response.text();
  if (!raw) return fallback;
  try {
    const body = JSON.parse(raw) as {
      detail?:
        | string
        | Array<{ msg?: string; loc?: Array<string | number> }>
        | { errors?: string[]; warnings?: string[] };
    };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      const messages = body.detail
        .map((item) => {
          const message = String(item.msg || "").replace(/^Value error,\s*/i, "");
          return message;
        })
        .filter(Boolean);
      if (messages.length) return messages.join(" ");
    }
    if (body.detail && !Array.isArray(body.detail) && body.detail.errors?.length) {
      return body.detail.errors.join(" ");
    }
  } catch {
    // Non-JSON errors are returned below without hiding the server response.
  }
  return raw || fallback;
};

const calendarMeetingTone = (item: CalendarItem) => {
  const categories = (item.calendar_categories || []).map((category) =>
    category.trim().toLowerCase(),
  );
  if (
    categories.some(
      (category) =>
        category.includes("daily") ||
        category.includes("weekly") ||
        category.includes("standup") ||
        category.includes("brown"),
    )
  )
    return "border-[#8B623D] bg-[#C9A98A] text-slate-950";
  if (
    categories.some(
      (category) => category.includes("red") || category.includes("online"),
    )
  )
    return "border-[#E55361] bg-[#FFD5DC] text-slate-950";
  if (
    categories.some(
      (category) => category === "tak int" || category.includes("yellow"),
    )
  )
    return "border-[#E6AD00] bg-[#FFE38F] text-slate-950";
  if (categories.some((category) => category.includes("orange")))
    return "border-[#E87922] bg-[#FFD7AD] text-slate-950";
  if (
    categories.some(
      (category) =>
        category.includes("event") ||
        category.includes("evvent") ||
        category.includes("fizik"),
    )
  )
    return "border-[#35ABB4] bg-[#CCEFF1] text-slate-950";
  if (
    categories.some(
      (category) => category.includes("purple") || category.includes("violet"),
    )
  )
    return "border-[#7167D9] bg-[#E5E7FB] text-slate-950";
  if (categories.some((category) => category.includes("blue")))
    return "border-[#5B9FE8] bg-[#DCECFF] text-slate-950";

  if (item.source === "microsoft" || item.microsoft_event_id)
    return "border-[#E55361] bg-[#FFD5DC] text-slate-950";
  if (item.meeting_type === "internal")
    return "border-[#E6AD00] bg-[#FFE38F] text-slate-950";
  return "border-[#5B9FE8] bg-[#DCECFF] text-slate-950";
};

export default function MeetingSchedulerPage() {
  const { apiFetch, user } = useAuth();
  const [weekStart, setWeekStart] = React.useState(() => mondayFor(new Date()));
  const [departments, setDepartments] = React.useState<Department[]>([]);
  const [users, setUsers] = React.useState<UserLookup[]>([]);
  const [standards, setStandards] = React.useState<Standard[]>([]);
  const [calendarItems, setCalendarItems] = React.useState<CalendarItem[]>([]);
  const [microsoftEvents, setMicrosoftEvents] = React.useState<
    MicrosoftEvent[]
  >([]);
  const [msConnected, setMsConnected] = React.useState(false);
  const [msCanWrite, setMsCanWrite] = React.useState(false);
  const [msCanManage, setMsCanManage] = React.useState(false);
  const [msAccountEmail, setMsAccountEmail] =
    React.useState("info@primexeu.com");
  const [loading, setLoading] = React.useState(true);
  const [validating, setValidating] = React.useState(false);
  const [creating, setCreating] = React.useState(false);
  const [meetingTitle, setMeetingTitle] = React.useState("");
  const [clientSelection, setClientSelection] = React.useState<MeetingClientSelection | null>(null);
  const [meetingUrl, setMeetingUrl] = React.useState("");
  const [validation, setValidation] = React.useState<Validation | null>(null);
  const validationRequestRef = React.useRef(0);

  const [departmentId, setDepartmentId] = React.useState(
    user?.department_id || "",
  );
  const [meetingType, setMeetingType] = React.useState<"internal" | "external">(
    "external",
  );
  // Takimet: a training is scheduled as TAK INT and grouped under "Trajnime".
  const [isTraining, setIsTraining] = React.useState(false);
  const [standardId, setStandardId] = React.useState("");
  const [initialSlot] = React.useState(() => {
    const next = new Date(Math.ceil((Date.now() + 60_000) / 900_000) * 900_000);
    return localDateTimeParts(next.toISOString());
  });
  const [selectedDate, setSelectedDate] = React.useState(initialSlot.date);
  const [selectedTime, setSelectedTime] = React.useState(initialSlot.time);
  const [duration, setDuration] = React.useState(60);
  const [participantIds, setParticipantIds] = React.useState<string[]>(
    user?.id ? [user.id] : [],
  );
  const [standardName, setStandardName] = React.useState("");
  const [standardType, setStandardType] = React.useState<
    "internal" | "external"
  >("external");
  const [standardDuration, setStandardDuration] = React.useState(60);
  const [standardBuffer, setStandardBuffer] = React.useState(15);

  const days = React.useMemo(
    () => Array.from({ length: 5 }, (_, index) => addDays(weekStart, index)),
    [weekStart],
  );
  const rangeStart = days[0].toISOString();
  const rangeEnd = addDays(days[4], 1).toISOString();
  const departmentNames = React.useMemo(
    () => new Map(departments.map((department) => [department.id, department.name])),
    [departments],
  );

  React.useEffect(() => {
    if (!departmentId && user?.department_id)
      setDepartmentId(user.department_id);
    if (user?.id)
      setParticipantIds((current) => (current.length ? current : [user.id]));
  }, [departmentId, user]);

  const loadReferenceData = React.useCallback(async () => {
    const [departmentsRes, usersRes, standardsRes, msStatusRes] =
      await Promise.all([
        apiFetch("/departments"),
        apiFetch("/users/lookup"),
        apiFetch("/meeting-scheduler/standards"),
        apiFetch("/microsoft/status"),
      ]);
    if (departmentsRes.ok) setDepartments(await departmentsRes.json());
    if (usersRes.ok) setUsers(await usersRes.json());
    if (standardsRes.ok) setStandards(await standardsRes.json());
    if (msStatusRes.ok) {
      const status = (await msStatusRes.json()) as {
        connected?: boolean;
        can_write_calendar?: boolean;
        can_manage?: boolean;
        account_email?: string;
      };
      setMsConnected(Boolean(status.connected));
      setMsCanWrite(Boolean(status.can_write_calendar));
      setMsCanManage(Boolean(status.can_manage));
      if (status.account_email) setMsAccountEmail(status.account_email);
    }
  }, [apiFetch]);

  const loadSchedule = React.useCallback(async () => {
    const query = new URLSearchParams({ start: rangeStart, end: rangeEnd });
    if (departmentId) query.set("department_id", departmentId);
    const calendarRes = await apiFetch(`/meeting-scheduler/calendar?${query}`);
    if (calendarRes.ok) setCalendarItems(await calendarRes.json());
    if (msConnected) {
      const eventsRes = await apiFetch(
        `/microsoft/events?start=${encodeURIComponent(rangeStart)}&end=${encodeURIComponent(rangeEnd)}`,
      );
      if (eventsRes.ok) setMicrosoftEvents(await eventsRes.json());
    } else {
      setMicrosoftEvents([]);
    }
  }, [apiFetch, departmentId, msConnected, rangeEnd, rangeStart]);

  React.useEffect(() => {
    let active = true;
    setLoading(true);
    void loadReferenceData().finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [loadReferenceData]);
  React.useEffect(() => {
    void loadSchedule();
  }, [loadSchedule]);

  const payload = React.useMemo(() => {
    const start = localDateTime(selectedDate, selectedTime);
    const end = new Date(start.getTime() + duration * 60_000);
    return {
      title: meetingType === "external" ? "Kontroll TAK EXT" : isTraining ? "Trajnim" : "Kontroll TAK INT",
      meeting_type: meetingType,
      is_training: meetingType === "internal" && isTraining,
      starts_at: Number.isNaN(start.getTime()) ? "" : start.toISOString(),
      ends_at: Number.isNaN(end.getTime()) ? "" : end.toISOString(),
      platform: meetingType === "external" ? "Teams" : null,
      notes: null,
      department_id: departmentId,
      project_id: null,
      standard_id: standardId || null,
      participant_ids: participantIds,
      conflicts_as_warnings: meetingType === "external",
    };
  }, [
    departmentId,
    duration,
    isTraining,
    meetingType,
    participantIds,
    selectedDate,
    selectedTime,
    standardId,
  ]);

  const validate = React.useCallback(async (notify = true) => {
    const missingFields = [
      !payload.department_id ? "departamentin" : "",
      !payload.participant_ids.length ? "të paktën një pjesëmarrës" : "",
      !payload.starts_at || !payload.ends_at ? "datën dhe orën" : "",
      duration < 5 || duration > 480 ? "kohëzgjatjen nga 5 deri në 480 minuta" : "",
    ].filter(Boolean);
    if (missingFields.length) {
      const message = `Plotëso ${missingFields.join(", ")} para validimit.`;
      setValidation(validationFailure(message));
      if (notify) toast.error("Takimi nuk mund të validohet.", { description: message });
      return null;
    }
    const requestId = ++validationRequestRef.current;
    setValidating(true);
    try {
      const response = await apiFetch("/meeting-scheduler/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const message = await meetingSchedulerError(
          response,
          "Validimi dështoi për shkak të një gabimi të panjohur.",
        );
        if (requestId === validationRequestRef.current) setValidation(validationFailure(message));
        if (notify) toast.error("Takimi nuk mund të validohet.", { description: message });
        return null;
      }
      const result = (await response.json()) as Validation;
      if (requestId !== validationRequestRef.current) return null;
      setValidation(result);
      if (notify && !result.can_create) {
        toast.error("Ka konflikt në këtë orar.", {
          description:
            result.errors.join(" ") ||
            "Kontrollo konfliktet e shfaqura te rezultati i validimit.",
        });
      } else if (notify && (result.warnings.length || result.conflicts.length)) {
        toast.warning("Ka paralajmërime për këtë orar.", {
          description: "Mund ta shtosh takimin gjithsesi.",
        });
      } else if (notify) {
        toast.success("Orari është i lirë për këtë takim.");
      }
      return result;
    } catch {
      const message = "Kontrolli i orarit dështoi. Kontrollo lidhjen dhe provo përsëri.";
      if (requestId === validationRequestRef.current) setValidation(validationFailure(message));
      if (notify) toast.error(message);
      return null;
    } finally {
      if (requestId === validationRequestRef.current) setValidating(false);
    }
  }, [apiFetch, duration, payload]);

  React.useEffect(() => {
    // Invalidate both the visible result and any in-flight response for old inputs.
    validationRequestRef.current += 1;
    const timeout = window.setTimeout(() => {
      setValidation(null);
      void validate(false);
    }, 450);
    return () => {
      window.clearTimeout(timeout);
      validationRequestRef.current += 1;
    };
  }, [payload, validate]);

  const oneHConflicts = validation?.conflicts.filter((conflict) => conflict.source === "one_h") || [];
  const hasWarnings = Boolean(validation && (validation.warnings.length || validation.conflicts.length));
  const createExternalMeeting = async () => {
    if (creating) return;
    if (meetingTitle.trim().length < 2) {
      toast.error("Shkruaj emrin e takimit.");
      return;
    }
    if (clientSelection && !clientSelection.name.trim()) {
      toast.error("Shkruaj emrin e klientit të ri.");
      return;
    }
    setCreating(true);
    try {
      const result = await validate(false);
      if (!result) return;
      if (!result.can_create) {
        toast.error("Takimi nuk mund të shtohet.", { description: result.errors.join(" ") });
        return;
      }
      if ((result.warnings.length || result.conflicts.length) && warningSignature(result) !== warningSignature(validation)) {
        toast.warning("Kontrollo paralajmërimet dhe shtyp Shto gjithsesi për të vazhduar.");
        return;
      }
      const response = await apiFetch("/meetings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: meetingTitle.trim(),
          client_id: clientSelection?.id || null,
          client_name: clientSelection?.name.trim() || null,
          meeting_type: "external",
          starts_at: payload.starts_at,
          ends_at: payload.ends_at,
          department_id: departmentId,
          participant_ids: participantIds,
          platform: "Teams",
          meeting_url: meetingUrl.trim() || null,
          create_internal_meeting: false,
          allow_one_h_conflict: result.conflicts.some((conflict) => conflict.source === "one_h"),
        }),
      });
      if (!response.ok) {
        toast.error("Takimi nuk u shtua.", { description: await meetingSchedulerError(response, "Provo përsëri.") });
        return;
      }
      setMeetingTitle("");
      setClientSelection(null);
      setMeetingUrl("");
      setValidation(null);
      setWeekStart(mondayFor(new Date(payload.starts_at)));
      toast.success("Takimi extern u shtua.");
      await loadSchedule().catch(() => toast.warning("Takimi u shtua, por kalendari nuk u rifreskua. Rifresko faqen."));
    } catch {
      toast.error("Takimi nuk u shtua. Kontrollo lidhjen dhe provo përsëri.");
    } finally {
      setCreating(false);
    }
  };
  const applySuggestedSlot = () => {
    if (!validation?.suggested_slot) return;
    const next = localDateTimeParts(validation.suggested_slot.starts_at);
    setSelectedDate(next.date);
    setSelectedTime(next.time);
    setValidation(null);
  };

  const createStandard = async () => {
    if (!standardName.trim()) {
      toast.error("Shkruaj emrin e standardit.");
      return;
    }
    const response = await apiFetch("/meeting-scheduler/standards", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: standardName.trim(),
        meeting_type: standardType,
        default_duration_minutes: standardDuration,
        buffer_minutes: standardBuffer,
        workday_start: "08:00",
        workday_end: "17:00",
        is_active: true,
      }),
    });
    if (!response.ok) {
      toast.error("Standardi nuk u krijua.", {
        description: await response.text(),
      });
      return;
    }
    toast.success("Standardi u krijua.");
    setStandardName("");
    const standardsRes = await apiFetch("/meeting-scheduler/standards");
    if (standardsRes.ok) setStandards(await standardsRes.json());
  };

  const chooseSlot = (day: Date, time: string) => {
    setSelectedDate(isoDate(day));
    setSelectedTime(time);
    setValidation(null);
    document
      .getElementById("meeting-request-form")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const slotItems = (day: Date, time: string) => {
    const key = `${isoDate(day)}T${time}`;
    const primeflow = calendarItems.filter((item) => {
      const local = new Date(item.starts_at);
      return (
        `${isoDate(local)}T${String(local.getHours()).padStart(2, "0")}:${String(Math.floor(local.getMinutes() / 30) * 30).padStart(2, "0")}` ===
        key
      );
    });
    const microsoft = microsoftEvents
      .filter((item) => {
        if (
          calendarItems.some(
            (existing) =>
              existing.microsoft_event_id &&
              existing.microsoft_event_id === item.id,
          )
        )
          return false;
        if (!item.starts_at) return false;
        const local = new Date(item.starts_at);
        return (
          `${isoDate(local)}T${String(local.getHours()).padStart(2, "0")}:${String(Math.floor(local.getMinutes() / 30) * 30).padStart(2, "0")}` ===
          key
        );
      })
      .map((item) => ({
        id: `ms:${item.id}`,
        source: "microsoft",
        title: item.subject || "Microsoft event",
        meeting_type: "microsoft",
        starts_at: item.starts_at!,
        ends_at: item.ends_at || item.starts_at!,
        status: "BUSY",
        calendar_categories: item.categories || [],
      }));
    return [...primeflow, ...microsoft];
  };

  const canManageStandards =
    user?.role === "ADMIN" || user?.role === "MANAGER";

  return (
    <div className="space-y-6 p-4 md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">
            Meeting Scheduler
          </h1>
          <p className="text-sm text-slate-500">
            Shto një takim extern ose kontrollo orarin e takimeve.
            Kur ka mbivendosje, mund të vazhdosh pas paralajmërimit.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {msCanManage ? (
            <Button
              variant="outline"
              onClick={async () => {
                const res = await apiFetch(
                  `/microsoft/authorize-url?redirect_to=${encodeURIComponent(window.location.href)}`,
                );
                if (res.ok) window.location.href = (await res.json()).url;
              }}
            >
              {msConnected && msCanWrite
                ? "Reconnect info@primexeu.com"
                : msConnected
                  ? "Upgrade Microsoft access"
                  : "Connect info@primexeu.com"}
            </Button>
          ) : (
            <span
              className={`rounded-full border px-3 py-2 text-xs font-medium ${msConnected ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-800"}`}
            >
              {msConnected
                ? `${msAccountEmail} connected`
                : `${msAccountEmail} not connected`}
            </span>
          )}
        </div>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <CalendarDays className="h-5 w-5" />
                Orari javor
              </CardTitle>
              <CardDescription>
                Kliko një slot për ta kontrolluar.
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <Button
                size="icon"
                variant="outline"
                onClick={() => setWeekStart(addDays(weekStart, -7))}
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <span className="min-w-40 text-center text-sm font-medium">
                {isoDate(days[0])} – {isoDate(days[4])}
              </span>
              <Button
                size="icon"
                variant="outline"
                onClick={() => setWeekStart(addDays(weekStart, 7))}
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          {loading ? (
            <div className="py-10 text-center text-sm text-slate-500">
              Duke ngarkuar…
            </div>
          ) : (
            <div className="min-w-[900px] overflow-hidden rounded-lg border">
              <div className="grid grid-cols-[72px_repeat(5,minmax(150px,1fr))] bg-slate-50">
                <div className="border-r p-2" />
                {days.map((day) => (
                  <div
                    key={isoDate(day)}
                    className="border-r p-2 text-center text-sm font-semibold last:border-r-0"
                  >
                    {day.toLocaleDateString("sq-AL", {
                      weekday: "short",
                      day: "2-digit",
                      month: "2-digit",
                    })}
                  </div>
                ))}
              </div>
              {HOURS.map((time) => (
                <div
                  key={time}
                  className="grid grid-cols-[72px_repeat(5,minmax(150px,1fr))] border-t"
                >
                  <div className="border-r px-2 py-2 text-xs font-medium text-slate-500">
                    {time}
                  </div>
                  {days.map((day) => {
                    const items = slotItems(day, time);
                    return (
                      <button
                        key={`${isoDate(day)}-${time}`}
                        type="button"
                        onClick={() => chooseSlot(day, time)}
                        className="min-h-14 border-r p-1 text-left transition hover:bg-blue-50 last:border-r-0"
                      >
                        {items.map((item) => (
                          <div
                            key={item.id}
                            className={`mb-1 truncate rounded border px-1.5 py-1 text-[10px] font-medium ${calendarMeetingTone(item)}`}
                            title={[item.title, calendarWindow(item)].filter(Boolean).join(" · ")}
                          >
                            {calendarWindow(item) ? <span className="block font-semibold">{calendarWindow(item)}</span> : null}
                            {item.title}
                          </div>
                        ))}
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card id="meeting-request-form">
          <CardHeader>
            <CardTitle>{meetingType === "external" ? "Shto takim extern" : "Kontrollo orarin e takimit"}</CardTitle>
            <CardDescription>
              {selectedDate} në {selectedTime}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {meetingType === "external" && <div className="grid gap-4 md:grid-cols-3">
              <div>
                <Label htmlFor="scheduler-meeting-title">Emri i takimit</Label>
                <Input id="scheduler-meeting-title" value={meetingTitle} onChange={(event) => setMeetingTitle(event.target.value)} placeholder="Shkruaj emrin e takimit" disabled={creating} />
              </div>
              <div>
                <Label htmlFor="scheduler-client-name">Klienti (opsional)</Label>
                <MeetingClientPicker id="scheduler-client-name" value={clientSelection} onChange={setClientSelection} disabled={creating} />
                <p className="mt-1 text-xs text-muted-foreground">Zgjidh klientin ekzistues ose shto një të ri.</p>
              </div>
              <div>
                <Label htmlFor="scheduler-meeting-url">Linku i takimit (opsional)</Label>
                <Input id="scheduler-meeting-url" type="url" value={meetingUrl} onChange={(event) => setMeetingUrl(event.target.value)} placeholder="https://…" disabled={creating} />
              </div>
            </div>}
            <fieldset disabled={creating} className="space-y-4">
            <div className="grid gap-4 md:grid-cols-3">
              <div>
                <Label>Lloji</Label>
                <Select
                  value={meetingType}
                  onValueChange={(value) => {
                    const nextType = value as "internal" | "external";
                    setMeetingType(nextType);
                    setStandardId("");
                    setDuration(nextType === "external" ? 60 : 30);
                    if (nextType === "external") setIsTraining(false);
                    setValidation(null);
                  }}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="external">TAK EXT</SelectItem>
                    <SelectItem value="internal">TAK INT</SelectItem>
                  </SelectContent>
                </Select>
                {meetingType === "internal" && (
                  <label className="mt-2 flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={isTraining}
                      onChange={(event) => {
                        setIsTraining(event.target.checked);
                        setValidation(null);
                      }}
                    />
                    Trajnim
                  </label>
                )}
              </div>
              <div>
                <Label>Departamenti</Label>
                <Select
                  value={departmentId}
                  onValueChange={(value) => {
                    setDepartmentId(value);
                    setValidation(null);
                  }}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Zgjidh departamentin" />
                  </SelectTrigger>
                  <SelectContent>
                    {departments.map((department) => (
                      <SelectItem key={department.id} value={department.id}>
                        {department.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>Rregullat e orarit (opsionale)</Label>
                <Select
                  value={standardId || "none"}
                  onValueChange={(value) => {
                    setStandardId(value === "none" ? "" : value);
                    setValidation(null);
                    const selected = standards.find(
                      (item) => item.id === value,
                    );
                    if (selected)
                      setDuration(selected.default_duration_minutes);
                  }}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Pa standard" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">Pa rregulla shtesë</SelectItem>
                    {standards
                      .filter((item) => item.meeting_type === meetingType)
                      .map((standard) => (
                        <SelectItem key={standard.id} value={standard.id}>
                          {standard.name}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
                <p className="mt-1 text-xs text-muted-foreground">Profili cakton kohëzgjatjen, orarin e punës dhe pauzën mes takimeve.</p>
              </div>
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <div>
                <Label>Data</Label>
                <Input
                  type="date"
                  value={selectedDate}
                  onChange={(event) => {
                    setSelectedDate(event.target.value);
                    setValidation(null);
                  }}
                />
              </div>
              <div>
                <Label>Ora</Label>
                <Input
                  type="time"
                  step={900}
                  value={selectedTime}
                  className={oneHConflicts.length ? meetingType === "external" ? "border-amber-500 bg-amber-50 text-amber-800" : "border-red-500 bg-red-50 text-red-800 focus-visible:ring-red-500" : undefined}
                  onChange={(event) => {
                    setSelectedTime(event.target.value);
                    setValidation(null);
                  }}
                />
              </div>
              <div>
                <Label>Minuta</Label>
                <Input
                  type="number"
                  min={5}
                  max={480}
                  step={5}
                  value={duration}
                  onChange={(event) => {
                    setDuration(Number(event.target.value) || 60);
                    setValidation(null);
                  }}
                />
              </div>
            </div>
            <div>
              <Label className="flex items-center gap-2">
                <Users className="h-4 w-4" />
                Pjesëmarrësit
              </Label>
              <div className="mt-2 grid max-h-44 gap-2 overflow-y-auto rounded-md border p-3 sm:grid-cols-2">
                {users.map((candidate) => (
                  <label
                    key={candidate.id}
                    className="flex items-center gap-2 text-sm"
                  >
                    <input
                      type="checkbox"
                      checked={participantIds.includes(candidate.id)}
                      onChange={(event) => {
                        setValidation(null);
                        setParticipantIds((current) =>
                          event.target.checked
                            ? [...new Set([...current, candidate.id])]
                            : current.filter((id) => id !== candidate.id),
                        );
                      }}
                    />
                    <span>
                      {userLabel(candidate)}
                      {candidate.department_id && departmentNames.get(candidate.department_id) ? (
                        <span className="ml-1 text-xs text-slate-500">
                          ({departmentNames.get(candidate.department_id)})
                        </span>
                      ) : null}
                    </span>
                  </label>
                ))}
              </div>
            </div>
            </fieldset>
            {validation && (
              <div
                role={validation.can_create ? "status" : "alert"}
                className={`rounded-lg border p-3 text-sm ${!validation.can_create ? "border-red-200 bg-red-50" : hasWarnings ? "border-amber-200 bg-amber-50" : "border-emerald-200 bg-emerald-50"}`}
              >
                <div className="mb-1 font-semibold">
                  {validation.can_create
                    ? hasWarnings ? "Paralajmërim — mund ta shtosh takimin gjithsesi" : "Orari është i lirë"
                    : "Kontrollo të dhënat e takimit"}
                </div>
                {validation.errors.map((message) => (
                  <div key={message} className="text-red-700">
                    • {message}
                  </div>
                ))}
                {validation.warnings.map((message) => (
                  <div key={message} className="text-amber-700">
                    • {message}
                  </div>
                ))}
                {uniqueConflicts(validation.conflicts).map((conflict, index) => (
                  <div
                    key={`${conflict.source}-${conflict.starts_at}-${conflict.ends_at}-${index}`}
                    className="mt-1 text-xs"
                  >
                    {conflict.source === "one_h" ? "1H" : conflict.source}: {conflict.title}
                    {` (${new Date(conflict.starts_at).toLocaleString("sq-AL")} – ${new Date(conflict.ends_at).toLocaleTimeString("sq-AL", { hour: "2-digit", minute: "2-digit" })})`}
                    {conflict.participant_ids?.length
                      ? ` — ${conflict.participant_ids.map((id) => {
                          const participant = users.find((candidate) => candidate.id === id);
                          return participant ? userLabel(participant) : id;
                        }).join(", ")}`
                      : ""}
                  </div>
                ))}
                {validation.suggested_slot ? (
                  <Button className="mt-3" size="sm" variant="outline" onClick={applySuggestedSlot} disabled={creating}>
                    Përdor orarin e lirë {localDateTimeParts(validation.suggested_slot.starts_at).time}
                  </Button>
                ) : null}
              </div>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => void validate(true)}
                disabled={validating || creating}
              >
                {validating ? "Duke kontrolluar…" : "Kontrollo orarin"}
              </Button>
              {meetingType === "external" && <Button onClick={() => void createExternalMeeting()} disabled={creating || validating || Boolean(validation && !validation.can_create)}>
                {creating ? "Duke shtuar…" : hasWarnings ? "Shto gjithsesi" : "Shto takim extern"}
              </Button>}
            </div>
          </CardContent>
        </Card>

      {canManageStandards && (
        <Card>
          <CardHeader>
            <CardTitle>Standardet e takimeve</CardTitle>
            <CardDescription>
              Shto kohëzgjatjen dhe buffer-in. Orari standard është 08:00–17:00.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 md:grid-cols-5">
              <div className="md:col-span-2">
                <Label>Emri</Label>
                <Input
                  value={standardName}
                  onChange={(event) => setStandardName(event.target.value)}
                  placeholder="Takim klienti"
                />
              </div>
              <div>
                <Label>Lloji</Label>
                <Select
                  value={standardType}
                  onValueChange={(value) =>
                    setStandardType(value as "internal" | "external")
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="external">TAK EXT</SelectItem>
                    <SelectItem value="internal">TAK INT</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>Minuta</Label>
                <Input
                  type="number"
                  min={5}
                  step={5}
                  value={standardDuration}
                  onChange={(event) =>
                    setStandardDuration(Number(event.target.value) || 60)
                  }
                />
              </div>
              <div>
                <Label>Buffer</Label>
                <Input
                  type="number"
                  min={0}
                  step={5}
                  value={standardBuffer}
                  onChange={(event) =>
                    setStandardBuffer(Number(event.target.value) || 0)
                  }
                />
              </div>
            </div>
            <div className="mt-3 flex items-center justify-between">
              <div className="text-xs text-slate-500">
                {standards
                  .map(
                    (item) =>
                      `${item.name}: ${item.default_duration_minutes} min, buffer ${item.buffer_minutes} min`,
                  )
                  .join(" · ")}
              </div>
              <Button variant="outline" onClick={() => void createStandard()}>
                Shto standard
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
