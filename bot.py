import os
import json
import asyncio
import threading
import requests
import discord
from discord import app_commands
from discord.ext import tasks
from flask import Flask

TOKEN = os.getenv("DISCORD_TOKEN")
BASE = "https://www.vinted.fr"
API = f"{BASE}/api/v2/catalog/items"
ALERTS_FILE = "alertes.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


# ---------- Sauvegarde des alertes ----------
def load_alertes():
    try:
        with open(ALERTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_alertes():
    try:
        with open(ALERTS_FILE, "w", encoding="utf-8") as f:
            json.dump(alertes, f)
    except Exception as e:
        print(f"Erreur sauvegarde: {e}")


alertes = load_alertes()

# ---------- Vinted ----------
_session = None
_lock = threading.Lock()


def _new_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    r = s.get(BASE, timeout=15)
    print(f"Init session Vinted: {r.status_code}")
    return s


def _search_sync(marque, categorie, prix_max):
    global _session
    params = {
        "search_text": f"{marque} {categorie}",
        "order": "newest_first",
        "per_page": "10",
    }
    if prix_max:
        params["price_to"] = prix_max

    with _lock:
        for attempt in range(2):
            try:
                if _session is None:
                    _session = _new_session()
                r = _session.get(
                    API,
                    params=params,
                    headers={"Accept": "application/json, text/plain, */*"},
                    timeout=15,
                )
                if r.status_code in (401, 403):
                    print(f"Vinted a répondu {r.status_code}, je renouvelle la session")
                    _session = None
                    continue
                if r.status_code != 200:
                    print(f"Vinted a répondu {r.status_code}: {r.text[:200]}")
                    return []
                return r.json().get("items", [])
            except Exception as e:
                print(f"Erreur search (essai {attempt + 1}): {e}")
                _session = None
        return []


async def search_vinted(marque, categorie, prix_max):
    return await asyncio.to_thread(_search_sync, marque, categorie, prix_max)


def build_embed(it):
    iid = str(it.get("id"))
    price = it.get("price")
    if isinstance(price, dict):
        price = price.get("amount", "?")
    embed = discord.Embed(
        title=it.get("title", "Nouvel article"),
        url=it.get("url") or f"{BASE}/items/{iid}",
        color=0x09B1BA,
    )
    embed.add_field(name="Prix", value=f"{price or '?'}€")
    if it.get("brand_title"):
        embed.add_field(name="Marque", value=it["brand_title"])
    if it.get("size_title"):
        embed.add_field(name="Taille", value=it["size_title"])
    photo_url = None
    if isinstance(it.get("photo"), dict):
        photo_url = it["photo"].get("url")
    if not photo_url and it.get("photos"):
        photo_url = it["photos"][0].get("url")
    if photo_url:
        embed.set_image(url=photo_url)
    return embed


# ---------- Commandes ----------
@tree.command(name="alerte", description="Créer une alerte Vinted")
async def alerte(interaction: discord.Interaction, marque: str, categorie: str, prix_max: int):
    await interaction.response.defer(ephemeral=True)

    items = await search_vinted(marque, categorie, prix_max)

    uid = str(interaction.user.id)
    alertes.setdefault(uid, []).append({
        "marque": marque,
        "categorie": categorie,
        "prix_max": prix_max,
        "seen": [str(it.get("id")) for it in items],
    })
    save_alertes()

    await interaction.followup.send(
        f"✅ Alerte **{marque} {categorie} max {prix_max}€** activée !", ephemeral=True
    )

    try:
        if items:
            await interaction.user.send(
                content=f"Dernier article actuel pour **{marque} {categorie}** :",
                embed=build_embed(items[0]),
            )
        else:
            await interaction.user.send(
                f"Aucun résultat pour {marque} {categorie} (ou Vinted bloque le bot). "
                f"Tape /debug_vinted pour voir."
            )
    except discord.Forbidden:
        await interaction.followup.send(
            "❌ Je ne peux pas t'envoyer de MP. Autorise les messages privés.",
            ephemeral=True,
        )


@tree.command(name="mes_alertes", description="Voir tes alertes")
async def mes_alertes(interaction: discord.Interaction):
    lst = alertes.get(str(interaction.user.id), [])
    if not lst:
        await interaction.response.send_message("Aucune alerte.", ephemeral=True)
        return
    txt = "\n".join(
        f"**{i}.** {a['marque']} {a['categorie']} (max {a['prix_max']}€)"
        for i, a in enumerate(lst, 1)
    )
    await interaction.response.send_message(txt, ephemeral=True)


@tree.command(name="supprimer_alerte", description="Supprimer une alerte (numéro de /mes_alertes)")
async def supprimer_alerte(interaction: discord.Interaction, numero: int):
    lst = alertes.get(str(interaction.user.id), [])
    if 1 <= numero <= len(lst):
        a = lst.pop(numero - 1)
        save_alertes()
        await interaction.response.send_message(
            f"🗑️ Alerte {a['marque']} {a['categorie']} supprimée.", ephemeral=True
        )
    else:
        await interaction.response.send_message("Numéro invalide.", ephemeral=True)


@tree.command(name="test_dm", description="Test si DM OK")
async def test_dm(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        await interaction.user.send("✅ DM OK ! Bot opérationnel")
        await interaction.followup.send("✅ DM envoyé, regarde tes MP !", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send(
            "❌ Ouvre tes DM Discord ! Clic droit sur le serveur > Paramètres de "
            "confidentialité > Autoriser les MP",
            ephemeral=True,
        )


@tree.command(name="debug_vinted", description="Teste la connexion à Vinted")
async def debug_vinted(interaction: discord.Interaction, recherche: str = "nike"):
    await interaction.response.defer(ephemeral=True)

    def _test():
        s = requests.Session()
        s.headers.update(HEADERS)
        r1 = s.get(BASE, timeout=15)
        cookies = list(s.cookies.keys())
        r2 = s.get(
            API,
            params={"search_text": recherche, "per_page": "5"},
            headers={"Accept": "application/json, text/plain, */*"},
            timeout=15,
        )
        return r1.status_code, cookies, r2.status_code, r2.text[:300]

    try:
        s1, cookies, s2, body = await asyncio.to_thread(_test)
        await interaction.followup.send(
            f"Accueil : **{s1}**\nCookies : {cookies}\nAPI : **{s2}**\n```{body}```",
            ephemeral=True,
        )
    except Exception as e:
        await interaction.followup.send(f"Erreur : {e}", ephemeral=True)


# ---------- Boucle de vérification ----------
@tasks.loop(minutes=2)
async def check_loop():
    try:
        for uid, lst in list(alertes.items()):
            try:
                user = await client.fetch_user(int(uid))
            except Exception:
                continue
            for al in lst:
                items = await search_vinted(al["marque"], al["categorie"], al["prix_max"])
                new_items = [it for it in items if str(it.get("id")) not in al["seen"]]
                for it in reversed(new_items):
                    al["seen"].append(str(it.get("id")))
                    try:
                        await user.send(embed=build_embed(it))
                    except Exception as e:
                        print(f"Erreur DM: {e}")
                al["seen"] = al["seen"][-200:]
                await asyncio.sleep(2)
        save_alertes()
    except Exception as e:
        print(f"Erreur check_loop: {e}")


# ---------- Test au démarrage (résultat dans les logs) ----------
def startup_test():
    try:
        s = requests.Session()
        s.headers.update(HEADERS)
        r1 = s.get(BASE, timeout=15)
        r2 = s.get(
            API,
            params={"search_text": "nike", "per_page": "5"},
            headers={"Accept": "application/json, text/plain, */*"},
            timeout=15,
        )
        print(f"[TEST VINTED] Accueil={r1.status_code} cookies={list(s.cookies.keys())} "
              f"API={r2.status_code} body={r2.text[:300]}")
    except Exception as e:
        print(f"[TEST VINTED] erreur: {e}")


@client.event
async def on_ready():
    synced = await tree.sync()
    print(f"{len(synced)} commandes synchronisées : {[c.name for c in synced]}")
    await asyncio.to_thread(startup_test)
    if not check_loop.is_running():
        check_loop.start()
    print("VERSION 2 OK")
    print(f"Connecté {client.user}")


# ---------- Mini serveur web (pour Render / UptimeRobot) ----------
app = Flask(__name__)


@app.route("/")
def home():
    return "Bot OK"


threading.Thread(
    target=lambda: app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000))),
    daemon=True,
).start()

client.run(TOKEN)
