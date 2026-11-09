# SECRETS — kya chahiye, value kahan milegi, kahan dalni hai

Saare secrets yahan dalne hain: repo → **Settings → Secrets and variables → Actions → New repository secret**.
**Koi bhi secret value chat me mat bhejna, code me kabhi mat likhna.** Sirf upar wali jagah par.

Kul 6 secrets hain — 3 Meta ke, 3 YouTube ke. `GITHUB_TOKEN` khud-ba-khud milta hai, uska secret nahi banana.

---

## 1. FB_PAGE_ID

- **Value (tumhari taiyaar hai):** `1456603634203701`
- Ye Rahasya Bharat wale Facebook Page ki ID hai. Bas copy karke secret bana do.

## 2. FB_PAGE_TOKEN  ⭐ sabse zaroori

**Kya hai:** Rahasya Bharat Page ka *kabhi expire na hone wala* token. Isi ek token se **Facebook post + Instagram Reel dono** publish honge.

**Shart:** Ye token us Facebook login se banna chahiye jise Rahasya Bharat Page par **full control** mila hai (Eric D Burris wali ID ko mila hua hai — wahi use karna). StudyGyaan ke purane token se kaam nahi chalega, token har Page ka alag hota hai.

**Steps:**
1. [developers.facebook.com/tools/explorer](https://developers.facebook.com/tools/explorer) kholo (usi FB ID se login).
2. Upar app chuno (koi bhi maujooda app; nahi hai to ek app banao — type "Other/Consumer").
3. **Get Token → Get User Access Token** → ye 4 permissions jodo:
   `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `instagram_content_publish` → **Generate Access Token** → Allow karo.
4. Ab is chhote token ko lamba karo: Explorer me hi URL wali jagah ye chalao (APP_ID aur APP_SECRET usi app ke Settings → Basic me milenge):
   `oauth/access_token?grant_type=fb_exchange_token&client_id=APP_ID&client_secret=APP_SECRET&fb_exchange_token=CHHOTA_TOKEN`
   Jo token mile wahi **long-lived user token** hai (lagbhag 60 din).
5. Phir Explorer me chalao: `me/accounts` → list me **Rahasya Bharat** dhundo → uske saath wala `access_token` hi tumhara **Page token** hai (long-lived user token se bana Page token kabhi expire nahi hota).
6. **Pakka karo:** [developers.facebook.com/tools/debug/accesstoken](https://developers.facebook.com/tools/debug/accesstoken) me woh token daalo → **Type: Page** aur **Expires: Never** dikhna chahiye. Dikh gaya to wahi value `FB_PAGE_TOKEN` secret me daal do.

## 3. IG_USER_ID

- **Expected value:** `17841409762175655` (Rahasya Bharat ke Instagram @rahasyabharatt ki Graph API ID)
- **Pakka karne ka tareeka:** Graph Explorer me Page token use karke chalao:
  `1456603634203701?fields=instagram_business_account`
  Jo `id` aaye wahi dalna. Expected value se match ho to bina soche daal do.

---

## 4–6. YouTube ke teen secrets

Pehle ek Google Cloud project banana hoga:

1. [console.cloud.google.com](https://console.cloud.google.com) → **New Project** → naam: `Rahasya Bharat`.
2. **APIs & Services → Library** → `YouTube Data API v3` search karke **Enable** karo.
3. **OAuth consent screen** → User type **External** → app naam `Rahasya Bharat`, apni email bharkar save. **Test users** me woh Google email jodo **jis account par YouTube channel (@RahasyaBharatt) hai** — ye kadam bhoolna mat, warna login fail hoga.
4. **Credentials → Create Credentials → OAuth client ID** → Application type **Desktop app** → Create. Jo file download hogi (JSON) usi me dono values hain:

### 4. YT_CLIENT_ID
Downloaded JSON ki `client_id` wali value.

### 5. YT_CLIENT_SECRET
Usi JSON ki `client_secret` wali value.

### 6. YT_REFRESH_TOKEN  ⭐

1. Apne PC par Python rakho, phir: `pip install google-auth-oauthlib`
2. Is repo ki `scripts/yt_auth_local.py` file aur woh downloaded JSON (naam badalkar `client_secret.json`) ek hi folder me rakho.
3. Chalao: `python yt_auth_local.py` → browser khulega → **usi Google account se sign-in karo jis par channel hai** → Allow.
4. Screen par refresh token print hoga — wahi `YT_REFRESH_TOKEN` secret me daal do.
   (Dhyaan: sign-in kisi aur Google account se hua to upload galat channel par jayega ya fail hoga.)

### ⚠️ YouTube ki ek jaankari pehle se (taaki baad me surprise na ho)

Google ka niyam hai: jab tak Cloud project ka OAuth app **verify** na ho, API se upload ki gayi
videos YouTube **private par lock** kar sakta hai. Agar pehli upload public ki jagah private
dikhe to ghabrana mat — code sahi hai, ye Google ki verification wali rokh hai.
Uska hal: consent screen par **Publish App** karke verification ke liye apply karna
(Google scope ki justification aur kabhi-kabhi ek chhoti demo video mangta hai; kuch din lag sakte hain).
Tab tak ke liye YouTube Studio app se us video ko haath se public karna hoga.

---

## 7–8. Threads ke do secrets (2026-11-09 joda gaya)

Threads ka token FB Page token se ALAG hota hai — Threads API Page
token nahi leti. Dono secrets na hon to pipeline Threads ko chhod
kar purani teen platforms par chalti rehti hai; hon to Threads bhi
chautha platform ban jata hai (vault retry samet).

**THREADS_USER_ID:** `17841441106180278` (@rahasyabharatt ki Threads ID — taiyaar hai, bas daal do)

**THREADS_ACCESS_TOKEN banane ke steps:**
1. [developers.facebook.com](https://developers.facebook.com) → My Apps → **rahasya bharat**.
2. Left side **Use cases** (ya "Add products") → **Threads API** jodo / Customize kholo.
3. Wahan **User Token Generator** milega → **Add account** → @rahasyabharatt
   wale account se login karke allow karo. (Agar Threads app me invite
   aaye to Threads app → Settings → Website permissions → Invites me
   use pehle accept karna hoga.)
4. Account jud jaye to uske saamne **Generate token** dabao → jo token
   mile wahi `THREADS_ACCESS_TOKEN` secret me daal do. **Chat me mat bhejna.**
5. Token lagbhag **60 din** chalta hai; khatam hone se pehle Muse
   yaad dilayega, tab yahi steps dohra kar naya daal dena hai.

## Checklist (sab ho jaye to Muse ko "secrets dal diye" bolna)

- [ ] FB_PAGE_ID
- [ ] FB_PAGE_TOKEN (Debug tool me Type: Page / Expires: Never verify karke)
- [ ] IG_USER_ID
- [ ] YT_CLIENT_ID
- [ ] YT_CLIENT_SECRET
- [ ] YT_REFRESH_TOKEN
- [ ] THREADS_USER_ID
- [ ] THREADS_ACCESS_TOKEN (upar wale steps se bana kar)

Uske baad Muse: pehle **dry-run** test karega (video bankar ready, bina publish),
phir ek **asli test post** karke teeno platform par live verify karke report dega.
