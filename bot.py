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

# 表記揺れ（カタカナ ➔ 英語名）変換辞書
ALIAS_MAP = {
    "デベステ": "Deveste",
    "デベステエイト": "Deveste Eight",
    "タイラス": "Tyrus",
    "ゼントーノ": "Zentorno",
    "クライガー": "Krieger",
    "ネロ": "Nero",
    "イグナス": "Ignus",
    "テゼロクト": "Tezeract",
    "プロト": "X80 Proto",
    # 必要に応じて追加してください
}

RULE_PAGES = [
    "https://null404-rules.pages.dev/01-support.html",
    "https://null404-rules.pages.dev/02-general.html",
    "https://null404-rules.pages.dev/03-vehicle.html",
    "https://null404-rules.pages.dev/04-job.html",
    "https://null404-rules.pages.dev/05-crime.html",
    "https://null404-rules.pages.dev/06-gang.html",
]

# ブラウザ偽装用セッション
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
})

# キーワード整形（エイリアス変換）
def convert_query(raw_query):
    query = raw_query.strip()
    for alias, official_name in ALIAS_MAP.items():
        if alias.lower() in query.lower():
            return query.lower().replace(alias.lower(), official_name), official_name
    return query, query

# ---------------------------------------------------------
# Web・スプレッドシート検索用ロジック
# ---------------------------------------------------------
def search_rules_site(query):
    matches = []
    clean_query = query.lower().replace(" ", "")
    for url in RULE_PAGES:
        try:
            res = session.get(url, timeout=5)
            if res.status_code != 200 or "cf-error-details" in res.text:
                continue
            res.encoding = res.apparent_encoding
            soup = BeautifulSoup(res.text, 'html.parser')
            for element in soup.find_all(['tr', 'p', 'li', 'h1', 'h2', 'h3']):
                text = element.get_text(separator=' | ').strip()
                text_single_line = " ".join(text.split())
                if text_single_line and clean_query in text_single_line.lower().replace(" ", ""):
                    if text_single_line not in matches:
                        matches.append(text_single_line)
                        if len(matches) >= 3:
                            return matches
        except Exception:
            continue
    return matches

def search_spreadsheet(query):
    url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSERXdms_ZOSdihgcdlJNm-NneQRlydiThyBxmRbqyhUkIA8PYzE9lYuFVfFZV85wKn921LR0L47bPG/pub?output=csv"
    matches = []
    clean_query = query.lower().replace(" ", "")
    try:
        res = session.get(url, timeout=5)
        if res.status_code != 200:
            return []
        res.encoding = 'utf-8'
        csv_file = io.StringIO(res.text)
        reader = csv.reader(csv_file)
        for row in reader:
            cells = [cell.strip() for cell in row if cell.strip()]
            if not cells:
                continue
            row_text = " | ".join(cells)
            if clean_query in row_text.lower().replace(" ", ""):
                if row_text not in matches:
                    matches.append(row_text)
                    if len(matches) >= 3:
                        break
        return matches
    except Exception:
        return []

# ---------------------------------------------------------
# サーバー内ログ・フォーラム検索用ロジック
# ---------------------------------------------------------
async def search_in_channels(channels, keyword, limit_per_channel=100):
    results = []
    clean_keyword = keyword.lower().replace(" ", "")

    for channel in channels:
        # フォーラム（スレッド一覧）と通常テキストチャンネルの両方に対応
        target_threads_or_channels = []
        if isinstance(channel, discord.ForumChannel):
            target_threads_or_channels.extend(channel.threads)
            # 非アクティブなスレッドも取得
            async for thread in channel.archived_threads(limit=20):
                target_threads_or_channels.append(thread)
        elif isinstance(channel, discord.TextChannel):
            target_threads_or_channels.append(channel)

        for target in target_threads_or_channels:
            try:
                messages = [msg async for msg in target.history(limit=limit_per_channel)]
                for msg in messages:
                    if not msg.content:
                        continue
                    
                    # 行ごとに検索して、最も合致する行を抽出
                    lines = msg.content.split('\n')
                    matched_lines = [line.strip() for line in lines if clean_keyword in line.lower().replace(" ", "")]

                    if matched_lines:
                        results.append({
                            "channel_name": target.name,
                            "hit_line": matched_lines[0], # 最も近い1行を抽出
                            "jump_url": msg.jump_url,
                            "created_at": msg.created_at.strftime("%Y/%m/%d %H:%M")
                        })
                        if len(results) >= 5:
                            return results
            except discord.Forbidden:
                continue
            except Exception:
                continue

    return results

# ---------------------------------------------------------
# UI (モーダル & ビュー)
# ---------------------------------------------------------
class KeywordModal(discord.ui.Modal):
    def __init__(self, target_type, target_obj):
        super().__init__(title="キーワード検索")
        self.target_type = target_type
        self.target_obj = target_obj

        self.keyword_input = discord.ui.TextInput(
            label="検索キーワード (例: デベステ / Deveste)",
            placeholder="キーワードを入力してください",
            required=True,
            max_length=100
        )
        self.add_item(self.keyword_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        raw_keyword = self.keyword_input.value
        search_query, official_name = convert_query(raw_keyword)

        if self.target_type == 'category':
            channels = self.target_obj.channels
            target_name = f"カテゴリー: {self.target_obj.name}"
        else:
            channels = [self.target_obj]
            target_name = f"チャンネル/フォーラム: #{self.target_obj.name}"

        # サーバー内ログから検索
        search_results = await search_in_channels(channels, search_query)
        if not search_results and search_query != raw_keyword:
            search_results = await search_in_channels(channels, raw_keyword)

        embed = discord.Embed(title="🔍 車両・ログ検索結果", color=discord.Color.green())
        embed.add_field(name="検索対象", value=target_name, inline=True)
        embed.add_field(name="入力キーワード", value=f"{raw_keyword} (⇒ {official_name})", inline=True)

        if search_results:
            embed.description = f"**{len(search_results)}件** ヒットしました。"
            for res in search_results:
                field_title = f"📍 #{res['channel_name']} ({res['created_at']})"
                field_value = f"**{res['hit_line']}**\n👉 [メッセージヘジャンプ]({res['jump_url']})"
                embed.add_field(name=field_title, value=field_value, inline=False)
        else:
            embed.description = "該当する車両またはテキストが見つかりませんでした。"

        await interaction.channel.send(embed=embed)
        await interaction.followup.send("検索結果を送信しました。", ephemeral=True)

class ChannelSelectView(discord.ui.View):
    def __init__(self, category: discord.CategoryChannel):
        super().__init__(timeout=60)
        options = [
            discord.SelectOption(label=f"#{ch.name}", value=str(ch.id))
            for ch in category.channels[:25]
        ]
        if options:
            select = discord.ui.Select(placeholder="チャンネルを選択してください", options=options)
            select.callback = self.select_callback
            self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        channel_id = int(interaction.data['values'][0])
        channel = interaction.guild.get_channel(channel_id)
        await interaction.response.send_modal(KeywordModal(target_type='channel', target_obj=channel))

class CategorySelectView(discord.ui.View):
    def __init__(self, categories, search_mode):
        super().__init__(timeout=60)
        self.search_mode = search_mode
        options = [
            discord.SelectOption(label=cat.name, value=str(cat.id))
            for cat in categories[:25]
        ]
        if options:
            select = discord.ui.Select(placeholder="カテゴリーを選択してください", options=options)
            select.callback = self.select_callback
            self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        category_id = int(interaction.data['values'][0])
        category = interaction.guild.get_channel(category_id)

        if self.search_mode == 'category':
            await interaction.response.send_modal(KeywordModal(target_type='category', target_obj=category))
        else:
            await interaction.response.send_message(
                "検索したいチャンネルを選択してください:",
                view=ChannelSelectView(category),
                ephemeral=True
            )

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

    @discord.ui.button(label="チャンネル/フォーラムごとに検索", style=discord.ButtonStyle.secondary)
    async def channel_search(self, interaction: discord.Interaction, button: discord.ui.Button):
        categories = self.guild.categories
        if not categories:
            await interaction.response.send_message("カテゴリーが存在しません。", ephemeral=True)
            return
        await interaction.response.send_message(
            "対象チャンネルが含まれるカテゴリーを選択してください:",
            view=CategorySelectView(categories, search_mode='channel'),
            ephemeral=True
        )

# ---------------------------------------------------------
# イベント & コマンド
# ---------------------------------------------------------
@bot.event
async def on_ready():
    print(f'ログイン成功: {bot.user.name}')
    try:
        synced = await bot.tree.sync()
        print(f"スラッシュコマンドを同期しました: {len(synced)} 件")
    except Exception as e:
        print(f"コマンド同期エラー: {e}")

@bot.tree.command(name="検索", description="サーバー内の車一覧ログや資料を検索します")
async def slash_search(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📂 過去ログ・車両情報検索システム",
        description="下のボタンを押すと、カテゴリーやチャンネルを指定して検索できます。",
        color=discord.Color.blue()
    )
    # パネル本体は全員に見える形（ephemeral=False）で表示
    await interaction.response.send_message(embed=embed, view=SearchTypeView(interaction.guild), ephemeral=False)

if TOKEN:
    bot.run(TOKEN)
