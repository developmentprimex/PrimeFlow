"""Synthetic interval fixtures; real household configuration stays outside Git."""
import copy
import os
import unittest
import uuid
from datetime import date
from types import SimpleNamespace

from app.schemas.ga_personal import TemplateDefinition
from app.services import ga_personal as service
from app.services.ga_personal_device_sync import exported_cards
from sqlalchemy import select
from app.schemas.ga_personal import GenerateRequest, TemplateWrite
from tests import test_ga_personal as fixtures
from tests.test_ga_personal_dataset_v2 import v2_dataset


def interval_definition(**changes):
    values=dict(title='Interval fixture', assignees=['mrika'], frequency='near_daily', weekdays=[6],
        enabled=True, recurrence_interval_weeks=3, recurrence_anchor_date='2026-11-08')
    values.update(changes)
    return TemplateDefinition(**values).model_dump(mode='json')


class WeekIntervalRulesTests(unittest.TestCase):
    def test_dataset_import_retains_interval_metadata(self):
        data=v2_dataset()
        data['task_templates'][0].update(frequency='near_daily',recurrence_interval_weeks=3,
            recurrence_anchor_date='2026-11-08',schedule_rules=[{'trigger_type':'routine','weekdays':'6'}])
        parsed,_=service.validate_dataset(data)
        self.assertEqual(parsed[0][1]['recurrence_interval_weeks'],3)
        self.assertEqual(parsed[0][1]['recurrence_anchor_date'],'2026-11-08')

    def test_interval_schema_round_trip_and_invalid_configurations(self):
        d=interval_definition()
        self.assertEqual(d['recurrence_interval_weeks'],3)
        self.assertEqual(d['recurrence_anchor_date'],'2026-11-08')
        for changes in [dict(recurrence_anchor_date=None),dict(recurrence_interval_weeks=0),
                        dict(recurrence_interval_weeks=53),dict(frequency='daily')]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                interval_definition(**changes)

    def test_three_week_sunday_schedule_and_year_boundary(self):
        d=interval_definition()
        expected={'2026-11-08','2026-11-29','2026-12-20','2027-01-10'}
        from datetime import timedelta
        day=date(2026,11,1)
        actual=set()
        while day<=date(2027,1,10):
            if service.scheduled(d,day):actual.add(day.isoformat())
            day+=timedelta(days=1)
        self.assertEqual(actual,expected)

    def test_monday_calendar_weeks_and_no_dates_before_anchor(self):
        d=interval_definition(weekdays=[0,6],recurrence_anchor_date='2026-11-04')
        for value,expected in [('2026-11-02',False),('2026-11-08',True),('2026-11-09',False),
                               ('2026-11-23',True),('2026-11-29',True)]:
            with self.subTest(value=value):self.assertEqual(service.scheduled(d,date.fromisoformat(value)),expected)

    def test_interval_uses_calendar_days_across_daylight_saving(self):
        d=interval_definition(recurrence_anchor_date='2026-10-18')
        for value,expected in [('2026-10-18',True),('2026-10-25',False),('2026-11-01',False),('2026-11-08',True)]:
            self.assertEqual(service.scheduled(d,date.fromisoformat(value)),expected)

    def test_legacy_weekday_definitions_do_not_change(self):
        d=interval_definition()
        d.pop('recurrence_interval_weeks');d.pop('recurrence_anchor_date')
        self.assertTrue(service.scheduled(d,date(2026,11,1)))
        self.assertTrue(service.scheduled(d,date(2026,11,15)))
        self.assertFalse(service.scheduled(d,date(2026,11,16)))

    def test_weekend_frequency_keeps_single_weekend_period(self):
        d=interval_definition(frequency='weekly',weekdays=[5],recurrence_anchor_date='2026-11-07')
        self.assertTrue(service.scheduled(d,date(2026,11,7)))
        self.assertFalse(service.scheduled(d,date(2026,11,8)))
        self.assertFalse(service.scheduled(d,date(2026,11,14)))
        self.assertTrue(service.scheduled(d,date(2026,11,28)))
        self.assertEqual(service.period_key(d,date(2026,11,7)),service.period_key(d,date(2026,11,8)))

    def test_interval_tablet_cards_use_actual_dates_without_local_repeat_or_alarm(self):
        d=interval_definition()
        template=SimpleNamespace(id=uuid.uuid4(),definition=d,archived=False)
        occurrence=SimpleNamespace(template_id=template.id,assignment_key='mrika',snapshot=copy.deepcopy(d),
            status='pending',local_date='2026-11-08',due_at=None)
        cards=exported_cards([template],[occurrence],SimpleNamespace(config={}),service.PEOPLE)
        self.assertEqual(len(cards),1)
        self.assertEqual(str(cards[0]['date']),'2026-11-08')
        self.assertIsNone(cards[0]['repeat'])
        self.assertIsNone(cards[0]['days'])
        self.assertIsNone(cards[0]['start'])
        self.assertFalse(cards[0]['alarm'])
        self.assertEqual(exported_cards([template],[],SimpleNamespace(config={}),service.PEOPLE),[])


@unittest.skipUnless(os.getenv('GA_PERSONAL_TEST_DATABASE_URL'),'Disposable PostgreSQL required')
class WeekIntervalDatabaseTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.GaPersonalDatabaseTests.asyncSetUp
    asyncTearDown=fixtures.GaPersonalDatabaseTests.asyncTearDown
    as_person=fixtures.GaPersonalDatabaseTests.as_person

    async def test_rotation_generation_skips_intervening_weeks_and_is_idempotent(self):
        async with self.sessions() as db:
            member=(await db.execute(select(fixtures.Member).where(fixtures.Member.person_key=='gane'))).scalar_one()
            space=await db.get(fixtures.Space,self.space_id)
            space.config={'nala_rotation':v2_dataset()['rotations'][0]}
            d=interval_definition(assignment='rotation',assignees=[],rotation_id='nala')
            saved=await service.save_template(db,member,TemplateWrite(definition=TemplateDefinition.model_validate(d)))
            for value,count in [('2026-11-01',0),('2026-11-08',1),('2026-11-15',0),('2026-11-22',0),('2026-11-29',1),('2026-11-29',0)]:
                result=await service.generate(db,member,GenerateRequest(day=date.fromisoformat(value)))
                self.assertEqual(result['created'],count,value)
            rows=(await db.execute(select(fixtures.Occurrence).where(fixtures.Occurrence.template_id==uuid.UUID(saved['id'])))).scalars().all()
            self.assertEqual(sorted(o.local_date for o in rows),['2026-11-08','2026-11-29'])
            self.assertTrue(all(o.snapshot['assignees']==['rrita'] and o.due_at is None for o in rows))
