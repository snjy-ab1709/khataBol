"""
Bolo Khata — Voice-first credit ledger for India's 60M+ kirana shops.
Speak in any Indian language -> structured ledger -> ask questions by voice ->
send udhaar reminders as voice notes in the CUSTOMER's language.

Sarvam stack: Saaras v4 (STT) + Sarvam-105B (understanding/generation) + Bulbul v3 (TTS)
Design principle: LLM for language, Python for money math (no hallucinated balances).
"""
import base64, json, os, re, uuid, urllib.parse
from datetime import datetime, date

import pandas as pd
import requests
import streamlit as st

API = "https://api.sarvam.ai"
DB_FILE = "khata.json"

LANGS = {
    "हिन्दी (Hindi)": "hi-IN", "বাংলা (Bengali)": "bn-IN", "English": "en-IN",
    "தமிழ் (Tamil)": "ta-IN", "తెలుగు (Telugu)": "te-IN", "ಕನ್ನಡ (Kannada)": "kn-IN",
    "മലയാളം (Malayalam)": "ml-IN", "मराठी (Marathi)": "mr-IN", "ગુજરાતી (Gujarati)": "gu-IN",
    "ਪੰਜਾਬੀ (Punjabi)": "pa-IN", "ଓଡ଼ିଆ (Odia)": "od-IN",
}
TTS_OK = set(LANGS.values())
LANG_NAME = {v: k.split("(")[-1].rstrip(")") if "(" in k else k for k, v in LANGS.items()}

st.set_page_config(page_title="Bolo Khata", page_icon="📒", layout="wide")

# ---------------------------------------------------------------- storage
SEED = [
    {"customer": "Ramesh", "type": "credit", "item": "rice 5 kg", "amount": 300, "lang": "hi-IN"},
    {"customer": "Ramesh", "type": "payment", "item": "", "amount": 100, "lang": "hi-IN"},
    {"customer": "Sunita", "type": "credit", "item": "oil + sugar", "amount": 450, "lang": "bn-IN"},
    {"customer": "Murugan", "type": "credit", "item": "atta 10 kg", "amount": 520, "lang": "ta-IN"},
    {"customer": "Walk-in", "type": "sale", "item": "biscuits", "amount": 60, "lang": "hi-IN"},
]


def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, encoding="utf-8") as f:
            return json.load(f)
    db = []
    for s in SEED:
        db.append({**s, "id": uuid.uuid4().hex[:8], "ts": datetime.now().isoformat(timespec="seconds"),
                   "source": "seed"})
    save_db(db)
    return db


def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=1)


if "db" not in st.session_state:
    st.session_state.db = load_db()


def balances(db):
    """Deterministic money math — never delegated to the LLM."""
    out = {}
    for t in db:
        c = t["customer"].strip().title()
        if c.lower() in ("walk-in", "walkin", ""):
            continue
        b = out.setdefault(c, {"due": 0.0, "lang": t.get("lang", "hi-IN")})
        if t["type"] == "credit":
            b["due"] += float(t["amount"])
        elif t["type"] == "payment":
            b["due"] -= float(t["amount"])
        if t.get("lang"):
            b["lang"] = t["lang"]
    return out


# ---------------------------------------------------------------- Sarvam APIs
def key():
    k = (st.session_state.get("api_key") or os.getenv("SARVAM_API_KEY", "")).strip()
    if not k:
        st.error("Add your Sarvam API key in the sidebar first.")
        st.stop()
    return k


def stt(audio_bytes):
    r = requests.post(f"{API}/speech-to-text", headers={"api-subscription-key": key()},
                      files={"file": ("audio.wav", audio_bytes, "audio/wav")},
                      data={"model": "saaras:v4", "language_code": "unknown"}, timeout=60)
    r.raise_for_status()
    j = r.json()
    return j.get("transcript", ""), j.get("language_code") or "hi-IN"


def tts(text, lang):
    lang = lang if lang in TTS_OK else "hi-IN"
    r = requests.post(f"{API}/text-to-speech",
                      headers={"api-subscription-key": key(), "Content-Type": "application/json"},
                      json={"text": text[:2400], "language_code": lang, "model": "bulbul:v3",
                            "speaker": st.session_state.get("voice", "shubh"), "pace": 1.05},
                      timeout=60)
    r.raise_for_status()
    return base64.b64decode("".join(r.json()["audios"]))


def chat(system, user, as_json=False):
    body = {"model": "sarvam-105b", "temperature": 0.2, "reasoning_effort": "low", "max_tokens": 1500,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if as_json:
        body["response_format"] = {"type": "json_object"}
    h = {"api-subscription-key": key(), "Authorization": f"Bearer {key()}", "Content-Type": "application/json"}
    r = requests.post(f"{API}/v1/chat/completions", headers=h, json=body, timeout=90)
    if r.status_code >= 400 and as_json:  # fallback if JSON mode is rejected
        body.pop("response_format")
        r = requests.post(f"{API}/v1/chat/completions", headers=h, json=body, timeout=90)
    r.raise_for_status()
    txt = r.json()["choices"][0]["message"].get("content") or ""
    return re.sub(r"<think>.*?</think>", "", txt, flags=re.S).strip()


def parse_json(txt):
    m = re.search(r"\{.*\}", txt, flags=re.S)
    return json.loads(m.group(0)) if m else {}


EXTRACT_SYS = """You are the brain of 'Bolo Khata', a ledger for Indian kirana shopkeepers.
The shopkeeper speaks casually, often code-mixed (Hinglish, Benglish, Tanglish), and may describe
several transactions in one sentence. Extract EVERY transaction.

Return ONLY JSON: {"transactions":[{"customer": str, "type": "credit"|"payment"|"sale",
"item": str, "amount": number}], "confirmation": str}

Rules:
- "credit" = customer took goods on udhaar / baaki / khata / "likh lo" / "baad mein dega".
- "payment" = customer paid back / jama kiya / de gaya / returned money.
- "sale" = cash sale, paid immediately. Use customer "Walk-in" if no name.
- customer: the person's name in Latin script, Title Case (e.g. "Ramesh", "Sunita Di" -> "Sunita").
- amount: rupees as a plain number. If quantity x rate is given, multiply. If no amount, use 0.
- item: short English description, empty for payments.
- confirmation: ONE short friendly sentence in the SAME language & script the shopkeeper used,
  read-back of what you recorded (names + amounts), so they can verify by ear.
- If nothing is a transaction, return {"transactions": [], "confirmation": "<polite ask to repeat>"}."""


def record_transactions(text, lang):
    out = parse_json(chat(EXTRACT_SYS, text, as_json=True))
    txs = out.get("transactions", []) or []
    for t in txs:
        if t.get("type") not in ("credit", "payment", "sale"):
            continue
        st.session_state.db.append({
            "id": uuid.uuid4().hex[:8], "ts": datetime.now().isoformat(timespec="seconds"),
            "customer": str(t.get("customer") or "Walk-in").strip().title(),
            "type": t["type"], "item": t.get("item", ""), "amount": float(t.get("amount") or 0),
            "lang": lang, "source": "voice", "said": text,
        })
    save_db(st.session_state.db)
    return txs, out.get("confirmation", "")


# ---------------------------------------------------------------- UI
with st.sidebar:
    st.markdown("## 📒 Bolo Khata")
    st.caption("Bol ke likho. Bol ke poocho. Bol ke vasool karo.")
    st.text_input("Sarvam API key", type="password", key="api_key",
                  value=os.getenv("SARVAM_API_KEY", ""))
    st.selectbox("Reply voice (Bulbul v3)", ["shubh", "ritu", "priya", "aditya", "kavya", "rahul"], key="voice")
    st.divider()
    st.markdown("**Powered by Sarvam**\n- 🎙️ Saaras v4 — speech → text (22 langs, auto-detect)\n"
                "- 🧠 Sarvam-105B — understands code-mixed speech\n- 🔊 Bulbul v3 — speaks back")
    if st.button("Reset demo data"):
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
        st.session_state.db = load_db()
        st.rerun()

db = st.session_state.db
bal = balances(db)
total_due = sum(max(b["due"], 0) for b in bal.values())
today_sales = sum(t["amount"] for t in db if t["type"] == "sale" and t["ts"][:10] == date.today().isoformat())

st.markdown("# 📒 Bolo Khata — *the khata that listens*")
st.caption("63M kirana shops run on a paper notebook. Typing apps fail them. Speaking doesn't.")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total udhaar outstanding", f"₹{total_due:,.0f}")
c2.metric("Customers with dues", sum(1 for b in bal.values() if b["due"] > 0))
c3.metric("Cash sales today", f"₹{today_sales:,.0f}")
c4.metric("Entries", len(db))

tab1, tab2, tab3, tab4 = st.tabs(["🎙️ Bolo — record", "❓ Poocho — ask", "📲 Yaad dilao — remind", "📊 Khata"])

# ---- Tab 1: record
with tab1:
    st.markdown("Speak naturally, in any language, several entries at once. "
                "_e.g. “Ramesh ne do kilo chini li 90 rupaye, likh lo. Sunita di 200 jama kar gayi.”_")
    a = st.audio_input("Tap to speak", key="rec_audio")
    typed = st.text_input("…or type (fallback)", key="rec_text")
    if st.button("Add to khata", type="primary", key="rec_btn") and (a or typed):
        with st.status("Listening & understanding…", expanded=True) as s:
            if a:
                text, lang = stt(a.getvalue())
                st.write(f"🎙️ **Saaras heard** ({LANG_NAME.get(lang, lang)}): {text}")
            else:
                text, lang = typed, st.session_state.get("typed_lang", "hi-IN")
            txs, conf = record_transactions(text, lang)
            st.write("🧠 **Sarvam-105B extracted:**")
            if txs:
                st.dataframe(pd.DataFrame(txs), hide_index=True, width='stretch')
            s.update(label=f"Recorded {len(txs)} entr{'y' if len(txs) == 1 else 'ies'}", state="complete")
        if conf:
            st.success(conf)
            st.audio(tts(conf, lang), format="audio/wav", autoplay=True)
        st.caption("Balances are computed by code, not the model — so the money is always right.")

# ---- Tab 2: ask
with tab2:
    st.markdown("Ask anything about the khata, by voice. _e.g. “Sabse zyada udhaar kiska hai?” · "
                "“Ramesh ka kitna baaki hai?” · “আজ কত বিক্রি হলো?”_")
    qa = st.audio_input("Ask by voice", key="ask_audio")
    qt = st.text_input("…or type", key="ask_text")
    if st.button("Ask", type="primary", key="ask_btn") and (qa or qt):
        if qa:
            q, lang = stt(qa.getvalue())
            st.write(f"🎙️ You asked: **{q}**")
        else:
            q, lang = qt, "hi-IN"
        facts = {
            "balances_due_by_customer_rupees": {c: round(b["due"]) for c, b in bal.items()},
            "total_outstanding_rupees": round(total_due),
            "cash_sales_today_rupees": round(today_sales),
            "recent_entries": [{k: t[k] for k in ("ts", "customer", "type", "item", "amount")} for t in db[-25:]],
            "today": date.today().isoformat(),
        }
        sys = ("You are a helpful munim (shop accountant). Answer the shopkeeper's question using ONLY the facts "
               "JSON. Never invent numbers. Reply in 1-3 short spoken-style sentences, in the SAME language and "
               "script as the question. Write amounts like '₹1,250'.")
        ans = chat(sys, f"FACTS:\n{json.dumps(facts, ensure_ascii=False)}\n\nQUESTION: {q}")
        st.info(ans)
        st.audio(tts(ans, lang), format="audio/wav", autoplay=True)

# ---- Tab 3: remind
with tab3:
    debtors = {c: b for c, b in bal.items() if b["due"] > 0}
    if not debtors:
        st.success("No pending udhaar 🎉")
    else:
        st.markdown("The shopkeeper speaks Hindi — but Sunita speaks Bengali and Murugan speaks Tamil. "
                    "Bolo Khata sends each customer a **polite voice-note reminder in their own language**.")
        cc1, cc2, cc3 = st.columns([2, 2, 2])
        cust = cc1.selectbox("Customer", sorted(debtors, key=lambda c: -debtors[c]["due"]),
                             format_func=lambda c: f"{c} — ₹{debtors[c]['due']:,.0f}")
        default_lang = debtors[cust]["lang"]
        names = list(LANGS)
        idx = list(LANGS.values()).index(default_lang) if default_lang in LANGS.values() else 0
        lname = cc2.selectbox("Customer's language", names, index=idx)
        tone = cc3.selectbox("Tone", ["Warm & friendly", "Gentle festive (Diwali offer)", "Firm but polite"])
        shop = st.text_input("Shop name", "Maa Durga General Store")
        if st.button("Generate voice reminder", type="primary"):
            lang = LANGS[lname]
            sys = ("You write WhatsApp payment reminders from a neighbourhood kirana shop to a regular customer. "
                   "Preserve the relationship: respectful, warm, never shaming. 2-3 short sentences, suitable to "
                   f"be read aloud. Write ONLY in {lname.split('(')[-1].rstrip(')')} using its native script. "
                   "Include the exact amount and shop name. Offer UPI or paying on next visit.")
            msg = chat(sys, f"Customer: {cust}. Amount due: ₹{debtors[cust]['due']:,.0f}. Shop: {shop}. Tone: {tone}.")
            st.text_area("Reminder text", msg, height=120)
            audio = tts(msg, lang)
            st.audio(audio, format="audio/wav")
            d1, d2 = st.columns(2)
            d1.download_button("⬇️ Download voice note", audio, file_name=f"reminder_{cust}.wav", mime="audio/wav")
            d2.link_button("💬 Open in WhatsApp", "https://wa.me/?text=" + urllib.parse.quote(msg))

# ---- Tab 4: ledger
with tab4:
    if bal:
        bdf = pd.DataFrame([{"Customer": c, "Due (₹)": round(b["due"]), "Language": LANG_NAME.get(b["lang"], b["lang"])}
                            for c, b in bal.items()]).sort_values("Due (₹)", ascending=False)
        l, r = st.columns([1, 1])
        l.markdown("#### Balances")
        l.dataframe(bdf, hide_index=True, width='stretch')
        r.markdown("#### Who owes most")
        r.bar_chart(bdf.set_index("Customer")["Due (₹)"])
    st.markdown("#### All entries (audit trail — every voice entry keeps what was said)")
    df = pd.DataFrame(db)
    cols = [c for c in ["ts", "customer", "type", "item", "amount", "source", "said"] if c in df.columns]
    st.dataframe(df[cols].iloc[::-1], hide_index=True, width='stretch')
    st.download_button("⬇️ Export CSV (for GST / bank loan)", df[cols].to_csv(index=False).encode(),
                       "khata.csv", "text/csv")
