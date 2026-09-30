import os, sys, requests
from datetime import datetime
from zoneinfo import ZoneInfo

BASE = "https://allresto.moneweb.fr"
API = BASE + "/client/api/reservation"

now = datetime.now(ZoneInfo("Europe/Paris"))
print("Heure Paris :", now)
if not (0 <= now.hour < 10):
    print("Hors fenêtre (00h-10h), on ne fait rien.")
    sys.exit(0)

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": BASE, "Referer": BASE + "/clients",
    "X-Jes-Accept-Notification": "1",
})

def check(r, etape):
    print(f"[{etape}] {r.status_code} {r.text[:500]}")
    if r.status_code >= 400:
        sys.exit(1)
    return r

# Connexion
s.get(BASE + "/clients")
check(s.post(BASE + "/clients/api/sign/in", json={
    "ID": os.environ["MW_USER"], "Password": os.environ["MW_PASS"], "RememberMe": True}), "connexion")

# Réservation
resa = check(s.post(API + "/fr-FR"), "création").json()["Id"]
check(s.put(f"{API}/{resa}/service", json={"service": 21}), "service")
check(s.put(f"{API}/{resa}/delivery-location", json={"deliveryLocation": 21}), "lieu")

# Stock
offer = s.get(f"{API}/{resa}/offer/fr-FR").json()
stock = offer.get("ProductsRemainingQuantity", {})
dispo = lambda pid: stock.get(str(pid), 1) > 0   # absent = pas de limite

def choisir(prefs, deja=()):
    for pid in prefs:
        if pid not in deja and dispo(pid):
            return pid
    sys.exit("Aucun produit disponible parmi " + str(prefs))

PLATS  = [3446, 4762, 3444, 4484, 3461, 3562, 5282, 5122]
PERIPH = [3475, 3470, 3467, 3473, 3469, 3482, 3468, 3474, 3472, 3466]  # donuts d'abord

plat = choisir(PLATS)
p2 = choisir(PERIPH)
p3 = choisir([3470] + PERIPH, deja=(p2,))   # jus de pomme d'abord
print("Choix :", plat, p2, p3)

# Menu
menu = check(s.post(f"{API}/{resa}/menu", json={"id": 81, "quantity": 1}), "menu").json()["Id"]

def ligne(j):
    if isinstance(j, dict):
        if j.get("ProductLines"):
            return j["ProductLines"][-1]["Id"]
        return j["Id"]

lignes = []
for pid, comp, order in [(plat, "2", "1"), (p2, "5", "2"), (p3, "5", "3")]:
    r = check(s.post(f"{API}/{resa}/menu/{menu}/product",
                     json={"id": pid, "component": comp, "order": order}), f"produit {pid}")
    lignes.append((ligne(r.json()), pid))

cle = f"{menu}-81-1(" + "/".join(f"{l}-{p}" for l, p in lignes) + ")"
print("Clé :", cle)

# Validation et paiement
check(s.put(f"{API}/{resa}/validate", json={
    "comment": None, "uniqueKey": cle, "amountPayment": 1,
    "paymentByTransaction": False, "PaymentByAccount": True}), "validation")
check(s.post(f"{API}/{resa}/payment-account-process"), "paiement")
print("Terminé.")