"""Storage and scoped context queries for the GA staff channel."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.ga_discord_channel_message import GaDiscordArchiveCheckpoint, GaDiscordChannelMessage
from app.models.ga_discord_mention import GaDiscordMention

CONTEXT_WINDOW = timedelta(minutes=2)


def archive_scope(guild_id: str, channel_id: str, parent_channel_id: str | None) -> bool:
    staff_channel = settings.DISCORD_GA_REPLIES_CHANNEL_ID
    return bool(staff_channel and guild_id == settings.DISCORD_GUILD_ID and
                (channel_id == staff_channel or parent_channel_id == staff_channel))


async def checkpoints(db: AsyncSession) -> dict[str, str]:
    rows = await db.execute(select(GaDiscordArchiveCheckpoint.channel_id, GaDiscordArchiveCheckpoint.last_message_id))
    return dict(rows.tuples().all())


async def store_messages(
    db: AsyncSession, messages: list[dict], *, checkpoint_channel_id: str | None = None,
) -> None:
    message = GaDiscordChannelMessage
    for values in messages:
        # A create/edit carries no reaction snapshot. Preserve any independently verified reactions.
        values = dict(values)
        if values["reactions"] is None:
            values.pop("reactions")
            values.pop("reactions_synced_at")
        elif values["reactions_synced_at"] is None:
            values["reactions_synced_at"] = datetime.now(timezone.utc)

        statement = insert(message).values(**values)
        incoming = statement.excluded
        is_newer = func.coalesce(incoming.edited_at, incoming.created_at) >= func.coalesce(message.edited_at, message.created_at)
        fields = ("content", "attachments", "edited_at", "author_name", "channel_name", "reply_to_message_id")
        updates = {field: case((is_newer, incoming[field]), else_=getattr(message, field)) for field in fields}
        if "reactions" in values:
            newer_snapshot = or_(message.reactions_synced_at.is_(None), incoming.reactions_synced_at >= message.reactions_synced_at)
            updates["reactions"] = case((newer_snapshot, incoming.reactions), else_=message.reactions)
            updates["reactions_synced_at"] = case((newer_snapshot, incoming.reactions_synced_at), else_=message.reactions_synced_at)
        await db.execute(statement.on_conflict_do_update(index_elements=[message.id], set_=updates))

    if checkpoint_channel_id and messages:
        cursor = GaDiscordArchiveCheckpoint
        last_id = max((message["id"] for message in messages), key=int)
        statement = insert(cursor).values(channel_id=checkpoint_channel_id, last_message_id=last_id)
        await db.execute(statement.on_conflict_do_update(
            index_elements=[cursor.channel_id],
            set_={"last_message_id": last_id},
            where=tuple_(func.length(cursor.last_message_id), cursor.last_message_id) < tuple_(len(last_id), last_id),
        ))
    await db.commit()


def staff_mention_scope():
    mention = GaDiscordMention
    return and_(
        mention.guild_id == settings.DISCORD_GUILD_ID,
        mention.channel_id == settings.DISCORD_GA_REPLIES_CHANNEL_ID,
        mention.reasons.contains(["mention"]),
    )


def _context_relationships():
    message, mention = GaDiscordChannelMessage, GaDiscordMention
    in_channel = message.channel_id == mention.channel_id
    same_author = and_(in_channel, message.author_discord_id == mention.author_discord_id)
    position = tuple_(message.created_at, func.length(message.id), message.id)
    anchor = tuple_(mention.created_at, func.length(mention.id), mention.id)
    before = and_(same_author, message.created_at >= mention.created_at - CONTEXT_WINDOW, position < anchor)
    after = and_(same_author, message.created_at <= mention.created_at + CONTEXT_WINDOW, position > anchor)
    original = and_(in_channel, message.id == mention.reply_to_message_id)
    responses = or_(message.reply_to_message_id == mention.id, message.channel_id == mention.id)
    return before, after, original, responses


def _linked_context(*relationships):
    message, mention = GaDiscordChannelMessage, GaDiscordMention
    return and_(
        message.guild_id == mention.guild_id,
        message.id != mention.id,
        or_(message.channel_id == mention.channel_id, message.parent_channel_id == mention.channel_id),
        or_(*relationships),
    )


async def context_rows(db: AsyncSession, mention_ids: list[str]):
    message, mention = GaDiscordChannelMessage, GaDiscordMention
    relationships = _context_relationships()
    statement = (
        select(mention.id, message, *relationships)
        .select_from(mention)
        .join(message, _linked_context(*relationships))
        .where(staff_mention_scope(), mention.id.in_(mention_ids))
        .order_by(message.created_at, func.length(message.id), message.id)
    )
    return (await db.execute(statement)).all()


async def get_context_message(db: AsyncSession, message_id: str) -> GaDiscordChannelMessage | None:
    message, mention = GaDiscordChannelMessage, GaDiscordMention
    linked = (
        select(mention.id)
        .where(staff_mention_scope(), _linked_context(*_context_relationships()))
        .correlate(message)
        .exists()
    )
    return await db.scalar(select(message).where(message.id == message_id, linked))
