from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

DISCORD_MESSAGE_ID_PATTERN = r"^[0-9]{1,32}$"
DISCORD_MENTION_ID_PATTERN = r"^dc:[0-9]{1,32}$"
DISCORD_FEED_DEFAULT_LIMIT = 25
DISCORD_FEED_MAX_LIMIT = 50
DiscordReplyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1996)]
DiscordReactionEmoji = Literal["👍", "✅", "👀", "❌"]


class DiscordReplyIn(BaseModel):
    text: DiscordReplyText
    nonce: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,25}$")


class DiscordReplyResult(BaseModel):
    id: str
    url: str


class DiscordReactIn(BaseModel):
    emoji: DiscordReactionEmoji
    remove: bool = False


class DiscordReactResult(BaseModel):
    id: str
    emoji: DiscordReactionEmoji
    removed: bool


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


class DiscordContextMessage(BaseModel):
    id: str
    author: str
    author_initials: str
    channel: str
    time: datetime
    edited_at: datetime | None
    text: str
    url: str
    attachments: list[DiscordAttachmentName]
    reactions: list[DiscordFeedReaction]
    reactions_synced_at: datetime | None


class DiscordMentionContext(BaseModel):
    para: list[DiscordContextMessage]
    pas: list[DiscordContextMessage]
    reply: DiscordContextMessage | None
    përgjigjet: list[DiscordContextMessage]


class DiscordFeedMention(DiscordContextMessage):
    context: DiscordMentionContext
    status: Literal["new", "seen", "done"]
    reviewed_by: list[str]
    ready_for_ga: bool
    ga_replied: bool = False
    ga_reacted: bool = False
    others_reacted_before_ga: bool = False
    others_reacted_before_ga_names: list[str] = Field(default_factory=list)
    others_reacted_before_ga_known: bool = False


class DiscordMentionsFeed(BaseModel):
    channel_id: str
    timezone: str
    bot_configured: bool
    items: list[DiscordFeedMention]
    next_before: str | None
