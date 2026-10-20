import * as React from "react"
import { Calendar } from "lucide-react"

import { cn } from "@/lib/utils"

type DateInputProps = Omit<React.ComponentProps<"input">, "type" | "value" | "onChange"> & {
  value?: React.ComponentProps<"input">["value"] | null
  onChange?: (event: React.ChangeEvent<HTMLInputElement>) => void
}

function isValidIsoDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const [year, month, day] = value.split("-").map(Number)
  const date = new Date(year, month - 1, day)
  return (
    date.getFullYear() === year &&
    date.getMonth() === month - 1 &&
    date.getDate() === day
  )
}

function formatDdMmFromIso(value?: string | null) {
  if (!value) return ""
  if (!isValidIsoDate(value)) return ""
  const [year, month, day] = value.split("-")
  return `${day}/${month}/${year}`
}

function parseDdMmToIso(value: string) {
  if (!/^\d{2}\/\d{2}\/\d{4}$/.test(value)) return null
  const [day, month, year] = value.split("/").map(Number)
  const iso = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`
  return isValidIsoDate(iso) ? iso : null
}

function isWithinBounds(value: string, min?: string | number, max?: string | number) {
  if (!isValidIsoDate(value)) return false
  if (typeof min === "string" && min && isValidIsoDate(min) && value < min) return false
  if (typeof max === "string" && max && isValidIsoDate(max) && value > max) return false
  return true
}

function DateInput({
  className,
  value,
  onChange,
  placeholder,
  disabled,
  readOnly,
  name,
  id,
  defaultValue,
  min,
  max,
  ...props
}: DateInputProps) {
  const inputRef = React.useRef<HTMLInputElement>(null)
  const hiddenRef = React.useRef<HTMLInputElement>(null)
  const rawValue = typeof value === "string" ? value : ""
  const rawDefault = typeof defaultValue === "string" ? defaultValue : ""
  const [displayValue, setDisplayValue] = React.useState(() =>
    formatDdMmFromIso(rawValue || rawDefault)
  )
  const isControlled = typeof value === "string"

  React.useEffect(() => {
    setDisplayValue(formatDdMmFromIso(rawValue))
  }, [rawValue])

  const emitChange = React.useCallback(
    (nextValue: string) => {
      if (!onChange) return
      const target = inputRef.current
      const event = {
        target: {
          ...(target ?? {}),
          value: nextValue,
          name,
          id,
        },
        currentTarget: {
          ...(target ?? {}),
          value: nextValue,
          name,
          id,
        },
      } as React.ChangeEvent<HTMLInputElement>
      onChange(event)
    },
    [id, name, onChange]
  )

  const handleInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const next = event.target.value
    setDisplayValue(next)

    if (!next) {
      emitChange("")
      if (hiddenRef.current) {
        hiddenRef.current.value = ""
      }
      return
    }

    if (next.length < 10) return
    const iso = parseDdMmToIso(next)
    if (!iso) return
    if (!isWithinBounds(iso, min, max)) return
    if (hiddenRef.current) {
      hiddenRef.current.value = iso
    }
    emitChange(iso)
  }

  const handleCalendarChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const iso = event.target.value
    if (!iso) {
      setDisplayValue("")
      emitChange("")
      return
    }
    if (!isValidIsoDate(iso)) return
    if (!isWithinBounds(iso, min, max)) return
    setDisplayValue(formatDdMmFromIso(iso))
    emitChange(iso)
  }

  return (
    <div className="relative w-full">
      <input
        {...props}
        ref={inputRef}
        type="text"
        data-slot="input"
        name={name}
        id={id}
        value={displayValue}
        onChange={handleInputChange}
        placeholder={placeholder ?? "dd/mm/yyyy"}
        inputMode="numeric"
        disabled={disabled}
        readOnly={readOnly}
        className={cn(
          "file:text-foreground placeholder:text-muted-foreground selection:bg-primary selection:text-primary-foreground dark:bg-input/30 border-input h-9 w-full min-w-0 rounded-md border bg-transparent px-3 py-1 pr-10 text-base shadow-xs transition-[color,box-shadow] outline-none file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
          "focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]",
          "aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive",
          className
        )}
      />
      <input
        ref={hiddenRef}
        type="date"
        {...(isControlled
          ? { value: rawValue }
          : { defaultValue: rawDefault ? rawDefault : undefined })}
        min={min}
        max={max}
        onChange={handleCalendarChange}
        disabled={disabled}
        readOnly={readOnly}
        tabIndex={-1}
        aria-hidden="true"
        className="pointer-events-none absolute right-10 top-0 h-0 w-0 opacity-0"
      />
      <button
        type="button"
        aria-label="Open calendar"
        className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-muted-foreground transition hover:text-foreground disabled:pointer-events-none"
        disabled={disabled || readOnly}
        onClick={() => {
          const target = hiddenRef.current
          if (!target) return
          if (typeof target.showPicker === "function") {
            target.showPicker()
            return
          }
          target.focus()
          target.click()
        }}
      >
        <Calendar className="h-4 w-4" />
      </button>
    </div>
  )
}

export { DateInput }
