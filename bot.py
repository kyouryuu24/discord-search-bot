import os
import threading
import csv
import io
from flask import Flask
import requests
from bs4 import BeautifulSoup
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# --- Keep-Alive Webサーバー ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is active!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()

# --- Discord Bot設定 ---
load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
bot = commands.Bot(command_prefix='!', intents=intents)

# 検索ヘルパー関数：チャンネル内メッセージから前後5行を抽出
async def search_in_channels(channels, keyword, limit_per_channel=100):
    results = []
    clean_keyword = keyword.lower()

    for channel in channels:
        if not isinstance(channel, discord.TextChannel):
            continue
        try:
            # 履歴を取得（最新100件）
            messages = [msg async for msg in channel.history(limit=limit_per_channel)]
            messages.reverse()  # 時系列順にソート

            for idx, msg in enumerate(messages):
                if not msg.content:
                    continue
                
                if clean_keyword in msg.content.lower():
                    # 前後5件のメッセージを取得してコンテキスト作成
                    start = max(0, idx - 5)
                    end = min(len(messages), idx + 6)
                    context_msgs = messages[start:end]

                    context_lines = []
                    for c_msg in context_msgs:
                        line = f"{c_msg.author.display_name}: {c_msg.content}"
                        # ヒットした対象行を強調
                        if c_msg.id == msg.id:
                            line = f"**> {line}**"
                        context_lines.append(line)

                    context_text = "\n".join(context_lines)
                    results.append({
                        "channel": channel,
                        "message": msg,
                        "context": context_text,
                        "jump_url": msg.jump_url,
                        "created_at": msg.created_at.strftime("%Y/%m/%d %H:%M")
                    })
                    if len(results) >= 5: # 最大5件まで取得
                        break
        except discord.Forbidden:
            continue
        except Exception as e:
            print(f"Error reading channel {channel.name}: {e}")

    return results

# --- UI コンポーネント (Modal & Views) ---

# キーワード入力用モーダル
class KeywordModal(discord.ui.Modal):
    def __init__(self, target_type, target_obj):
        super().__init__(title="キーワード検索")
        self.target_type = target_type  # 'category' or 'channel'
        self.target_obj = target_obj    # CategoryChannel or TextChannel

        self.keyword_input = discord.ui.TextInput(
            label="検索キーワード",
            placeholder="検索したい言葉を入力してください",
            required=True,
            max_length=100
        )
        self.add_item(self.keyword_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        keyword = self.keyword_input.value

        if self.target_type == 'category':
            channels = self.target_obj.text_channels
            target_name = f"カテゴリー: {self.target_obj.name}"
        else:
            channels = [self.target_obj]
            target_name = f"チャンネル: #{self.target_obj.name}"

        # メッセージ検索実行
        search_results = await search_in_channels(channels, keyword)

        # 全員が見える形で結果を作成して送信
        embed = discord.Embed(
            title="🔍 検索結果",
            color=discord.Color.blue()
        )
        embed.add_field(name="検索対象", value=target_name, inline=False)
        embed.add_field(name="キーワード", value=keyword, inline=False)

        if search_results:
            embed.description = f"**{len(search_results)}件** ヒットしました。"
            for res in search_results:
                field_title = f"#{res['channel'].name} ({res['created_at']}) - [メッセージへジャンプ]({res['jump_url']})"
                field_value = res['context']
                if len(field_value) > 1000:
                    field_value = field_value[:1000] + "..."
                embed.add_field(name=field_title, value=field_value, inline=False)
        else:
            embed.description = "該当する情報が見つかりませんでした。"

        # 全員が見えるチャンネルに結果を投稿
        await interaction.channel.send(embed=embed)
        await interaction.followup.send("検索結果を出力しました。", ephemeral=True)

# チャンネル選択セレクトボックス
class ChannelSelectView(discord.ui.View):
    def __init__(self, category: discord.CategoryChannel):
        super().__init__(timeout=60)
        options = [
            discord.SelectOption(label=f"#{ch.name}", value=str(ch.id))
            for ch in category.text_channels[:25]
        ]
        if options:
            select = discord.ui.Select(placeholder="検索したいチャンネルを選択してください", options=options)
            select.callback = self.select_callback
            self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        channel_id = int(interaction.data['values'][0])
        channel = interaction.guild.get_channel(channel_id)
        await interaction.response.send_modal(KeywordModal(target_type='channel', target_obj=channel))

# カテゴリー選択セレクトボックス
class CategorySelectView(discord.ui.View):
    def __init__(self, categories, search_mode):
        super().__init__(timeout=60)
        self.search_mode = search_mode  # 'category' or 'channel'
        options = [
            discord.SelectOption(label=cat.name, value=str(cat.id))
            for cat in categories[:25]
        ]
        if options:
            select = discord.ui.Select(placeholder="検索したいカテゴリーを選択してください", options=options)
            select.callback = self.select_callback
            self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        category_id = int(interaction.data['values'][0])
        category = interaction.guild.get_channel(category_id)

        if self.search_mode == 'category':
            await interaction.response.send_modal(KeywordModal(target_type='category', target_obj=category))
        else:
            if not category.text_channels:
                await interaction.response.send_message("このカテゴリーにはテキストチャンネルがありません。", ephemeral=True)
                return
            await interaction.response.send_message(
                "検索したいチャンネルを選択してください:",
                view=ChannelSelectView(category),
                ephemeral=True
            )

# メイン選択ビュー（ボタン2つ）
class SearchTypeView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=60)
        self.guild = guild

    @discord.ui.button(label="カテゴリーで検索", style=discord.ButtonStyle.primary)
    async def category_search(self, interaction: discord.Interaction, button: discord.ui.Button):
        categories = self.guild.categories
        if not categories:
            await interaction.response.send_message("カテゴリーが存在しません。", ephemeral=True)
            return
        await interaction.response.send_message(
            "検索したいカテゴリーを選択してください:",
            view=CategorySelectView(categories, search_mode='category'),
            ephemeral=True
        )

    @discord.ui.button(label="チャンネルごとに検索", style=discord.ButtonStyle.secondary)
    async def channel_search(self, interaction: discord.Interaction, button: discord.ui.Button):
        categories = self.guild.categories
        if not categories:
            await interaction.response.send_message("カテゴリーが存在しません。", ephemeral=True)
            return
        await interaction.response.send_message(
            "検索したいチャンネルが含まれるカテゴリーを選択してください:",
            view=CategorySelectView(categories, search_mode='channel'),
            ephemeral=True
        )

# --- イベント・コマンド ---

@bot.event
async def on_ready():
    print(f'ログイン成功: {bot.user.name}')
    try:
        synced = await bot.tree.sync()
        print(f"スラッシュコマンドを同期しました: {len(synced)} 件")
    except Exception as e:
        print(f"コマンド同期エラー: {e}")

@bot.tree.command(name="検索", description="サーバー内のログ・資料を検索します")
async def slash_search(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📂 過去ログ・資料検索システム",
        description="下のボタンを押すと、検索条件を選択できます。",
        color=discord.Color.blue()
    )
    # ephemeral=False に変更し、全員に見える形でメッセージを表示
    await interaction.response.send_message(embed=embed, view=SearchTypeView(interaction.guild), ephemeral=False)

if TOKEN:
    bot.run(TOKEN)
