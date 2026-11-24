from datetime import datetime
from typing import Literal

from pydantic import BaseModel

DISCORD_MESSAGE_ID_PATTERN = r"^[0-9]{1,32}$"
DISCORD_MENTION_ID_PATTERN = r"^dc:[0-9]{1,32}$"
DISCORD_FEED_DEFAULT_LIMIT = 25
DISCORD_FEED_MAX_LIMIT = 50


class DiscordFeedReactor(BaseModel):
    name: str
    initials: str


class DiscordFeedReaction(BaseModel):
    emoji: str
    count: int
    users: list[DiscordFeedReactor]


class DiscordAttachmentName(BaseModel):
    name: str


class DiscordAttachmentLink(DiscordAttachmentName):
    url: str
    content_type: str | None


class DiscordMentionAttachments(BaseModel):
    id: str
    attachments: list[DiscordAttachmentLink]


class DiscordFeedMention(BaseModel):
    id: str
    author: str
    author_initials: str
    channel: str
    time: datetime
    edited_at: datetime | None
    text: str
    url: str
    attachments: list[DiscordAttachmentName]
    status: Literal["new", "seen", "done"]
    reactions: list[DiscordFeedReaction]
    reactions_synced_at: datetime | None
    reviewed_by: list[str]
    ready_for_ga: bool


class DiscordMentionsFeed(BaseModel):
    channel_id: str
    timezone: str
    bot_configured: bool
    items: list[DiscordFeedMention]
    next_before: str | None
