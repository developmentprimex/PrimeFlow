"""Public synthetic fixtures; private household instructions stay outside Git."""
import copy
import os
import unittest
import uuid
from datetime import date
from types import SimpleNamespace

from sqlalchemy import select, func

from app.schemas.ga_personal import GenerateRequest
from app.services import ga_personal as service
from app.services.ga_personal_device_sync import exported_cards
from tests import test_ga_personal as fixtures
from tests.test_ga_personal import dataset, Space, Template, Occurrence, Member, Event


def v2_dataset():
    data = dataset()
    data['format_version'] = 2
    data['module']['key'] = 'ga_personal'
    data['rotations'] = [{
        'id': 'nala', 'kind': 'weekday_fixed_sunday_cycle', 'timezone': 'Europe/Belgrade',
        'weekday_owners_iso': dict(zip(map(str, range(6)), ['rrita', 'mrika', 'lirza'] * 2)),
        'sunday_cycle': {'anchor_date': '2026-11-01', 'order': ['lirza', 'rrita', 'mrika']},
        'members': [{'position': i, 'person_id': p} for i, p in enumerate(['lirza', 'rrita', 'mrika'])],
    }]
    task = data['task_templates'][0]
    task.update(id='rrita_room_daily', person_id='rrita', short_code='ROOM-D',
                recurrence_label='Daily', estimated_duration_minutes=12,
                schedule_rules=[{'trigger_type': 'clock', 'start_time': None, 'suggested_start_time': '06:50'}])
    return data


class DatasetV2RulesTests(unittest.TestCase):
    def test_weekdays_stay_fixed_and_only_sundays_cycle(self):
        _, rotation = service.validate_dataset(v2_dataset())
        for day, expected in [
            ('2026-10-29', 'rrita'), ('2026-10-30', 'mrika'), ('2026-10-31', 'lirza'),
            ('2026-11-01', 'lirza'), ('2026-11-02', 'rrita'), ('2026-11-08', 'rrita'),
            ('2026-11-15', 'mrika'), ('2026-11-22', 'lirza'), ('2027-01-04', 'rrita'),
        ]:
            self.assertEqual(service.rotation_owner(date.fromisoformat(day), rotation), expected)
        self.assertIsNone(service.rotation_owner(date(2026, 10, 25), rotation))

    def test_metadata_and_suggestions_never_activate_clocks(self):
        data = v2_dataset()
        data['task_templates'][0]['schedule_rules'][0]['weekdays'] = '0,1,2,3,4'
        parsed, _ = service.validate_dataset(data)
        model = parsed[0][1]
        self.assertEqual(model['short_code'], 'ROOM-D')
        self.assertEqual(model['estimated_minutes'], 12)
        self.assertEqual(model['weekdays'], list(range(5)))
        self.assertEqual(model['schedule_hints'][0]['suggested_start_time'], '06:50:00')
        self.assertIsNone(model['due_time'])
        self.assertFalse(model['enabled'])
        for mutate in [
            lambda d: d['rotations'][0]['sunday_cycle'].update(anchor_date='2026-11-02'),
            lambda d: d['rotations'][0]['weekday_owners_iso'].update({'0': 'gane'}),
            lambda d: d['task_templates'][0]['schedule_rules'][0].update(weekdays='7'),
        ]:
            invalid = copy.deepcopy(data); mutate(invalid)
            with self.assertRaises(Exception) as raised:
                service.validate_dataset(invalid)
            self.assertEqual(raised.exception.status_code, 422)

    def test_tablet_receives_actual_dated_rotation_instead_of_three_day_rule(self):
        data = v2_dataset()
        parsed, rotation = service.validate_dataset(data)
        definition = {**parsed[0][1], 'assignment': 'rotation', 'assignees': [], 'enabled': True}
        template = SimpleNamespace(id=uuid.uuid4(), definition=definition, archived=False)
        occurrence = SimpleNamespace(template_id=template.id, assignment_key='rotation',
            snapshot={**definition, 'assignees': ['lirza']}, status='pending',
            local_date='2026-11-01', due_at=None)
        cards = exported_cards([template], [occurrence], SimpleNamespace(config={'nala_rotation': rotation}), service.PEOPLE)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]['person_id'], 'lirza')
        self.assertEqual(cards[0]['date'], '2026-11-01')
        self.assertIsNone(cards[0]['repeat'])
        self.assertFalse(cards[0]['alarm'])


@unittest.skipUnless(os.getenv('GA_PERSONAL_TEST_DATABASE_URL'), 'Disposable PostgreSQL required')
class DatasetV2DatabaseTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.GaPersonalDatabaseTests.asyncSetUp
    asyncTearDown = fixtures.GaPersonalDatabaseTests.asyncTearDown
    as_person = fixtures.GaPersonalDatabaseTests.as_person

    async def test_upgrade_renames_uuid_updates_only_untouched_and_preserves_history(self):
        old = dataset(); old['task_templates'][0].update(id='rrita_room', person_id='rrita')
        new = v2_dataset()
        async with self.sessions() as db:
            member = (await db.execute(select(Member).where(Member.person_key == 'gane'))).scalar_one()
            await service.import_dataset(db, member, old, apply=True, expected_hash=service.document_hash(old))
            row = (await db.execute(select(Template))).scalar_one()
            # Simulate the shape imported before optional v2 metadata existed.
            original = {k: v for k, v in row.definition.items() if k not in {'short_code', 'recurrence_label'}}
            row.import_hash = service.document_hash(original)
            row.definition = {**original, 'enabled': True}
            await db.commit()
            await service.generate(db, member, GenerateRequest(day=date(2026, 10, 29)))
            occurrence = (await db.execute(select(Occurrence))).scalar_one()
            original_id, snapshot, occurrence_id = row.id, copy.deepcopy(occurrence.snapshot), occurrence.id
            preview = await service.import_dataset(db, member, new)
            self.assertEqual(preview['create'], [])
            self.assertEqual(preview['update'], ['rrita_room_daily'])
            self.assertEqual(preview['rename'], {'rrita_room_daily': 'rrita_room'})
            for _ in range(2):
                await service.import_dataset(db, member, new, apply=True, expected_hash=preview['dataset_hash'])
            self.assertEqual((await db.execute(select(func.count(Template.id)))).scalar_one(), 1)
            row = (await db.execute(select(Template))).scalar_one()
            self.assertEqual(row.id, original_id)
            self.assertTrue(row.definition['enabled'])
            self.assertEqual(row.definition['short_code'], 'ROOM-D')
            self.assertEqual((await db.get(Occurrence, occurrence_id)).snapshot, snapshot)
            self.assertEqual((await service.generate(db, member, GenerateRequest(day=date(2026, 10, 29))))['created'], 0)
            row.definition = {**row.definition, 'title': 'Local change'}
            row.import_hash = None
            await db.commit()
            changed = copy.deepcopy(new); changed['task_templates'][0]['title'] = 'New source'
            conflict = await service.import_dataset(db, member, changed)
            self.assertEqual(conflict['conflicts'], ['rrita_room_daily'])
            with self.assertRaises(Exception) as raised:
                await service.import_dataset(db, member, changed, apply=True, expected_hash=conflict['dataset_hash'])
            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(row.definition['title'], 'Local change')

    async def test_arrival_uses_first_authenticated_person_and_retries_do_not_reassign(self):
        from app.schemas.ga_personal import TemplateWrite, TemplateDefinition
        async with self.sessions() as db:
            admin = (await db.execute(select(Member).where(Member.person_key == 'gane'))).scalar_one()
            task = TemplateDefinition(title='First home', assignment='first_home', assignees=[],
                frequency='conditional', enabled=True)
            await service.save_template(db, admin, TemplateWrite(definition=task))
        self.as_person('mrika')
        payload = {'request_id': str(uuid.uuid4())}
        for _ in range(2):
            result = await self.client.post('/api/ga-personal/arrival', json=payload)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()['first_home'], 'mrika')
        self.as_person('rrita')
        result = await self.client.post('/api/ga-personal/arrival', json={'request_id': str(uuid.uuid4())})
        self.assertEqual(result.json()['first_home'], 'mrika')
        async with self.sessions() as db:
            rows = (await db.execute(select(Occurrence))).scalars().all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].snapshot['assignees'], ['mrika'])
            self.assertIsNone(rows[0].due_at)
            self.assertEqual((await db.execute(select(func.count(Event.id)).where(Event.kind == 'arrived'))).scalar_one(), 2)
