"use client"

import * as React from "react"
import { toast } from "sonner"

import { useConfirm } from "@/components/providers/confirm-dialog-provider"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { CreateUserDialog } from "@/components/users/create-user-dialog"
import { EditUserDialog } from "@/components/users/edit-user-dialog"
import { useAuth } from "@/lib/auth"
import type { Department, User } from "@/lib/types"

export default function UsersPage() {
  const { user, apiFetch } = useAuth()
  const confirm = useConfirm()
  const [users, setUsers] = React.useState<User[]>([])
  const [departments, setDepartments] = React.useState<Department[]>([])
  const [showInactive, setShowInactive] = React.useState(false)
  const isAdmin = user?.role === "ADMIN"

  const load = React.useCallback(async () => {
    const params = new URLSearchParams()
    if (showInactive) params.set("include_inactive", "true")
    if (isAdmin) params.set("include_household", "true")
    const suffix = params.size ? `?${params}` : ""
    const res = await apiFetch(`/users${suffix}`)
    if (res.ok) setUsers((await res.json()) as User[])
  }, [apiFetch, showInactive, isAdmin])

  React.useEffect(() => {
    void load()
    const loadDepartments = async () => {
      const res = await apiFetch("/departments")
      if (res.ok) setDepartments((await res.json()) as Department[])
    }
    void loadDepartments()
  }, [load])

  if (!user || user.role === "STAFF") {
    return <div className="text-sm text-muted-foreground">Forbidden.</div>
  }

  const departmentById = new Map(departments.map((d) => [d.id, d.name]))

  const deactivate = async (target: User) => {
    const confirmed = await confirm({
      title: "Deactivate user",
      description: `Deactivate ${target.email}?`,
      confirmLabel: "Deactivate",
      variant: "destructive",
    })
    if (!confirmed) return
    const res = await apiFetch(`/users/${target.id}`, { method: "DELETE" })
    if (!res.ok) {
      let detail = "Failed to deactivate user"
      try {
        const data = (await res.json()) as { detail?: string }
        if (data?.detail) detail = data.detail
      } catch {
        // ignore response parse errors
      }
      toast.error(detail)
      return
    }
    await load()
  }

  const visibleUsers = React.useMemo(
    () => (showInactive ? users.filter((u) => !u.is_active) : users),
    [showInactive, users],
  )

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div className="text-lg font-semibold">Users</div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <Checkbox
              id="show-inactive-users"
              checked={showInactive}
              onCheckedChange={(value) => setShowInactive(Boolean(value))}
            />
            <Label htmlFor="show-inactive-users" className="text-sm">
              Show only deactivated
            </Label>
          </div>
          {isAdmin ? <CreateUserDialog departments={departments} onCreated={load} /> : null}
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Directory</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Email</TableHead>
                <TableHead>Username</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Department</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visibleUsers.map((u) => (
                <TableRow key={u.id}>
                  <TableCell>{u.email}</TableCell>
                  <TableCell>{u.username}</TableCell>
                  <TableCell>{u.full_name || "-"}</TableCell>
                  <TableCell>{(u.department_id && departmentById.get(u.department_id)) || "-"}</TableCell>
                <TableCell>
                  {u.is_active ? <Badge variant="secondary">Active</Badge> : <Badge variant="outline">Inactive</Badge>}
                </TableCell>
                <TableCell>{u.role}</TableCell>
                <TableCell className="space-x-2">
                    {isAdmin ? (
                      <>
                        <EditUserDialog userRecord={u} departments={departments} onUpdated={load} />
                        {u.is_active ? (
                          <button
                            className="text-sm text-destructive hover:underline"
                            onClick={() => void deactivate(u)}
                          >
                            Deactivate
                          </button>
                        ) : null}
                      </>
                    ) : (
                      <span className="text-xs text-muted-foreground">View only</span>
                    )}
                </TableCell>
              </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}


