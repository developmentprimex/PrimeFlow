"""Identity supplied by the separate trusted family bot, never the browser."""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

Snowflake = Annotated[str, Field(pattern=r"^[0-9]{17,20}$")]


class HostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor_id: Snowflake
    guild_id: Snowflake
    channel_id: Snowflake
    present_user_ids: list[Snowflake] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def unique_listeners(self):
        if len(self.present_user_ids) != len(set(self.present_user_ids)):
            raise ValueError("Personat nuk mund të përsëriten.")
        return self
