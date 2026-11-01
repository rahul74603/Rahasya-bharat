# Rahasya Bharat — Daily Video Pipeline

Roz 2 Hindi Shorts (subah 08:00 IST *Itihaas ki Kahani*, shaam 19:00 IST *Rahasya*)
poori tarah GitHub Actions me bante aur teeno platform par publish hote hain:

**YouTube Shorts · Instagram Reels · Facebook Page**

## Flow (har run)

1. `topics.json` se slot ka agla topic (jiski script ready hai) chunta hai — `state.json` rotation rakhta hai.
2. **Video banta hai** (`scripts/make_video.py`):
   - Hindi voiceover — edge-tts (`hi-IN-MadhurNeural`, katha ki gati par)
   - Us jagah ki **asli photos** — Wikimedia Commons se (real jagah, real tasveer)
   - Slow zoom (Ken Burns) + burnt-in Devanagari captions — vertical 1080×1920
3. **Publish** hota hai:
   - Facebook Page — video file seedha upload (`scripts/publish_fb.py`)
   - Instagram — Meta ko public URL chahiye, isliye video ek **temporary GitHub Release** me jaati hai, Reel publish hoti hai, aur release **turant delete** ho jaati hai (`scripts/gh_release.py`, `scripts/publish_ig.py`) — GitHub par video store nahi rehti.
   - YouTube — Data API v3 upload (`scripts/publish_yt.py`)
4. `state.json` update hokar repo me wapas commit hota hai.
5. Koi bhi platform fail ho to run **RED** hota hai (exit 1) — StudyGyaan wali "silent fail" galti yahan jaan-bujh kar nahi dohraayi gayi hai. `state.json` me har post ke results + failures likhe rehte hain.

## Files

| File | Kaam |
|---|---|
| `topics.json` | 30 topics ka bank (15 subah + 15 shaam). Jinme `script` bhara hai wahi rotation me aate hain; baaki `script: null` = script baaki hai, runner unhe skip karke aage badhta hai aur agar ek bhi ready topic na bache to saaf error dekar rukta hai (filler kabhi post nahi hoga). |
| `state.json` | Kaunsa topic kab post hua, kis platform par result kya raha. |
| `scripts/run.py` | Orchestrator — topic → build → publish → state. |
| `scripts/yt_auth_local.py` | Apne PC par ek baar chalakar YouTube refresh token nikalne ke liye. |
| `.github/workflows/daily-video.yml` | Cron 02:30 UTC (08:00 IST) aur 13:30 UTC (19:00 IST) + manual run (slot + dry-run options). |
| `SECRETS.md` | Kaun se secrets chahiye, unki values kahan se milengi — poori guide. |

## Pehle test ke liye

Repo ke **Actions** tab → *Rahasya Bharat — Daily Video* → **Run workflow** → slot `morning`, `dry_run: true`.
Isse video bankar run ke logs me dikhega bina publish hue. Phir secrets dalne ke baad `dry_run: false` se pehla asli post.

## Ek imandaar note (quality)

Ye pipeline wale video **photo + awaaz + captions** wale hain — asli jagah ki tasveeron ke saath.
Muse ke banaye AI-cinematic-clip wale video (jaise Lepakshi sample) GitHub Actions se nahi
ban sakte, kyunki video-generation Muse ke apne system me hota hai. Isliye tay kram:
**roz ka base = ye pipeline; khaas AI-clip wale video = Muse alag se banata rahega.**
