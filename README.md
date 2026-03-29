# Bags Stock ERP — README

## Yeh Software Kya Karta Hai?

Bags Stock ERP aapke liye ek complete stock management system hai jo in kamon ke liye banaya gaya hai:

- **Lots manage karna** — Har incoming stock ka lot register karo
- **Stock entry** — Different weight bags add karo (25kg, 24.5kg, 20kg, 50kg, 49kg, 40kg)
- **Weight Adjustment** — Lot ke bags ka weight kam karo (jaise 25kg → 24.5kg)
- **Reports** — Complete weight aur quantity reports

---

## Software Chalane Ka Tarika

### Zaroorat:
- Python 3.8 ya usse upar

### Steps:
1. `start.bat` pe double-click karo
2. Automatically packages install ho jaenge
3. Browser mein kholo: **http://localhost:5000**

---

## Features

| Module | Kya Karta Hai |
|--------|---------------|
| **Dashboard** | Total bags, weight, lots ka overview + charts |
| **Lots** | Lot add karo, supplier ka naam, date |
| **Stock Entry** | Bags add karo — lot ke saath, weight, quantity |
| **Weight Adjustment** | 100 bags 25kg se 24.5kg karo — system khud calculate karta hai |
| **Reports** | Category-wise aur lot-wise complete report, print bhi kar saktey ho |

---

## Weight Adjustment Kaise Kaam Karta Hai?

Aksar ata hai k **25kg ka lot** aata hai, phir **100 bags ka weight 24.5kg kar detey hain**.

1. `Weight Adjustments → New Adjustment` pe jao
2. Stock entry select karo
3. Kitne bags adjust karne hain (e.g. 100)
4. Naya weight daalo (e.g. 24.5)
5. Save karo — System automatically:
   - Agar sarey bags adjust: entry update ho jati hai
   - Agar kuch bags: entry doh mein split ho jati hai automatically

---

*Developed for Bags Stock Management — 2026*
