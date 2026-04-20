# CONTRACTS – ID CARD MAKER

## DATA CONTRACTS

### Member
{
  name: string
  id_number: string
  date: string (YYYY-MM-DD)
  email: string
}

---

## OUTPUT CONTRACT

Generated Card:
- PNG file
- filename = {id_number}.png
- stored in /generated_cards

---

## API CONTRACT (TARGET)

### POST /preview
Input: Member + template + signature
Output: PNG (base64)

---

### POST /generate
Input: Member
Output: saved PNG

---

### POST /generate-batch
Input: list<Member>
Output: progress + results

---

### POST /email
Input: Member + SMTP config
Output: success/failure

---

## BEHAVIOR CONTRACTS

- ID number is REQUIRED to generate/save/email a card
- Date is optional; if missing or unparseable it is left blank (no default)
- CSV must map to:
  name, id_number, date, email

---

## NON-NEGOTIABLE

- Rendering logic in Python is authoritative
- Angular MUST NOT reimplement rendering
