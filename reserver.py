import os, sys, time, requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BASE = "https://allresto.moneweb.fr"
API = BASE + "/client/api/reservation"
PARIS = ZoneInfo("Europe/Paris")

PLATS  = [3446, 4762, 3444, 4484, 3461, 3562, 5282, 5122]
PERIPH = [3475, 3470, 3467, 3473, 3469, 3482, 3468, 3474, 3472, 3466]  # donuts d'abord

DUREE_ESSAIS = timedelta(minutes=10)   # on réessaie pendant 10 min après la cible


def maintenant():
    return datetime.now(PARIS)


# Lancé la veille au soir (22h-minuit) : on attend minuit pile.
# Lancé dans la nuit ou le matin (0h-10h) : on réserve tout de suite.
now = maintenant()
print("Heure Paris :", now)
if now.hour >= 22:
    cible = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
elif now.hour < 10:
    cible = now
else:
    print("Hors fenêtre (22h-10h), on ne fait rien.")
    sys.exit(0)

if cible.weekday() >= 5:
    print("Samedi/dimanche, on ne fait rien.")
    sys.exit(0)

USER, PASS = os.environ["MW_USER"], os.environ["MW_PASS"]
date_cible = cible.strftime("%d/%m/%Y")
limite = cible + DUREE_ESSAIS

attente = (cible - now).total_seconds()
if attente > 0:
    print(f"Attente de minuit ({attente / 60:.0f} min)...")
    time.sleep(attente)


class Echec(Exception):
    pass


class Complet(Echec):
    pass


def check(r, etape):
    print(f"[{etape}] {r.status_code} {r.text[:500]}")
    if r.status_code >= 400:
        if "nombre maximal" in r.text and date_cible in r.text:
            raise Complet(f"plus de place pour le {date_cible}")
        raise Echec(f"{etape}: {r.status_code}")
    return r


def reserver():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Origin": BASE, "Referer": BASE + "/clients",
        "X-Jes-Accept-Notification": "1",
    })

    # Connexion
    s.get(BASE + "/clients")
    check(s.post(BASE + "/clients/api/sign/in", json={
        "ID": USER, "Password": PASS, "RememberMe": True}), "connexion")

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
        raise Echec("Aucun produit disponible parmi " + str(prefs))

    plat = choisir(PLATS)
    p2 = choisir(PERIPH)
    p3 = choisir([3470] + PERIPH, deja=(p2,))   # jus de pomme d'abord
    print("Choix :", plat, p2, p3)

    # Menu
    menu = check(s.post(f"{API}/{resa}/menu", json={"id": 81, "quantity": 1}), "menu").json()["Id"]

    def ligne(j):
        return j["line"]["ProductLines"][-1]["Id"]

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


essai = 0
while True:
    essai += 1
    print(f"--- Essai {essai} ({maintenant():%H:%M:%S}) ---")
    try:
        reserver()
        print("Terminé.")
        sys.exit(0)
    except Complet as e:
        print("Abandon :", e)
        sys.exit(1)
    except (Echec, requests.RequestException, KeyError, IndexError, ValueError) as e:
        print("Échec :", e)
    if maintenant() > limite:
        print("Abandon : limite de temps atteinte.")
        sys.exit(1)
    # Essais rapprochés les 2 premières minutes, puis espacés :
    # chaque essai raté laisse une commande « en cours » sur le site.
    time.sleep(3 if maintenant() - cible < timedelta(minutes=2) else 30)
