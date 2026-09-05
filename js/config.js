/**
 * config.js
 * -------------------------------------------------------------------------
 * מקום מרכזי לכל הפרטים האמיתיים של האתר: פרטי קשר, קישורי רשת, וכתובת
 * ה-endpoint שאליו נשלח טופס יצירת הקשר.
 *
 * חשוב: קובץ זה רץ בדפדפן (צד לקוח) ולכן אסור לשים בו סודות (API keys,
 * סיסמאות, טוקנים). כל מידע רגיש חייב לשבת בשרת בלבד (ראו server/README).
 *
 * בסביבת פרודקשן מומלץ להזריק את הערכים האלה בזמן build מתוך משתני סביבה
 * (למשל דרך Vite/Next/11ty), כדי שכתובת ה-API לא תהיה מקודדת-קשיח בקוד.
 * לדוגמה עם Vite: import.meta.env.VITE_CONTACT_ENDPOINT
 */
window.SITE_CONFIG = {
  // כתובת אימייל אמיתית להצגה באתר וכיעד גיבוי לפניות. יש להחליף.
  CONTACT_EMAIL: "danielachmish@gmail.com", // לדוגמה: "hello@daniellachmish.com"

  // מספר טלפון אמיתי להצגה באתר. יש להחליף (או להשאיר ריק כדי להסתיר).
  CONTACT_PHONE: "0547945077", // לדוגמה: "050-0000000"

  // כתובת ה-API שהטופס שולח אליה POST. מחובר ל-Formspree (https://formspree.io).
  // כדי להחליף בעתיד לשרת עצמאי — ראו server/ — רק משנים את הכתובת כאן.
  CONTACT_ENDPOINT: "https://formspree.io/f/xkjnvooe",

  // קישורי רשתות חברתיות/מקצועיות. השאירו ריק כדי לא להציג קישור.
  SOCIAL_LINKS: {
    linkedin: "", // לדוגמה: "https://www.linkedin.com/in/daniel-lachmish"
    github: "",   // לדוגמה: "https://github.com/username"
    whatsapp: "https://wa.me/972547945077"  // לדוגמה: "https://wa.me/9725XXXXXXXX"
  }
};
