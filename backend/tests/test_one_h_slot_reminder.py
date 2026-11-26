import asyncio
from contextlib import nullcontext
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text

import discord_m3_client
from app.api.routers import tasks
from app.services.one_h_slot_reminder import CODE, has_pm_block


def test_slot_reminder_only_for_same_day_open_pm_block_and_affected_owner():
    asyncio.run(check_slot_reminder())


async def check_slot_reminder():
    engine = create_engine("sqlite://")
    owner, other, block_id = (uuid4() for _ in range(3))
    day = date(2026, 11, 26)
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE tasks (id TEXT, assigned_to TEXT, start_date TEXT, due_date TEXT, created_at TEXT, "
            "phase TEXT, pause_periods TEXT, is_active BOOLEAN, is_bllok BOOLEAN, finish_period TEXT, "
            "status TEXT, completed_at TEXT)"
        ))
        connection.execute(text("CREATE TABLE task_assignees (task_id TEXT, user_id TEXT)"))
        connection.execute(text("CREATE TABLE users (id TEXT, department_id TEXT)"))
        connection.execute(text("CREATE TABLE departments (id TEXT, code TEXT, name TEXT)"))
        connection.execute(text(
            "INSERT INTO tasks VALUES (:id, NULL, '2026-11-25', '2026-11-26', '2026-11-25', "
            "'MEETINGS', NULL, 1, 1, 'PM', 'TODO', NULL)"
        ), {"id": block_id.hex})
        connection.execute(text("INSERT INTO task_assignees VALUES (:task, :owner)"),
                           {"task": block_id.hex, "owner": owner.hex})
        db = SimpleNamespace(execute=AsyncMock(side_effect=connection.execute), begin_nested=nullcontext)
        assert not await has_pm_block(db, date(2026, 11, 27), {owner})
        assert not await has_pm_block(db, day, {other})
        assert await has_pm_block(db, day, {owner})

        for changes in (
            {"finish_period": "AM"}, {"status": "DONE"}, {"is_active": 0},
            {"pause_periods": '[{"from":"2026-11-26","until":"2026-11-26"}]'},
        ):
            connection.execute(text(
                "UPDATE tasks SET finish_period = 'PM', status = 'TODO', is_active = 1, pause_periods = NULL"
            ))
            column, value = next(iter(changes.items()))
            connection.execute(text(f"UPDATE tasks SET {column} = :value"), {"value": value})
            assert not await has_pm_block(db, day, {owner})
    engine.dispose()


def test_slot_endpoint_waits_for_confirmation_then_saves(monkeypatch):
    owner, task_id = uuid4(), uuid4()
    day = date(2026, 11, 26)
    task = SimpleNamespace(
        id=task_id, assigned_to=owner, title="Detyra 1H", one_h_report_slot=None,
        system_template_origin_id=None, system_task_slot_id=None, is_r1=False, is_1h_report=True, is_bllok=False,
        finish_period="PM",
    )
    dto = SimpleNamespace(
        is_1h_report=True, is_r1=False, is_bllok=False, assigned_to=owner, assignees=[],
    )
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    store = AsyncMock()
    monkeypatch.setattr(tasks.reporting_choices, "lock_task_group", AsyncMock(return_value=(task, [task])))
    monkeypatch.setattr(tasks.reporting_choices, "record_choice", AsyncMock(return_value=False))
    monkeypatch.setattr(tasks, "effective_slot_date", lambda selected: selected)
    monkeypatch.setattr(tasks, "_store_task_slot", store)
    monkeypatch.setattr(tasks, "_assignees_for_tasks", AsyncMock(return_value={}))
    monkeypatch.setattr(tasks, "_user_comments_for_tasks", AsyncMock(return_value={}))
    monkeypatch.setattr(tasks, "_task_to_out", lambda *_: dto)

    async def check_block(db, day, owners):
        db.commit.assert_not_awaited()
        store.assert_not_awaited()
        assert owners == {owner}
        return owners

    monkeypatch.setattr("app.services.one_h_slot_reminder.pm_block_owners", check_block)
    payload = tasks.TaskOneHReportSlotUpdate(report_date=day, one_h_report_slot="16:00")
    with pytest.raises(HTTPException) as warning:
        asyncio.run(tasks.update_task_one_h_report_slot(task_id, payload, db, SimpleNamespace(id=owner), "ask"))
    assert warning.value.detail["code"] == CODE
    assert warning.value.detail["slots"] == ("14:20",)
    assert task.one_h_report_slot is None
    db.commit.assert_not_awaited()

    saved = asyncio.run(tasks.update_task_one_h_report_slot(
        task_id, payload, db, SimpleNamespace(id=owner), "continue",
    ))
    assert saved.one_h_report_slot == task.one_h_report_slot == "16:00"
    store.assert_awaited_once_with(db, task_id, day, "16:00")
    db.commit.assert_awaited_once()


@pytest.mark.parametrize("selected_slot", ["16:00", "14:20"])
def test_discord_slot_reminder_is_private_and_saves_the_choice(monkeypatch, selected_slot):
    reminder = "Ka detyrë Bllok PM për të njëjtën ditë."
    latest = {"id": "slot-question"}
    bot = SimpleNamespace(bridge=AsyncMock(side_effect=[{"slot_reminder": reminder}, {"ok": True}, latest]))
    user = SimpleNamespace(id=10)
    interaction = SimpleNamespace(
        id=1, user=user, message=SimpleNamespace(edit=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()),
    )
    monkeypatch.setattr(discord_m3_client, "actor", lambda _: {})
    monkeypatch.setattr(discord_m3_client, "prompt", lambda _: "Pyetja")
    monkeypatch.setattr(discord_m3_client, "controls", lambda _: None)
    async def run():
        await discord_m3_client.save(bot, interaction, latest, "slot", slot="16:00")
        notification = interaction.followup.send.await_args
        assert notification.args == (reminder,)
        assert notification.kwargs["ephemeral"] is True
        interaction.message.edit.assert_not_awaited()
        buttons = {button.label: button for button in notification.kwargs["view"].children}
        assert set(buttons) == {"Vazhdo me 16:00", "Ndërro slotin"}
        click = SimpleNamespace(
            id=2, user=user, response=SimpleNamespace(edit_message=AsyncMock()), edit_original_response=AsyncMock(),
        )
        if selected_slot == "16:00":
            await buttons["Vazhdo me 16:00"].callback(click)
        else:
            await buttons["Ndërro slotin"].callback(click)
            assert bot.bridge.await_count == 1
            choices = notification.kwargs["view"].children[-1]
            assert [option.value for option in choices.options] == ["10:00", "11:00", "11:50", "14:20"]
            choices._values = [selected_slot]
            await choices.callback(click)
        assert bot.bridge.await_args_list[1].args[1]["slot"] == selected_slot
        assert bot.bridge.await_args_list[1].args[1]["continue_with_16"] is (selected_slot == "16:00")
        interaction.message.edit.assert_awaited_once()
        click.edit_original_response.assert_awaited_once_with(content=f"Sloti {selected_slot} u ruajt.", view=None)

    asyncio.run(run())
