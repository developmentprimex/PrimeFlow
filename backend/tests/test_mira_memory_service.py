import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from sqlalchemy import select
from tests.test_mira_memory_model import MemoryTests
from app.config import settings
from app.models.discord_assistant import DiscordLink
from app.models.discord_voice_meeting import DiscordVoiceMeeting as Meeting, DiscordVoiceSegment as Segment
from app.models.mira_memory import MiraMemoryItem as Item, MiraMemoryEvent as Event
from app.models.project import Project
from app.models.user import User
from app.schemas.mira_memory import MemoryClarification, MemoryEdit
from app.services import discord_voice_meetings as voice
from app.services import mira_memory


def op(action, item_id=None, title=None, description=None, kind=None, people=(), said='U përmend.', segments=(0,)):
    return {'action': action, 'item_id': item_id, 'title': title, 'description': description, 'kind': kind,
        'people': list(people), 'said': said, 'segments': list(segments)}


class MemoryServiceTests(MemoryTests):
    async def meeting(self, minutes_ago=0, title='1H', **values):
        row = Meeting(id=uuid.uuid4(), user_id=self.uid, link_id=self.lid, department_id=self.did, guild_id='123',
            voice_channel_id='55', private_channel_id='44', request_id=uuid.uuid4().hex[:20], instance_id=uuid.uuid4(),
            capture_token_hash='h', title=title, status='READY', partial=False, stop_authorized=True,
            started_at=voice.now()-timedelta(minutes=minutes_ago), **values)
        async with self.sessions() as db:
            db.add(row)
            await db.commit()
        return row

    async def item(self, title, *, status='OPEN', mentioned_days_ago=0, updated_days_ago=0, **values):
        moment = voice.now()
        row = Item(id=uuid.uuid4(), title=title, description=values.pop('description', 'Gjendja.'), kind='TASK',
            status=status, people=[], version=1, mention_count=values.pop('mention_count', 1), human_edited=False,
            last_mentioned_at=moment-timedelta(days=mentioned_days_ago),
            updated_at=moment-timedelta(days=updated_days_ago), **values)
        async with self.sessions() as db:
            db.add(row)
            await db.commit()
        return row

    async def apply(self, meeting, operations, versions, **options):
        async with self.sessions() as db:
            row = await db.get(Meeting, meeting.id)
            stats = await mira_memory.apply_operations(db, row, operations, versions, **options)
            await db.commit()
        return stats

    async def test_snapshot_includes_open_recent_closed_and_wrong_titles(self):
        await self.item('Oferta')
        await self.item('Fatura', status='CLOSED', updated_days_ago=3)
        await self.item('Raporti i vjetër', status='CLOSED', updated_days_ago=20)
        await self.item('Gabim', status='WRONG', updated_days_ago=90)
        async with self.sessions() as db:
            result = await mira_memory.snapshot(db)
        self.assertEqual({i['title'] for i in result['items']}, {'Oferta', 'Fatura'})
        self.assertEqual(result['wrong_titles'], ['Gabim'])
        self.assertEqual(result['omitted'], 0)

    async def test_snapshot_marks_quiet_after_30_days(self):
        await self.item('Printeri', mentioned_days_ago=31)
        await self.item('Oferta', mentioned_days_ago=29)
        async with self.sessions() as db:
            items = {i['title']: i for i in (await mira_memory.snapshot(db))['items']}
        self.assertTrue(items['Printeri']['quiet'])
        self.assertFalse(items['Oferta']['quiet'])

    async def test_snapshot_truncates_to_context_limit(self):
        await self.item('E vjetër', mentioned_days_ago=5, description='x'*400)
        await self.item('E re', mentioned_days_ago=1, description='y'*400)
        with patch.object(settings, 'MIRA_MEMORY_CONTEXT_CHARS', 700):
            async with self.sessions() as db:
                result = await mira_memory.snapshot(db)
        self.assertEqual([i['title'] for i in result['items']], ['E re'])
        self.assertEqual(result['omitted'], 1)

    async def test_add_mention_change_close_apply_and_record_history(self):
        meeting = await self.meeting()
        a, b, c = await self.item('A'), await self.item('B'), await self.item('C')
        versions = {str(a.id): 1, str(b.id): 1, str(c.id): 1}
        stats = await self.apply(meeting, [
            op('add', title='Oferta Albaniaplast', description='Arta e përgatit.', kind='TASK', people=['Arta'], segments=(2, 3)),
            op('mention', str(a.id), people=['Besnik']),
            op('change', str(b.id), description='Afati u shty në 30 tetor.'),
            op('close', str(c.id), said='U dërgua.')], versions)
        self.assertEqual(stats, {'applied': 4, 'rejected': 0, 'dropped': 0})
        async with self.sessions() as db:
            new = (await db.execute(select(Item).where(Item.title == 'Oferta Albaniaplast'))).scalar_one()
            self.assertEqual((new.status, new.mention_count, new.people), ('OPEN', 1, ['Arta']))
            a, b, c = await db.get(Item, a.id), await db.get(Item, b.id), await db.get(Item, c.id)
            self.assertEqual((a.mention_count, a.version, a.people), (2, 1, ['Besnik']))
            self.assertEqual((b.description, b.version), ('Afati u shty në 30 tetor.', 2))
            self.assertEqual((c.status, c.version), ('CLOSED', 2))
            events = (await db.execute(select(Event).where(Event.meeting_id == meeting.id))).scalars().all()
            self.assertEqual(sorted(e.kind for e in events), ['CHANGE', 'CLOSE', 'MENTION', 'MENTION'])
            self.assertEqual(next(e for e in events if e.item_id == new.id).refs, [2, 3])

    async def test_unknown_ids_and_incomplete_operations_are_rejected(self):
        meeting = await self.meeting()
        a = await self.item('A')
        stats = await self.apply(meeting, [
            op('mention', str(uuid.uuid4())),
            op('add', description='Pa titull.', kind='TASK'),
            op('add', title='Lloj i gabuar', description='x', kind='OTHER'),
            op('mention', str(a.id))], {str(a.id): 1})
        self.assertEqual(stats, {'applied': 1, 'rejected': 3, 'dropped': 0})

    async def test_version_mismatch_keeps_mention_drops_change(self):
        meeting = await self.meeting()
        a = await self.item('A', description='Nga njeriu.')
        async with self.sessions() as db:
            row = await db.get(Item, a.id)
            row.version = 2
            await db.commit()
        stats = await self.apply(meeting, [op('change', str(a.id), description='Nga Mira.')], {str(a.id): 1})
        self.assertEqual(stats, {'applied': 0, 'rejected': 0, 'dropped': 1})
        async with self.sessions() as db:
            row = await db.get(Item, a.id)
            self.assertEqual((row.description, row.mention_count), ('Nga njeriu.', 2))
            kinds = (await db.execute(select(Event.kind).where(Event.item_id == a.id))).scalars().all()
            self.assertEqual(kinds, ['MENTION'])

    async def test_wrong_title_is_not_recreated(self):
        meeting = await self.meeting()
        await self.item('Printeri i ri', status='WRONG')
        stats = await self.apply(meeting, [op('add', title=' printeri i RI ', description='x', kind='TOPIC')], {})
        self.assertEqual(stats['rejected'], 1)
        async with self.sessions() as db:
            self.assertEqual(len((await db.execute(select(Item))).scalars().all()), 1)

    async def test_several_operations_on_one_item_count_one_meeting_and_keep_miras_close(self):
        meeting = await self.meeting()
        item = await self.item('Fatura')
        stats = await self.apply(meeting, [op('change', str(item.id), description='U dërgua sot.'),
            op('close', str(item.id), said='U konfirmua.'), op('mention', str(item.id))], {str(item.id): 1})
        self.assertEqual(stats, {'applied': 3, 'rejected': 0, 'dropped': 0})
        async with self.sessions() as db:
            row = await db.get(Item, item.id)
            self.assertEqual((row.status, row.description, row.mention_count, row.version), ('CLOSED', 'U dërgua sot.', 2, 3))

    async def test_evidence_follow_up_and_confirmed_closure(self):
        first = await self.meeting(60)
        second = await self.meeting(30)
        third = await self.meeting()
        source = {'speaker_name': 'GA', 'transcript': 'Kontrollojeni Dantese deri nesër.'}
        segment_id = uuid.uuid4()
        project_id = uuid.uuid4()
        async with self.sessions() as db:
            db.add(Project(id=project_id, title='Dantese', department_id=self.did))
            colleague = User(id=uuid.uuid4(), username='second_organizer', full_name='Arta Test',
                email='organizer@example.test', password_hash='not-a-password', department_id=self.did)
            db.add(colleague)
            await db.flush()
            link = DiscordLink(id=uuid.uuid4(), user_id=colleague.id, discord_user_id='32', guild_id='123', channel_id='45')
            db.add(link)
            await db.flush()
            next_meeting = await db.get(Meeting, second.id)
            next_meeting.user_id, next_meeting.link_id, next_meeting.private_channel_id = colleague.id, link.id, '45'
            db.add(Segment(id=segment_id, session_id=first.id, sequence=0, speaker_id='32', speaker_name='GA',
                start_ms=1200, end_ms=5000, content_hash='dantese', status='DONE', transcript=source['transcript']))
            await db.commit()
        operation = op('add', title='Fotografitë Dantese', description='Kontrolli i fotografive.', kind='INSTRUCTION')
        operation.update(project='Dantese', requested_by='GA', assignee='Arta', deadline_text='deri nesër',
            deadline_date='2099-01-01', questions=['Kush është përgjegjës?'])
        await self.apply(first, [operation], {}, source_segments={0: source})
        async with self.sessions() as db:
            item = (await db.scalars(select(Item))).one()
            event = (await db.scalars(select(Event))).one()
            self.assertEqual((event.details['speakers'], event.details['requested_by'], event.details['project_id']),
                (['GA'], 'GA', str(project_id)))
            self.assertIsNone(event.details['assignee'])
            self.assertNotEqual(event.details['deadline_date'], '2099-01-01')
            detail = await voice.meeting_record(db, first.id)
            point = detail['memory']['points'][0]
            self.assertEqual(point['discussion_state'], 'NEW')
            self.assertTrue(point['needs_follow_up'])
            self.assertEqual(point['questions'], ['Kush është përgjegjës?'])
            self.assertEqual(point['sources'][0], {'id': str(segment_id), 'speaker': 'GA', 'start_ms': 1200, 'end_ms': 5000})
            self.assertEqual((await mira_memory.upcoming_points(db))[0]['meeting_id'], str(first.id))
            self.assertEqual(len(await mira_memory.upcoming_points(db, 'Dantese')), 1)
            self.assertEqual(await mira_memory.upcoming_points(db, 'Modeco'), [])

        repeated = {**operation, 'title': 'Fotografite - DANTESE', 'said': 'Ende në pritje.'}
        await self.apply(second, [repeated, repeated], {}, source_segments={0: source})
        versions = {str(item.id): 1}
        attempted = op('close', str(item.id), said='U mbyll.', segments=(90,))
        self.assertEqual((await self.apply(third, [attempted], versions, source_segments={0: source}))['rejected'], 1)
        attempted.update(segments=[0], confirmation='U rregullua.')
        self.assertEqual((await self.apply(third, [attempted], versions, source_segments={0: source}))['dropped'], 1)
        attempted['confirmation'] = 'Nuk u rregulluan.'
        negative = {**source, 'transcript': 'Nuk u rregulluan.'}
        self.assertEqual((await self.apply(third, [attempted], versions, source_segments={0: negative}))['dropped'], 1)
        confirmed = {**source, 'transcript': 'Fotografitë Dantese u rregulluan.'}
        attempted['confirmation'] = 'Fotografitë Dantese u rregulluan.'
        self.assertEqual((await self.apply(third, [attempted], versions, source_segments={0: confirmed}))['applied'], 1)
        async with self.sessions() as db:
            item = (await db.scalars(select(Item))).one()
            self.assertEqual((item.status, item.mention_count), ('CLOSED', 3))
            self.assertEqual(await mira_memory.upcoming_points(db), [])
            detail = await voice.meeting_record(db, third.id)
            self.assertEqual(detail['memory']['previous'][0]['meeting_id'], str(second.id))
            self.assertEqual(detail['memory']['points'][0]['discussion_state'], 'RESOLVED')
            self.assertFalse(detail['memory']['points'][0]['needs_follow_up'])
            previous = await voice.meeting_record(db, second.id)
            self.assertEqual(previous['memory']['points'][0]['discussion_state'], 'REPEATED')
            visible = await mira_memory.get_item(db, item.id)
            self.assertTrue(any(event['meeting_id'] for event in visible['events']))

    async def test_later_model_change_preserves_human_correction(self):
        item = await self.item('Oferta')
        async with self.sessions() as db:
            user = await db.get(User, self.uid)
            await mira_memory.edit_item(db, user, item.id,
                MemoryEdit(version=1, title='Oferta', description='Afati i korrigjuar nga stafi.'))
        meeting = await self.meeting()
        model = op('change', str(item.id), description='Afati i sugjeruar.')
        source = {'speaker_name': 'GA', 'transcript': 'Mbase ta shtyjmë afatin.'}
        result = await self.apply(meeting, [model], {str(item.id): 2}, source_segments={0: source})
        async with self.sessions() as db:
            item = await db.get(Item, item.id)
        self.assertEqual(result['dropped'], 1)
        self.assertEqual(item.description, 'Afati i korrigjuar nga stafi.')

    async def test_same_title_for_different_projects_keeps_distinct_issues(self):
        first = await self.meeting(60)
        second = await self.meeting()
        operation = op('add', title='Kontrolli i fotografive', description='Duhet kontrolluar.', kind='ACTION')
        for meeting, project in [(first, 'Dantese'), (second, 'Modeco')]:
            source = {'speaker_name': 'GA', 'transcript': f'Kontrolloni fotografitë për {project}.'}
            await self.apply(meeting, [{**operation, 'project': project}], {}, source_segments={0: source})
        async with self.sessions() as db:
            items = (await db.scalars(select(Item))).all()
            self.assertEqual(len(items), 2)
            detail = await voice.meeting_record(db, second.id)
            self.assertEqual(detail['memory']['points'][0]['project'], 'Modeco')
            self.assertEqual(detail['memory']['previous'], [])
            original = next(item for item in items if item.id != uuid.UUID(detail['memory']['points'][0]['id']))
        invalid = op('change', str(original.id), description='Çështje tjetër.', said='Është projekt tjetër.')
        invalid['project'] = 'Modeco'
        result = await self.apply(second, [invalid], {str(original.id): original.version},
            source_segments={0: {'speaker_name': 'GA', 'transcript': 'Kjo është për Modeco.'}})
        self.assertEqual(result['rejected'], 1)

    async def test_staff_clarification_is_persisted_with_history_and_original_transcript(self):
        meeting = await self.meeting()
        transcript = 'Arta pret përgjigje.'
        operation = op('add', title='Përgjigjja e klientit', description=transcript, kind='OPEN_QUESTION')
        question = 'Kur pritet përgjigjja?'
        operation['questions'] = [question]
        await self.apply(meeting, [operation], {}, source_segments={0: {'transcript': transcript}})
        async with self.sessions() as db:
            segment = Segment(id=uuid.uuid4(), session_id=meeting.id, sequence=0, speaker_id='32', speaker_name='GA',
                start_ms=1200, end_ms=5000, content_hash='reply', status='DONE', transcript=transcript)
            db.add(segment)
            colleague = User(id=uuid.uuid4(), username='colleague', full_name='Arta Test',
                email='colleague@example.test', password_hash='not-a-password', department_id=self.did)
            db.add(colleague)
            await db.commit()
            item = (await db.scalars(select(Item))).one()
            payload = MemoryClarification(meeting_id=meeting.id, question=question, answer='Të premten.')
            await mira_memory.answer_clarification(db, colleague, item.id, payload)
            await mira_memory.answer_clarification(db, colleague, item.id, payload)
            result = await voice.meeting_record(db, meeting.id)
            self.assertEqual(result['transcript'][0]['text'], transcript)
            point = result['memory']['points'][0]
            self.assertEqual((point['questions'], point['answers']), ([], {question: 'Të premten.'}))
            visible = await mira_memory.get_item(db, item.id)
            answers = [value for value in visible['events'] if value['kind'] == 'ANSWER']
            self.assertEqual([(value['user_name'], value['meeting_id']) for value in answers],
                [('Arta Test', str(meeting.id))])
            context = (await mira_memory.snapshot(db, include_evidence=True))['items'][0]
            self.assertEqual(context['clarifications'], {question: 'Të premten.'})
            self.assertEqual((await mira_memory.snapshot(db))['items'], [])
            self.assertEqual((await mira_memory.list_items(db, 'all'))['items'][0]['id'], str(item.id))
            edited = await mira_memory.edit_item(db, colleague, item.id,
                MemoryEdit(version=2, title='Përgjigjja e klientit', description='Pritet deri të premten.'))
            self.assertEqual(edited['description'], 'Pritet deri të premten.')


def test_relative_deadline_uses_meeting_date_in_local_timezone():
    when = datetime(2026, 11, 19, 23, 10, tzinfo=timezone.utc)
    details = mira_memory.meeting_evidence({'deadline_text': 'deri nesër'}, [0],
        {0: {'transcript': 'Rregullojeni deri nesër.'}}, {}, 'add', 'INSTRUCTION', when)
    assert details['deadline_date'] == '2026-11-21'
    assert mira_memory.resolve_deadline('deri më 25.11.2026', when) == '2026-11-25'
    assert mira_memory.resolve_deadline('sa më shpejt', when) is None
    assert mira_memory.resolve_deadline('deri nesër ose më 25.11.2026', when) is None
