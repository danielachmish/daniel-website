/**
 * shop/js/products.js
 * -------------------------------------------------------------------------
 * קטלוג המוצרים. כל מוצר הוא אובייקט במערך PRODUCTS.
 * ⚠️ המוצרים והמחירים כאן הם דוגמאות — יש להחליף במלאי ובמחירים האמיתיים שלך.
 *
 * שדות מוצר:
 *   id          מזהה ייחודי (אנגלית, בלי רווחים)
 *   name        שם המוצר
 *   category    מזהה קטגוריה (מתוך CATEGORIES)
 *   price       מחיר בשקלים
 *   oldPrice    מחיר לפני הנחה (אופציונלי — יוצג כמבצע)
 *   compat      תאימות: "iPhone" / "Samsung" / "Universal" (אפשר כמה)
 *   colors      צבעים זמינים (אופציונלי) — הלקוח יבחר אחד
 *   badge       תגית (אופציונלי): "חדש" / "רב מכר" / "מבצע"
 *   inStock     true/false
 *   image       נתיב לתמונה אמיתית (אופציונלי, למשל "assets/products/charger.jpg").
 *               אם אין — מוצג איור אוטומטי לפי הקטגוריה.
 *   tint        צבע האיור כשאין תמונה
 *   description תיאור קצר
 *   features    רשימת נקודות
 */
window.CATEGORIES = [
  { id: "chargers",  name: "מטענים",        icon: "chargers" },
  { id: "cables",    name: "כבלים",          icon: "cables" },
  { id: "cases",     name: "כיסויים",        icon: "cases" },
  { id: "screen",    name: "מגני מסך",       icon: "screen" },
  { id: "audio",     name: "אוזניות ושמע",   icon: "audio" },
  { id: "power",     name: "סוללות ניידות",  icon: "power" },
  { id: "holders",   name: "מעמדים ומחזיקים", icon: "holders" }
];

window.PRODUCTS = [
  {
    id: "charger-20w", name: "מטען קיר מהיר 20W USB-C", category: "chargers",
    price: 59, oldPrice: 79, compat: ["iPhone", "Samsung", "Universal"], badge: "רב מכר",
    inStock: true, tint: "#2563eb", colors: ["לבן", "שחור"],
    description: "מטען קיר קומפקטי עם טעינה מהירה PD — מטעין אייפון ל-50% בכ-30 דקות.",
    features: ["Power Delivery 20W", "חיבור USB-C", "הגנה מחימום יתר וקצר", "תקע ישראלי"]
  },
  {
    id: "charger-45w", name: "מטען קיר 45W כפול (USB-C + USB-A)", category: "chargers",
    price: 99, compat: ["Samsung", "Universal"], badge: "חדש",
    inStock: true, tint: "#0f172a",
    description: "שתי יציאות לטעינה של שני מכשירים במקביל. תומך Super Fast Charging של סמסונג.",
    features: ["עד 45W", "PPS לסמסונג", "2 יציאות", "מתאים גם לטאבלט"]
  },
  {
    id: "car-charger", name: "מטען לרכב 38W כפול", category: "chargers",
    price: 69, compat: ["Universal"], inStock: true, tint: "#475569",
    description: "טעינה מהירה בדרך — USB-C ו-USB-A, עם תאורת LED עדינה.",
    features: ["38W משולב", "USB-C PD + QC3.0", "גוף מתכת", "מתאים לכל רכב"]
  },
  {
    id: "wireless-pad", name: "משטח טעינה אלחוטי 15W", category: "chargers",
    price: 89, oldPrice: 119, compat: ["iPhone", "Samsung"], badge: "מבצע",
    inStock: true, tint: "#7c3aed",
    description: "מניחים ונטען. תואם לכל מכשיר עם טעינה אלחוטית (Qi).",
    features: ["עד 15W", "תקן Qi", "נורית מצב", "כבל USB-C כלול"]
  },
  {
    id: "cable-cc", name: "כבל USB-C ל-USB-C קלוע 1 מ׳", category: "cables",
    price: 35, compat: ["Samsung", "iPhone", "Universal"], inStock: true, tint: "#0ea5e9",
    colors: ["שחור", "לבן", "אפור"],
    description: "כבל קלוע ועמיד במיוחד, תומך טעינה מהירה עד 60W והעברת נתונים.",
    features: ["60W", "קליעת ניילון", "אורך 1 מטר", "מתאים לאייפון 15 ומעלה"]
  },
  {
    id: "cable-lightning", name: "כבל USB-C ל-Lightning 1 מ׳", category: "cables",
    price: 39, compat: ["iPhone"], badge: "רב מכר", inStock: true, tint: "#e2e8f0",
    description: "לטעינה מהירה של אייפון 8 עד 14 עם מטען USB-C.",
    features: ["טעינה מהירה PD", "שבב תואם", "אורך 1 מטר", "ראש מחוזק"]
  },
  {
    id: "cable-2m", name: "כבל USB-C ארוך 2 מ׳", category: "cables",
    price: 45, compat: ["Universal"], inStock: true, tint: "#f97316",
    description: "האורך שמגיע עד המיטה. קלוע, עם ראשים מחוזקים.",
    features: ["2 מטר", "עד 60W", "קליעת ניילון", "אחריות שנה"]
  },
  {
    id: "case-clear-iphone", name: "כיסוי שקוף MagSafe לאייפון", category: "cases",
    price: 49, compat: ["iPhone"], inStock: true, tint: "#94a3b8",
    colors: ["iPhone 14", "iPhone 15", "iPhone 16", "iPhone 16 Pro", "iPhone 17 Pro"],
    description: "כיסוי שקוף שלא מצהיב, עם מגנט מובנה לטעינה ואביזרי MagSafe.",
    features: ["מגנט MagSafe", "פינות מוגנות", "לא מצהיב", "שוליים מוגבהים למצלמה"]
  },
  {
    id: "case-silicone-samsung", name: "כיסוי סיליקון לסמסונג Galaxy", category: "cases",
    price: 45, oldPrice: 59, compat: ["Samsung"], badge: "מבצע", inStock: true, tint: "#16a34a",
    colors: ["Galaxy S24", "Galaxy S25", "Galaxy A55", "Galaxy A35"],
    description: "סיליקון רך עם בטנה פנימית נעימה, אחיזה טובה ומראה נקי.",
    features: ["סיליקון נוזלי", "בטנת מיקרופייבר", "כפתורים מדויקים", "דק וקל"]
  },
  {
    id: "case-rugged", name: "כיסוי מוקשח עם מעמד", category: "cases",
    price: 69, compat: ["iPhone", "Samsung"], inStock: true, tint: "#1e293b",
    colors: ["iPhone 16", "iPhone 16 Pro", "Galaxy S25", "Galaxy A55"],
    description: "הגנה כפולה לנפילות, עם טבעת מעמד מסתובבת לצפייה בסרטונים.",
    features: ["הגנה צבאית", "טבעת מעמד 360°", "שכבה כפולה", "תואם טעינה אלחוטית"]
  },
  {
    id: "glass-full", name: "מגן מסך זכוכית מלא 9H", category: "screen",
    price: 29, compat: ["iPhone", "Samsung"], badge: "רב מכר", inStock: true, tint: "#06b6d4",
    colors: ["iPhone 15", "iPhone 16", "iPhone 16 Pro", "Galaxy S25", "Galaxy A55"],
    description: "זכוכית מחוסמת לכיסוי מלא של המסך, עם מסגרת להדבקה מדויקת.",
    features: ["קשיות 9H", "שכבה נגד טביעות אצבע", "מסגרת הדבקה כלולה", "רגישות מגע מלאה"]
  },
  {
    id: "glass-privacy", name: "מגן מסך פרטיות", category: "screen",
    price: 45, compat: ["iPhone", "Samsung"], inStock: true, tint: "#334155",
    colors: ["iPhone 15", "iPhone 16", "iPhone 16 Pro", "Galaxy S25"],
    description: "רק מי שמולך רואה את המסך. מושלם לתחבורה ציבורית ולמשרד.",
    features: ["זווית צפייה מוגבלת", "קשיות 9H", "קל להדבקה", "ללא בועות"]
  },
  {
    id: "earbuds", name: "אוזניות אלחוטיות עם ביטול רעשים", category: "audio",
    price: 179, oldPrice: 229, compat: ["Universal"], badge: "מבצע", inStock: true, tint: "#f8fafc",
    colors: ["לבן", "שחור"],
    description: "ביטול רעשים אקטיבי, עד 30 שעות עם הקופסה, ומיקרופונים ברורים לשיחות.",
    features: ["ANC", "Bluetooth 5.3", "עד 30 שעות", "עמידות למים IPX4"]
  },
  {
    id: "earphones-c", name: "אוזניות חוטיות USB-C", category: "audio",
    price: 39, compat: ["Samsung", "iPhone", "Universal"], inStock: true, tint: "#e2e8f0",
    description: "סאונד נקי ושלט עם מיקרופון. מתאים לכל מכשיר עם USB-C.",
    features: ["חיבור USB-C", "שלט + מיקרופון", "כבל 1.2 מ׳", "קל ונוח"]
  },
  {
    id: "powerbank-10k", name: "סוללה ניידת 10,000mAh", category: "power",
    price: 99, compat: ["Universal"], badge: "רב מכר", inStock: true, tint: "#0f172a",
    description: "קטנה כמו טלפון — טוענת אותו כ-2 פעמים מלאות. עם תצוגת אחוזים.",
    features: ["10,000mAh", "22.5W טעינה מהירה", "USB-C + USB-A", "תצוגה דיגיטלית"]
  },
  {
    id: "powerbank-magsafe", name: "סוללה מגנטית MagSafe 5,000mAh", category: "power",
    price: 129, compat: ["iPhone"], badge: "חדש", inStock: true, tint: "#a78bfa",
    description: "נצמדת לגב האייפון וטוענת בלי כבלים. דקה ונוחה לכיס.",
    features: ["מגנט MagSafe", "5,000mAh", "טעינה אלחוטית 15W", "מעמד מתקפל"]
  },
  {
    id: "car-mount", name: "מחזיק מגנטי לרכב לפתח מזגן", category: "holders",
    price: 49, compat: ["Universal"], inStock: true, tint: "#64748b",
    description: "מגנט חזק שמחזיק את הטלפון יציב גם בכבישים משובשים. התקנה בשנייה.",
    features: ["מגנט N52", "סיבוב 360°", "תפס מזגן יציב", "כולל מדבקות מתכת"]
  },
  {
    id: "desk-stand", name: "מעמד שולחני מתכוונן מאלומיניום", category: "holders",
    price: 59, compat: ["Universal"], inStock: false, tint: "#cbd5e1",
    description: "מעמד יציב לטלפון או טאבלט, מתקפל ומתכוונן בגובה ובזווית.",
    features: ["אלומיניום", "מתקפל", "גומיות נגד החלקה", "מתאים לטאבלטים"]
  }
];
