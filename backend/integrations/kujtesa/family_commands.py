"""Manual family tools; tasks and authorization always come from PrimeFlow."""
import asyncio
import ctypes.util
import math
import struct
from pathlib import Path

import discord


def load_opus():
    if discord.opus.is_loaded():
        return True
    bundled = Path(discord.__file__).resolve().parent / "bin" / ("libopus-0.x64.dll" if struct.calcsize("P") == 8 else "libopus-0.x86.dll")
    library = ctypes.util.find_library("opus")
    for candidate in ([library] if library else []) + ([str(bundled)] if bundled.is_file() else []):
        try:
            discord.opus.load_opus(candidate)
            return True
        except OSError:
            continue
    return False


class Chime(discord.AudioSource):
    def __init__(self):
        self.pos = 0

    def read(self):
        if self.pos >= 67200:
            return b""
        output = bytearray()
        for offset in range(960):
            t = (self.pos + offset) / 48000
            value = 0.0
            for hz, start, end in ((523.25, 0.0, 0.55), (659.25, 0.45, 1.2)):
                if start <= t < end:
                    value += .22 * min(1, (t - start) / .02) * min(1, (end - t) / .12) * math.sin(2 * math.pi * hz * t)
            sample = struct.pack("<h", int(max(-1, min(1, value)) * 32767))
            output.extend(sample + sample)
        self.pos += 960
        return bytes(output)

    def is_opus(self):
        return False


class DemoView(discord.ui.View):
    def __init__(self, actor):
        super().__init__(timeout=300)
        self.actor = actor
        for label in ("E pashë", "Po ia nisi", "U kry", "Më duhet ndihmë"):
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary)

            async def click(interaction, text=label):
                await interaction.response.edit_message(content=f"Provë: {text}. Detyrat në PrimeFlow nuk ndryshuan.", view=self)

            button.callback = click
            self.add_item(button)
        menu = discord.ui.Select(placeholder="Hapat ose më duhet kohë", options=[
            discord.SelectOption(label="Hapat / Si bëhet?", value="steps"),
            *[discord.SelectOption(label=f"Më duhet kohë · {minutes} minuta", value=f"later{minutes}") for minutes in (15, 30, 60)],
        ])

        async def choose(interaction):
            choice = menu.values[0]
            text = "1. Hape detyrën.\n2. Ndiqi hapat.\n3. Konfirmo kryerjen." if choice == "steps" else f"Provë: shtyrje për {choice[5:]} minuta."
            await interaction.response.edit_message(content=text + "\nDetyrat në PrimeFlow nuk ndryshuan.", view=self)

        menu.callback = choose
        self.add_item(menu)

    async def interaction_check(self, interaction):
        return interaction.user.id == self.actor


async def play_chime(bot, interaction, allowed):
    # Reuse the voice host's tested channel privacy check, without starting AI.
    if __package__:
        from .voice_host import KujtesaHost
    else:
        from voice_host import KujtesaHost
    channel = getattr(getattr(interaction.user, "voice", None), "channel", None)
    if channel is None or not interaction.guild:
        raise ValueError("Hyr në kanalin privat zanor para /zeri.")
    if bot.host and bot.host.session:
        raise ValueError("Përfundo bisedën zanore para tingullit.")
    KujtesaHost(bot, worker="", node="node")._private(channel, set(allowed))
    if not load_opus():
        raise ValueError("Tingulli kërkon bibliotekën libopus në server.")
    if interaction.guild.voice_client:
        raise ValueError("Kujtesa është tashmë në një kanal zanor.")
    if bot.family_chime_starting:
        raise ValueError("Tingulli është duke u nisur.")
    bot.family_chime_starting = True
    connected = None
    try:
        connected = await channel.connect()
        bot.family_chime = connected
        bot.family_chime_allowed = set(allowed)
        KujtesaHost(bot)._private(channel, set(allowed))
        finished = asyncio.Event()
        loop = asyncio.get_running_loop()
        connected.play(Chime(), after=lambda _: loop.call_soon_threadsafe(finished.set))
        await asyncio.wait_for(finished.wait(), 8)
    finally:
        bot.family_chime = None
        bot.family_chime_starting = False
        if connected:
            await connected.disconnect()


def register_family_commands(bot):
    labels = {"sot": "Detyrat e tua të sotme nga PrimeFlow", "provo": "Provo butonat pa ndryshuar detyra",
        "mengjesi": "Rutina jote e mëngjesit", "kujto": "Dërgo manualisht kartën e Nalës",
        "ndihme": "Komandat dhe butonat e Kujtesës", "ore": "Ora te shtëpia", "kush": "Familjarët e lidhur",
        "nala": "Kujt i bie Nala sot", "vikendi": "Pastrimi i vikendit", "zeri": "Tingull i shkurtër në kanalin privat zanor",
        "dil": "Dil pas tingullit", "zgjova": "Regjistro zgjimin në PrimeFlow", "erdha": "Regjistro kthimin në shtëpi"}

    def make(name):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                result = await bot.api("/command", {"command": name, "actor_id": str(interaction.user.id),
                    "guild_id": str(interaction.guild_id) if interaction.guild_id else None,
                    "channel_id": str(interaction.channel_id), "interaction_id": str(interaction.id),
                    "delivery_enabled": bot.reminders_enabled})
                if name == "zeri":
                    await play_chime(bot, interaction, result["allowed_user_ids"])
                elif name == "dil":
                    connection = getattr(bot, "family_chime", None)
                    if connection:
                        await connection.disconnect()
                text = result["text"]
                # Split complete responses instead of truncating a person's task list.
                for index in range(0, len(text), 1900):
                    await interaction.followup.send(text[index:index + 1900], ephemeral=True,
                        view=DemoView(interaction.user.id) if name == "provo" and index == 0 else None,
                        allowed_mentions=discord.AllowedMentions.none())
            except Exception as error:
                # Bridge errors are deliberately sanitized by the API.
                text = str(error) if type(error).__name__ in {"BridgeError", "ValueError"} else "Komanda nuk u krye. Provoje përsëri."
                await interaction.followup.send(text[:1900], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        return callback

    for name, description in labels.items():
        bot.tree.command(name=name, description=description)(make(name))
