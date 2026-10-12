# 📒 Bolo Khata — the khata that listens

**Voice-first credit ledger for India's 63 million kirana shops.**
Bol ke likho. Bol ke poocho. Bol ke vasool karo.

## Problem
Most kirana shops still track udhaar (credit) in a paper notebook. Typing apps fail them: shopkeepers are busy, multitasking, and often more comfortable speaking than typing English. Unrecovered udhaar quietly eats margins, and asking a regular customer for money is socially awkward.

## Solution
1. **Bolo (record):** The shopkeeper speaks naturally, code-mixed, several entries at once: *"Ramesh ne do kilo chini li 90 rupaye, likh lo. Sunita di 200 jama kar gayi."* The entries land in the ledger, and Bulbul reads them back aloud so the shopkeeper can verify by ear.
2. **Poocho (ask):** *"Sabse zyada udhaar kiska hai?"* gets a spoken answer, in the language the question was asked in.
3. **Yaad dilao (remind):** The shopkeeper speaks Hindi, but the customer speaks Bengali or Tamil. Bolo Khata writes a warm, non-shaming reminder **in the customer's language** and turns it into a WhatsApp-ready voice note.
4. **Khata:** Balances, a who-owes-most chart, a full audit trail (each entry keeps what was actually said), and a CSV export that can support GST filing or bank-loan applications.

## Sarvam stack
| Step | Model |
|---|---|
| Speech → text, 22 languages, auto language detection | **Saaras v4** |
| Understanding code-mixed speech, structured extraction, Q&A, reminder writing | **Sarvam-105B** |
| Spoken confirmations, answers, and reminder voice notes | **Bulbul v3** |

**Design principle: the LLM handles language, Python handles money.** Balances are computed deterministically from the ledger, never by the model, so the numbers can't be hallucinated.

## Why it matters
- 63M+ MSMEs, most of them kirana shops; credit runs on trust and paper.
- Voice-first in the shopkeeper's own language; no typing or English required.
- A digital ledger builds a **credit history**, the path to formal loans.

## Roadmap
WhatsApp bot (voice note in, voice note out) · UPI payment links in reminders · auto-reconciliation of UPI credits · feature-phone IVR via Sarvam Voice Agents · lender API for khata-based credit scores.

## Run
```bash
pip install -r requirements.txt
streamlit run app.py
```
Paste your Sarvam API key in the sidebar, or set `SARVAM_API_KEY`.
