import uuid
from pydantic import BaseModel, ConfigDict, Field

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')

class VoiceActor(StrictModel):
    discord_user_id: str = Field(pattern=r'^\d{1,32}$')
    guild_id: str = Field(pattern=r'^\d{1,32}$')
    channel_id: str = Field(pattern=r'^\d{1,32}$')
    voice_channel_id: str | None = Field(default=None, pattern=r'^\d{1,32}$')

class VoiceStart(VoiceActor):
    request_id: str = Field(pattern=r'^\d{1,32}$')
    instance_id: uuid.UUID
    capture_token: str = Field(min_length=32, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    department_id: uuid.UUID | None = None

class Worker(StrictModel):
    capture_token: str = Field(min_length=32, max_length=128)
    instance_id: uuid.UUID

class Finish(Worker):
    segment_count: int = Field(ge=0)
    partial: bool = False

class SegmentMeta(Worker):
    sequence: int = Field(ge=0)
    speaker_id: str = Field(pattern=r'^\d{1,32}$')
    speaker_name: str = Field(min_length=1, max_length=100)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)

class Interrupt(Worker):
    reason: str = Field(max_length=60, pattern=r'^[a-z_]+$')

class DeliveryAck(StrictModel):
    delivery_token: uuid.UUID
    message_ids: list[str] = Field(max_length=10)
