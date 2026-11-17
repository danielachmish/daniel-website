---
name: torah-clips
description: Turn a long Torah lesson (YouTube link or video/audio file, 1-2+ hours, Hebrew) into accurate, viral short clips — TikTok/Reels/Shorts (20-60s) or longer 2-5 minute videos. Use when the user sends a lesson (shiur) link or file and asks for shorts, clips, reels, or "cut this into videos". Identifies complete moves (kushya-teirutz, mashal-nimshal, stories, practical calls to action), verifies each clip is faithful to the rabbi's intent out of context, then renders vertical videos with burned-in Hebrew captions.
---

# Torah Clips — משיעור לסרטונים

המטרה: המשתמש שולח שיעור ומקבל בחזרה את כל הקטעים האיכותיים שאפשר להוציא ממנו, באורך שביקש.
**דיוק קודם לוויראליות.** קטע שמעוות את כוונת הרב גרוע מאין קטע.

## תהליך

עבוד בתיקיית עבודה לכל שיעור: `work/<slug>/` (בתיקיית ה-scratchpad או איפה שהמשתמש מבקש).

### 1. הבנת הבקשה
הפוך את בקשת המשתמש להגדרת עבודה (כתוב ב-`work/<slug>/request.json`):
- `formats`: אילו אורכים — `short` (20–60 שניות), `medium` (1.5–3 דקות), `long` (4–6 דקות), או אורכים מדויקים שהמשתמש ציין.
- `count`: מספר, או `"max"` ("כמה שיש") = כל מועמד שעובר את רף האיכות, בלי מילוי.
- `platform`, `style` — אם צוינו.
- `mode`: `plan` (רשימת קטעים בלבד, בלי רינדור) או `render`. **ברירת מחדל: `plan` בהרצה הראשונה על שיעור חדש**, אלא אם המשתמש ביקש במפורש סרטונים מוכנים.

### 2. הורדה
```bash
bash .claude/skills/torah-clips/scripts/fetch.sh "<קישור או נתיב לקובץ>" work/<slug>
```
יוצר `source.mp4` (או קישור לקובץ המקומי) ו-`audio.wav` (16kHz מונו).
אם יוטיוב חוסם הורדה מהשרת — אמור למשתמש ובקש שיעלה את הקובץ.

### 3. תמלול
```bash
python3 .claude/skills/torah-clips/scripts/transcribe.py work/<slug>/audio.wav work/<slug>
```
יוצר:
- `words.json` — כל מילה עם זמן התחלה/סוף (לחיתוך מדויק ולכתוביות).
- `transcript.txt` — התמלול בשורות `[hh:mm:ss.s] טקסט`, מפוצל בהפסקות. **זה הקובץ שאתה מנתח.**

מודל עברית כברירת מחדל (ivrit-ai). על מעבד (CPU) זה לוקח בערך 0.5–1 מאורך השיעור — הרץ ברקע ועדכן את המשתמש.
אחרי התמלול עבור על `references/glossary.md` ותקן בקריאה שלך טעויות תמלול שיטתיות במונחים (לא בקבצים).

### 4. ניתוח — לב הסקיל
קרא את `references/method.md` במלואו ופעל לפיו בדיוק. קרא את **כל** `transcript.txt` לפני שאתה בוחר משהו.
לניתוח יש ארבעה מעברים נפרדים; אל תדלג על אף אחד:
1. **מיפוי מהלכים** ← `work/<slug>/map.md`
2. **בחירת מועמדים** לפי פורמט
3. **בדיקת נאמנות** — מעבר נפרד שמנסה *לפסול* כל מועמד. אם אפשר, הרץ אותו כסוכן נפרד (כלי Agent) שמקבל את המועמד + ±5 דקות הקשר סביבו, בלי הנימוקים שלך.
4. **דירוג וכיול נקודות חיתוך**

פלט: `work/<slug>/clips.json` בפורמט שב-`references/method.md`, ועוד `work/<slug>/clips.md` — דוח קריא למשתמש.

### 5. רינדור (רק במצב `render` או אחרי שהמשתמש אישר את הרשימה)
```bash
python3 .claude/skills/torah-clips/scripts/render.py work/<slug>
```
מרנדר כל קטע ב-`clips.json` ל-`work/<slug>/out/<id>.mp4`: 9:16 ב-1080×1920, כותרת פתיח למעלה, כתוביות בעברית עם הדגשה מילה-אחר-מילה, אודיו מנורמל. דגלים: `--only 03,07`, `--aspect 16:9` לקטעים אופקיים, `--crop-x 0.4` (מיקום אופקי של המסגרת, 0–1) אם הרב לא במרכז הפריים.
אחר כך שלוף פריים אחד מכל קטע ובדוק בעין שהכתוביות והמסגור תקינים:
`ffmpeg -ss 3 -i out/01.mp4 -frames:v 1 check01.png`

### 6. מסירה
הצג למשתמש את `clips.md` (טבלה: מזהה, אורך, כותרת, פתיח, מסר, זמני מקור, ציון נאמנות, ציון ויראליות) ושלח את הקבצים.
בקש פידבק לכל קטע. **כל תיקון של המשתמש הוא הזדמנות ללמידה**: אם זה כלל חוזר — הוסף ל-`references/method.md` תחת "לקחים מפידבק"; אם זה מונח — ל-`references/glossary.md`.

## כללי ברזל
- לעולם אל תחתוך עמדה שהרב מביא כדי לדחות אותה ("הווה אמינא", "אפשר היה לחשוב", "אבל האמת היא...") כאילו היא המסקנה שלו.
- פסק הלכה בלי הסייג שהרב צירף — פסול, או הרחב את הקטע כך שיכלול את הסייג.
- אל תתפור קטעים לא צמודים אלא אם המשתמש התיר; אם תופרים, סמן `stitched: true` ונמק בבדיקת הנאמנות.
- אל תמציא טקסט: הכותרת והפתיח באים מדברי הרב או מסכמים אותם בנאמנות. בלי ציטוטים שהוא לא אמר.
- `count: "max"` לא אומר מילוי. עדיף 9 קטעים מצוינים מ-20 בינוניים. אמור כמה נפסלו ולמה.
