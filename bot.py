from flask import Flask
import threading
import discord
from discord import app_commands
import requests, json, os
from discord.ext import tasks

TOKEN = os.getenv("DISCORD_TOKEN")
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
alertes = {}

def search_vinted(marque, categorie, prix_max):
    try:
        r_init = requests.get("https://www.vinted.fr/", headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        cookie = r_init.cookies.get("_vinted_fr_session")
        url = "https://www.vinted.fr/api/v2/catalog/items"
        params = {"search_text": f"{marque} {categorie}", "order": "newest_first", "per_page": "10", "price_to": prix_max or ""}
        r = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, cookies={"_vinted_fr_session": cookie} if cookie else {}, timeout=10)
        return r.json().get("items", [])
    except: return []

@tree.command(name="alerte", description="Créer une alerte Vinted")
async def alerte(interaction: discord.Interaction, marque: str, categorie: str, prix_max: int):
    uid=str(interaction.user.id)
    if uid not in alertes: alertes[uid]=[]
    alertes[uid].append({"marque": marque, "categorie": categorie, "prix_max": prix_max, "seen": []})
    await interaction.response.send_message(f"✅ Alerte {marque} {categorie} max {prix_max}€ activée, DM toutes les 1min !", ephemeral=True)

@tree.command(name="test_dm", description="Test si DM OK")
async def test_dm(interaction: discord.Interaction):
    try:
        await interaction.user.send("✅ DM OK !")
        await interaction.response.send_message("DM envoyé !", ephemeral=True)
    except:
        await interaction.response.send_message("❌ Ouvre tes DM Discord !", ephemeral=True)

@tasks.loop(minutes=1)
async def check_loop():
    for uid, lst in list(alertes.items()):
        try: user = await client.fetch_user(int(uid))
        except: continue
        for al in lst:
            for it in search_vinted(al["marque"], al["categorie"], al["prix_max"]):
                iid=str(it.get("id"))
                if iid in al["seen"]: continue
                al["seen"].append(iid)
                if len(al["seen"])<=3 and check_loop.current_loop==0: continue
                embed=discord.Embed(title=it.get("title","Nouvel article"), url=f"https://www.vinted.fr/items/{iid}", color=0x09B1BA)
                embed.add_field(name="Prix", value=f"{it.get('price',{}).get('amount','?')}€")
                if it.get("photo",{}).get("url"): embed.set_image(url=it["photo"]["url"])
                try: await user.send(embed=embed)
                except: pass

@client.event
async def on_ready():
    await tree.sync()
    if not check_loop.is_running(): check_loop.start()
    print(f"Connecté {client.user}")
app = Flask('')
@app.route('/')
def home(): return "Bot OK"
threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
client.run(TOKEN)
