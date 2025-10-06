import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import asyncio
import os
import re
from typing import Optional

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)

        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.duration = data.get('duration')
        self.thumbnail = data.get('thumbnail')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

    @classmethod
    async def search_youtube(cls, query, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        search_query = f"ytsearch:{query}"
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search_query, download=False))

        if 'entries' in data and data['entries']:
            return data['entries'][0]
        return None

class MusicQueue:
    def __init__(self):
        self.queue = []
        self.current = None

    def add(self, item):
        self.queue.append(item)

    def get_next(self):
        if self.queue:
            return self.queue.pop(0)
        return None

    def clear(self):
        self.queue.clear()
        self.current = None

    def is_empty(self):
        return len(self.queue) == 0

class MusicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_clients = {}
        self.music_queues = {}

        spotify_client_id = os.getenv('SPOTIFY_CLIENT_ID')
        spotify_client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')

        if spotify_client_id and spotify_client_secret:
            try:
                client_credentials_manager = SpotifyClientCredentials(
                    client_id=spotify_client_id,
                    client_secret=spotify_client_secret
                )
                self.spotify = spotipy.Spotify(client_credentials_manager=client_credentials_manager)
            except Exception as e:
                print(f"Failed to initialize Spotify client: {e}")
                self.spotify = None
        else:
            print("Spotify credentials not found. Spotify functionality will be disabled.")
            self.spotify = None

    def get_music_queue(self, guild_id):
        if guild_id not in self.music_queues:
            self.music_queues[guild_id] = MusicQueue()
        return self.music_queues[guild_id]

    def is_spotify_url(self, url):
        spotify_regex = r'https?://open\.spotify\.com/(track|album|playlist)/([a-zA-Z0-9]+)'
        return re.match(spotify_regex, url) is not None

    def is_youtube_url(self, url):
        youtube_regex = r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/'
        return re.match(youtube_regex, url) is not None

    async def get_spotify_track_info(self, url):
        if not self.spotify:
            return None

        try:
            track_id = url.split('/')[-1].split('?')[0]
            track = self.spotify.track(track_id)

            artist_names = ', '.join([artist['name'] for artist in track['artists']])
            track_name = track['name']
            search_query = f"{artist_names} - {track_name}"

            return search_query
        except Exception as e:
            print(f"Error fetching Spotify track: {e}")
            return None

    async def play_next(self, guild_id):
        queue = self.get_music_queue(guild_id)
        voice_client = self.voice_clients.get(guild_id)

        if not voice_client:
            return

        next_song = queue.get_next()
        if next_song:
            queue.current = next_song
            try:
                player = await YTDLSource.from_url(next_song['url'], stream=True)
                voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(self.play_next(guild_id), self.bot.loop))
            except Exception as e:
                print(f"Error playing next song: {e}")
                await self.play_next(guild_id)
        else:
            queue.current = None

    @app_commands.command(name="play", description="Play a song from YouTube or Spotify")
    @app_commands.describe(query="YouTube URL, Spotify URL, or song name to search")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()

        if not interaction.user.voice:
            embed = discord.Embed(
                title="❌ Error",
                description="You need to be in a voice channel to use this command!",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)
            return

        voice_channel = interaction.user.voice.channel
        guild_id = interaction.guild.id

        if guild_id not in self.voice_clients:
            try:
                voice_client = await voice_channel.connect()
                self.voice_clients[guild_id] = voice_client
            except Exception as e:
                embed = discord.Embed(
                    title="❌ Error",
                    description=f"Failed to connect to voice channel: {str(e)}",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed)
                return

        voice_client = self.voice_clients[guild_id]
        queue = self.get_music_queue(guild_id)

        try:
            if self.is_spotify_url(query):
                if not self.spotify:
                    embed = discord.Embed(
                        title="❌ Error",
                        description="Spotify functionality is not available. Please check your Spotify credentials.",
                        color=discord.Color.red()
                    )
                    await interaction.followup.send(embed=embed)
                    return

                search_query = await self.get_spotify_track_info(query)
                if not search_query:
                    embed = discord.Embed(
                        title="❌ Error",
                        description="Failed to get Spotify track information.",
                        color=discord.Color.red()
                    )
                    await interaction.followup.send(embed=embed)
                    return

                track_data = await YTDLSource.search_youtube(search_query)
                if not track_data:
                    embed = discord.Embed(
                        title="❌ Error",
                        description="Could not find the song on YouTube.",
                        color=discord.Color.red()
                    )
                    await interaction.followup.send(embed=embed)
                    return

            elif self.is_youtube_url(query):
                loop = asyncio.get_event_loop()
                track_data = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
                if 'entries' in track_data:
                    track_data = track_data['entries'][0]
            else:
                track_data = await YTDLSource.search_youtube(query)
                if not track_data:
                    embed = discord.Embed(
                        title="❌ Error",
                        description="Could not find any results for your search.",
                        color=discord.Color.red()
                    )
                    await interaction.followup.send(embed=embed)
                    return

            song_info = {
                'title': track_data.get('title', 'Unknown'),
                'url': track_data.get('webpage_url', track_data.get('url')),
                'thumbnail': track_data.get('thumbnail'),
                'duration': track_data.get('duration'),
                'requested_by': interaction.user
            }

            if voice_client.is_playing() or queue.current:
                queue.add(song_info)
                embed = discord.Embed(
                    title="🎵 Added to Queue",
                    description=f"**{song_info['title']}**\nRequested by {interaction.user.mention}",
                    color=discord.Color.green()
                )
                if song_info['thumbnail']:
                    embed.set_thumbnail(url=song_info['thumbnail'])
                embed.add_field(name="Position in queue", value=len(queue.queue), inline=True)
            else:
                queue.current = song_info
                player = await YTDLSource.from_url(song_info['url'], stream=True)
                voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(self.play_next(guild_id), self.bot.loop))

                embed = discord.Embed(
                    title="🎵 Now Playing",
                    description=f"**{song_info['title']}**\nRequested by {interaction.user.mention}",
                    color=discord.Color.blue()
                )
                if song_info['thumbnail']:
                    embed.set_thumbnail(url=song_info['thumbnail'])

            await interaction.followup.send(embed=embed)

        except Exception as e:
            embed = discord.Embed(
                title="❌ Error",
                description=f"An error occurred while trying to play the song: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="pause", description="Pause the current song")
    async def pause(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        voice_client = self.voice_clients.get(guild_id)

        if not voice_client or not voice_client.is_playing():
            embed = discord.Embed(
                title="❌ Error",
                description="Nothing is currently playing!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return

        voice_client.pause()
        embed = discord.Embed(
            title="⏸️ Paused",
            description="Music has been paused.",
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="resume", description="Resume the paused song")
    async def resume(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        voice_client = self.voice_clients.get(guild_id)

        if not voice_client or not voice_client.is_paused():
            embed = discord.Embed(
                title="❌ Error",
                description="Nothing is currently paused!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return

        voice_client.resume()
        embed = discord.Embed(
            title="▶️ Resumed",
            description="Music has been resumed.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="skip", description="Skip the current song")
    async def skip(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        voice_client = self.voice_clients.get(guild_id)
        queue = self.get_music_queue(guild_id)

        if not voice_client or not voice_client.is_playing():
            embed = discord.Embed(
                title="❌ Error",
                description="Nothing is currently playing!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return

        voice_client.stop()

        if queue.is_empty():
            embed = discord.Embed(
                title="⏭️ Skipped",
                description="Song skipped. Queue is empty.",
                color=discord.Color.blue()
            )
        else:
            embed = discord.Embed(
                title="⏭️ Skipped",
                description="Song skipped. Playing next song...",
                color=discord.Color.blue()
            )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="stop", description="Stop music and clear the queue")
    async def stop(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        voice_client = self.voice_clients.get(guild_id)
        queue = self.get_music_queue(guild_id)

        if not voice_client:
            embed = discord.Embed(
                title="❌ Error",
                description="Bot is not connected to a voice channel!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return

        voice_client.stop()
        queue.clear()
        await voice_client.disconnect()
        del self.voice_clients[guild_id]

        embed = discord.Embed(
            title="⏹️ Stopped",
            description="Music stopped and queue cleared. Disconnected from voice channel.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="queue", description="Show the current music queue")
    async def queue(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        queue = self.get_music_queue(guild_id)

        if not queue.current and queue.is_empty():
            embed = discord.Embed(
                title="📝 Queue",
                description="The queue is empty!",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed)
            return

        embed = discord.Embed(
            title="📝 Current Queue",
            color=discord.Color.blue()
        )

        if queue.current:
            embed.add_field(
                name="🎵 Now Playing",
                value=f"**{queue.current['title']}**\nRequested by {queue.current['requested_by'].mention}",
                inline=False
            )

        if not queue.is_empty():
            queue_list = []
            for i, song in enumerate(queue.queue[:10], 1):
                queue_list.append(f"{i}. **{song['title']}** - {song['requested_by'].mention}")

            embed.add_field(
                name="📋 Up Next",
                value="\n".join(queue_list),
                inline=False
            )

            if len(queue.queue) > 10:
                embed.add_field(
                    name="📊 Queue Info",
                    value=f"... and {len(queue.queue) - 10} more songs",
                    inline=False
                )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="nowplaying", description="Show information about the current song")
    async def nowplaying(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        queue = self.get_music_queue(guild_id)
        voice_client = self.voice_clients.get(guild_id)

        if not queue.current or not voice_client or not voice_client.is_playing():
            embed = discord.Embed(
                title="❌ Error",
                description="Nothing is currently playing!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return

        current_song = queue.current
        embed = discord.Embed(
            title="🎵 Now Playing",
            description=f"**{current_song['title']}**",
            color=discord.Color.blue()
        )

        if current_song.get('thumbnail'):
            embed.set_thumbnail(url=current_song['thumbnail'])

        embed.add_field(name="Requested by", value=current_song['requested_by'].mention, inline=True)

        if current_song.get('duration'):
            minutes, seconds = divmod(current_song['duration'], 60)
            embed.add_field(name="Duration", value=f"{int(minutes)}:{int(seconds):02d}", inline=True)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leave", description="Disconnect the bot from the voice channel")
    async def leave(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        voice_client = self.voice_clients.get(guild_id)

        if not voice_client:
            embed = discord.Embed(
                title="❌ Error",
                description="Bot is not connected to a voice channel!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return

        await voice_client.disconnect()
        del self.voice_clients[guild_id]

        if guild_id in self.music_queues:
            self.music_queues[guild_id].clear()

        embed = discord.Embed(
            title="👋 Disconnected",
            description="Bot has left the voice channel.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(MusicCog(bot))