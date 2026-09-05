/**
 * contact-server-example.js
 * -------------------------------------------------------------------------
 * דוגמת שרת מינימלי (Node.js + Express) לקבלת פניות מטופס יצירת הקשר ושליחתן
 * באימייל באמצעות Nodemailer. זהו קובץ דוגמה/reference — אינו מותקן או מורץ
 * אוטומטית. כדי לחבר אותו בפועל:
 *
 *   1. cd server
 *   2. npm init -y
 *   3. npm install express nodemailer cors dotenv express-rate-limit
 *   4. העתיקו את .env.example ל-.env ומלאו ערכים אמיתיים
 *   5. node contact-server-example.js
 *   6. עדכנו את CONTACT_ENDPOINT ב-js/config.js לכתובת השרת (למשל
 *      http://localhost:4000/api/contact בפיתוח, או כתובת הפרודקשן שלכם)
 *
 * בפרודקשן מומלץ לארח את זה כ-Serverless Function (Vercel/Netlify/AWS
 * Lambda) במקום שרת עומד, ולעולם לא לחשוף סודות (API keys, סיסמאות) בצד
 * הלקוח — הם צריכים לשבת רק כאן, במשתני סביבה בצד השרת.
 */

require("dotenv").config();
const express = require("express");
const cors = require("cors");
const nodemailer = require("nodemailer");
const rateLimit = require("express-rate-limit");

const app = express();
const PORT = process.env.PORT || 4000;

app.use(cors({ origin: process.env.ALLOWED_ORIGIN || "*" }));
app.use(express.json({ limit: "20kb" }));

// הגנה בסיסית מפני הצפה/ספאם: מקסימום 5 בקשות ל-15 דקות לכל IP
const contactLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 5,
  standardHeaders: true,
  legacyHeaders: false,
  message: { ok: false, error: "יותר מדי בקשות, נסו שוב מאוחר יותר." }
});

function isValidEmail(v) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(v || "").trim());
}

app.post("/api/contact", contactLimiter, async (req, res) => {
  try {
    const { fullName, company, email, phone, projectType, budget, message, websiteUrl } = req.body || {};

    // honeypot: אם שדה מוסתר זה מלא — כנראה בוט, מתעלמים בשקט
    if (websiteUrl) return res.json({ ok: true });

    if (!fullName || String(fullName).trim().length < 2) {
      return res.status(400).json({ ok: false, error: "שם מלא נדרש." });
    }
    if (!isValidEmail(email)) {
      return res.status(400).json({ ok: false, error: "כתובת אימייל לא תקינה." });
    }
    if (!projectType) {
      return res.status(400).json({ ok: false, error: "יש לבחור סוג פרויקט." });
    }
    if (!message || String(message).trim().length < 20) {
      return res.status(400).json({ ok: false, error: "תיאור הפרויקט קצר מדי." });
    }

    const transporter = nodemailer.createTransport({
      host: process.env.SMTP_HOST,
      port: Number(process.env.SMTP_PORT || 587),
      secure: process.env.SMTP_SECURE === "true",
      auth: {
        user: process.env.SMTP_USER,
        pass: process.env.SMTP_PASS
      }
    });

    await transporter.sendMail({
      from: process.env.MAIL_FROM,
      to: process.env.MAIL_TO,
      replyTo: email,
      subject: `פנייה חדשה מהאתר — ${fullName} (${projectType})`,
      text: [
        `שם מלא: ${fullName}`,
        `חברה/עסק: ${company || "-"}`,
        `אימייל: ${email}`,
        `טלפון: ${phone || "-"}`,
        `סוג פרויקט: ${projectType}`,
        `תקציב משוער: ${budget || "-"}`,
        "",
        "תיאור הפרויקט:",
        message
      ].join("\n")
    });

    return res.json({ ok: true });
  } catch (err) {
    console.error("[contact] failed:", err);
    return res.status(500).json({ ok: false, error: "שגיאת שרת. נסו שוב מאוחר יותר." });
  }
});

app.listen(PORT, () => {
  console.log(`Contact API listening on http://localhost:${PORT}`);
});
