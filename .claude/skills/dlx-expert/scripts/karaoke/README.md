# קריוקי: משיר לסרטון קריוקי (פלייבק + מילים מסונכרנות + טונליות)

המדריך המקצועי (מתי, איך מדברים עם הלקוח, זכויות, רף הסוכנות): `references/karaoke.md`. כאן רק הכלים.

| קובץ | מה הוא עושה |
|---|---|
| `karaoke.py` | הצינור המלא: הפרדת קול, יישור מילים לערוץ הקול (או טיוטת תמלול), שורות, ספירה לאחור, קובץ ASS (עברית מימין לשמאל), שינוי טונליות, מיקס ל-‎-14 LUFS, רינדור MP4 ו-`timing.json` |
| `qa_karaoke.py` | בדיקה חובה: סנכרון מול ערוץ הקול, שאריות קול בפלייבק, דיוק טונליות (סנטים), אורך, עוצמה, כיוון ההדגשה בפריימים, סדר מילים ב-OCR. יוצא 1 על FAIL |
| `requirements.txt` | גרסאות שנבדקו (Python 3.13, ‏CPU בלבד) |

## התקנה (פעם אחת, נבדק 11/2026 על Ubuntu 24.04)

```bash
# כלי מערכת: ffmpeg עם libass+fribidi+harfbuzz+rubberband (הגרסה של Ubuntu כוללת), Rubber Band CLI, ו-OCR לבדיקה
apt-get install -y ffmpeg rubberband-cli tesseract-ocr tesseract-ocr-heb
# סביבת Python נפרדת
python3 -m venv ~/.venvs/karaoke
~/.venvs/karaoke/bin/pip install --upgrade pip
~/.venvs/karaoke/bin/pip install torch torchaudio torchvision --index-url https://download.pytorch.org/whl/cpu
~/.venvs/karaoke/bin/pip install "audio-separator[cpu]" audioread faster-whisper stable-ts librosa pyloudnorm soundfile
# בדיקה מהירה
ffmpeg -hide_banner -filters | grep -E " ass | rubberband"; rubberband --version; ~/.venvs/karaoke/bin/audio-separator --version
```
**מלכודות שנתקלנו בהן:** (1) `torchvision` מ-PyPI לא תואם ל-torch של אינדקס ה-CPU (`operator torchvision::nms does not exist`):
מתקינים אותו מאותו אינדקס. (2) `audio-separator` דורש `audioread` שלא תמיד מותקן אוטומטית.
(3) משקולות Demucs (`dl.fbaipublicfiles.com`) חסומות בחלק מהסביבות (403). מודלי RoFormer ו-MDX יורדים מ-GitHub ועובדים.

**הורדות מודלים (פעם אחת):** BS-RoFormer ‏640MB, MDX Inst HQ3 ‏~65MB (ב-`~/.cache/karaoke-models`, או `KARAOKE_MODELS=`),
Whisper large-v3-turbo ו-ivrit-ai turbo ‏~1.6GB כל אחד (ב-`~/.cache/huggingface`). סה"כ כ-4GB.

## הפעלה

```bash
PY=~/.venvs/karaoke/bin/python
# אין מילים: טיוטת תמלול (lyrics_draft.txt, [?מילה] = לא בטוח). יוצא בקוד 3 עד שהלקוח מאשר
$PY karaoke.py --audio song.mp3 --lang he --out work/song
# יש מילים מאושרות: גרסה מקורית, 16:9 ו-9:16
$PY karaoke.py --audio song.mp3 --lyrics lyrics.txt --lang he --title "שם" --artist "מבצע" --formats 16x9,9x16 --out work/song
# חצי טון למטה (ההפרדה והיישור לא רצים שוב: הם שמורים ב-work/)
$PY karaoke.py --audio song.mp3 --lyrics lyrics.txt --lang he --semitones -1 --out work/song
# בדיקה
$PY qa_karaoke.py work/song/<name>-timing--1st.json
```

| דגל | ברירת מחדל | הסבר |
|---|---|---|
| `--lyrics` | אין | טקסט, שורה מושרת בכל שורה, שורה ריקה = מעבר בין בתים. `[פזמון]` ו-`(x2)` מתעלמים. **כל חזרה שמושרת צריכה להופיע** |
| `--lang` | auto | `he` / `en`. auto: לפי האותיות במילים, או זיהוי שפה מהקול |
| `--semitones` | 0 | ‎-1 חצי טון למטה, ‎-2 טון למטה, +1 למעלה. Rubber Band R3 עם שימור פורמנטים, אורך זהה |
| `--guide-vocal` | 0 | עוצמת הקול המקורי בפלייבק (0.15 ≈ ‎-16dB, "קול מנחה") |
| `--bg` | צבע כהה | תמונה (מטושטשת ומוחשכת אוטומטית) או `#RRGGBB` |
| `--formats` | 16x9 | `16x9`, `9x16` או שניהם |
| `--sep` | best | `best` (BS-RoFormer), `fast` (MDX HQ3), `melband`, או שם קובץ מודל של audio-separator (למשל מודל karaoke שמשאיר קולות רקע) |
| `--max-words` | 6 | מקסימום מילים בשורה על המסך |
| `--draft-ok` | | מרנדר גם טיוטה לא מאושרת (מילים לא בטוחות עם קו תחתון), לתצוגה בלבד |

**פלט:** `<name>-karaoke-<orig|-1st>-<16x9|9x16>.mp4`, קובץ `.ass` לכל פורמט, `<name>-timing-<tag>.json`,
ו-`work/` (מיקס, `vocals.wav`, `instrumental.wav`, גרסאות בטונליות אחרת, `karaoke_mix_*.wav` = הפלייבק הסופי).

## זמני ריצה שנמדדו (CPU בלבד, 4 ליבות, 16GB RAM)
| שלב | זמן |
|---|---|
| הפרדה `fast` (MDX HQ3) | ~0.55× אורך השיר (שיר של 4 דק' ≈ 2:15 דק') |
| הפרדה `best` (BS-RoFormer, overlap 2) | ~13× אורך השיר (30 שנ' ≈ 6:40 דק') |
| יישור מילים (turbo, int8) | TBD |
| Rubber Band R3 ‏-F | TBD |
| רינדור 1080p | TBD |

## מה נבדק ואיך (qa_karaoke.py)
- **סנכרון:** תחילת כל מילה מול נקודת הפתיחה (onset) הקרובה בערוץ הקול; תחילת כל משפט מול עליית האנרגיה אחרי
  שקט; היסט גלובלי בקורלציה; אחוז זמן המילים שיש בו קול. FAIL: p90 מעל 250ms, היסט מעל 100ms, או פחות מ-75% קול.
  `--shift 0.4` = בדיקת שליטה (חייבת להיכשל).
- **שאריות קול:** מפרידים שוב את הפלייבק במודל שני (MDX HQ3) ומשווים את ה"קול" שנשאר לערוץ הקול האמיתי (dB),
  כולל החלון הגרוע של 2 שניות (להקשיב שם). FAIL מעל ‎-14dB, WARN מעל ‎-20dB.
- **טונליות:** קורלציה של ספקטרום לוגריתמי (5 סנט לתא, אחרי הלבנה) בין הפלייבק המקורי למוזז, חציון על בלוקים
  של ~1.5 שנ'. FAIL: שגיאה מעל 15 סנט, הפרש אורך מעל 50ms, היסט בזמן מעל 20ms.
- **פריימים:** רגע באמצע המילה השנייה של שורות לאורך השיר, ופריימי ספירה לאחור. בודק אוטומטית שהחלק הצהוב
  (שכבר שרו) בצד ימין בעברית ובצד שמאל באנגלית, ומריץ OCR (tesseract) לסדר המילים. גיליון: `qa/contact_<fmt>.png`.

## עברית ב-libass (נבדק בפריימים, libass 0.17.1)
- `Encoding` של הסגנון חייב להיות ‎-1 (זיהוי כיוון לפי Unicode). עם 1 (ברירת המחדל הנפוצה) פיסוק ושורות מעורבות מתהפכים.
- `\kf` ממלא כל מילה משמאל לימין גם בעברית, ולכן בעברית הסקריפט משתמש ב-`\k` לכל אות (אות ועוד הניקוד שלה).
