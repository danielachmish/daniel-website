# תבניות קופי: מתחילים מכאן, לא מדף ריק

כל תבנית היא שלד מלא בעברית עם הוראות בתוך סוגריים מרובעים. ממלאים, מוחקים את ההוראות, ומריצים QA.
**כל יחידת קופי יושבת בבלוק ` ```copy <שדה> ` ** כדי ש-`scripts/qa_copy.py` יספור תווים ויבדוק אותה.

| תבנית | מתי | QA |
|---|---|---|
| `strategy-onepager.md` | לפני כל קמפיין: חמש השורות, שלב מודעות, הרעיון הגדול, מלאי הוכחות | עובר על עין + מבקר |
| `ad-set.md` | סט מודעות: Meta (3 זוויות), Google RSA (15+4), TikTok, לינקדאין, וואטסאפ/SMS | `qa_copy.py` |
| `content-calendar-30d.md` + `calendar-plan.template.json` | לוח תוכן לחודש → גיליון Excel | `content_calendar.py` (מריץ את `qa_copy` על כל פוסט) |
| `review-replies.md` | ספריית תגובות לביקורות בגוגל + הודעת בקשת ביקורת | `qa_copy.py` |
| `car-listing.md` | מודעת רכב: יד2/מרקטפלייס, גרסה קצרה, רשימת צילום, תשובות לקונים | `qa_copy.py` |
| `apartment-listing.md` | דירה למכירה/השכרה | `qa_copy.py` |

## שדות (תגית הבלוק)
`meta.primary` · `meta.headline` · `meta.description` · `meta.cta` · `meta.reels` · `google.headline` · `google.description` ·
`google.path` · `google.sitelink` · `google.callout` · `tiktok.text` · `instagram.caption` · `facebook.post` ·
`linkedin.post` · `gbp.post` · `gbp.reply` · `youtube.title` · `sms` · `email.subject` · `email.body` ·
`whatsapp.broadcast` (שיווקי, דורש הסכמה) · `whatsapp` / `reply` (תשובה אישית לפנייה) · `listing.title` ·
`listing.body` · `listing.short` · `landing` (טקסט דף נחיתה) · `post`.
וריאנט: ` ```copy meta.primary v=A `. כל השדות עם אותו `v=` נבדקים כמודעה אחת (למשל הנעה לפעולה).
בשדות `google.*` כל שורה היא נכס נפרד.

## הפעלה
```bash
python3 scripts/qa_copy.py templates/copy/ad-set.md --draft   # תבנית: placeholders = אזהרה
python3 scripts/qa_copy.py client/ad-set.md                    # מסירה: placeholder בקופי = FAIL
python3 scripts/qa_copy.py client/ad-set.md --counts           # טבלת תווים להדבקה במסירה
python3 scripts/content_calendar.py plan.json calendar.xlsx --final
```
טענה חזקה שבאמת מוכחת (אחריות אמיתית, "100% כותנה"): מתעדים בקובץ
`<!-- qa-allow: <המילה> | <ההוכחה ואיפה היא> -->`. זה מוריד את ה-FAIL לאזהרה עם הנימוק, ולא מעלים אותו.
