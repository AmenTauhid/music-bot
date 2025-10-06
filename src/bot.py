import discord
from discord.ext import commands
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

class MusicBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True

        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        await self.load_extension('src.cogs.music')
        await self.tree.sync()
        print(f"Synced slash commands for {self.user}")

    async def on_ready(self):
        print(f'{self.user} has connected to Discord!')
        print(f'Bot is in {len(self.guilds)} guilds')

async def main():
    bot = MusicBot()

    discord_token = os.getenv('DISCORD_TOKEN')
    if not discord_token:
        print("Error: DISCORD_TOKEN not found in environment variables")
        return

    async with bot:
        await bot.start(discord_token)

if __name__ == '__main__':
    asyncio.run(main())